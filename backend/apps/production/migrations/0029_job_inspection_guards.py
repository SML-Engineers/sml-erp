from django.db import migrations

# P3-14: a job inspection is never deleted; once passed or decided it never changes; while
# on hold or waiting for the Director only its decision fields change. Results change only
# while the inspection is being done. The Director approves deviations on a failed critical
# check ("job_deviation").

SQL = """
CREATE OR REPLACE FUNCTION production_job_inspection_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A job inspection is never deleted'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status IN ('passed', 'decided') THEN
    RAISE EXCEPTION 'A passed or decided job inspection never changes'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.job_id <> OLD.job_id OR NEW.operation_id <> OLD.operation_id
     OR NEW.stage <> OLD.stage OR NEW.inspector_id <> OLD.inspector_id
     OR NEW.created_at <> OLD.created_at THEN
    RAISE EXCEPTION 'A job inspection keeps its job, operation, stage and inspector'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status IN ('on_hold', 'deviation_requested') AND (
       NEW.pieces <> OLD.pieces OR NEW.notes <> OLD.notes
       OR NEW.inspected_at IS DISTINCT FROM OLD.inspected_at) THEN
    RAISE EXCEPTION 'A failed job inspection changes only by its decision'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_job_inspection_guard
BEFORE UPDATE OR DELETE ON production_jobinspection
FOR EACH ROW EXECUTE FUNCTION production_job_inspection_guard();

CREATE OR REPLACE FUNCTION production_job_result_guard() RETURNS trigger AS $$
DECLARE
  state text;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  SELECT status INTO state FROM production_jobinspection
    WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.inspection_id ELSE NEW.inspection_id END;
  IF state IS NOT NULL AND state <> 'draft' THEN
    RAISE EXCEPTION 'The results of a finished inspection never change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_job_result_guard
BEFORE INSERT OR UPDATE OR DELETE ON production_jobinspectionresult
FOR EACH ROW EXECUTE FUNCTION production_job_result_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_job_result_guard ON production_jobinspectionresult;
DROP FUNCTION IF EXISTS production_job_result_guard();
DROP TRIGGER IF EXISTS production_job_inspection_guard ON production_jobinspection;
DROP FUNCTION IF EXISTS production_job_inspection_guard();
"""


def seed(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    director = Role.objects.filter(code="director").first()
    if director and not ApprovalRule.objects.filter(document_type="job_deviation").exists():
        ApprovalRule.objects.create(document_type="job_deviation", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="job_deviation", defaults={"enabled": True, "after_days": 1}
    )


class Migration(migrations.Migration):
    dependencies = [
        ("production", "0028_job_inspections"),
        ("core", "0027_company_epf_etf"),
    ]

    operations = [
        migrations.RunSQL(SQL, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
