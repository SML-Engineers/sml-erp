from django.db import migrations

# P3-11: a job order is never deleted, keeps its number and division, changes its part,
# quantity, purpose, operations and materials only while a draft, and moves only forward
# (draft → released → completed → closed; draft or released → cancelled). Its issues are
# insert-only. A request to issue more than the job allows is never deleted, and only a
# waiting one changes, and then only its decision. Plus the "JO" number series and the
# Production Manager approving those requests.

SQL = """
CREATE OR REPLACE FUNCTION production_job_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Job order % is never deleted; cancel it', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status IN ('closed', 'cancelled') THEN
    RAISE EXCEPTION 'Job order % is %: it never changes', OLD.number, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.number <> OLD.number OR NEW.division_id <> OLD.division_id THEN
    RAISE EXCEPTION 'A job order keeps its number and division'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'draft' AND (
       NEW.purpose <> OLD.purpose
       OR NEW.sales_line_id IS DISTINCT FROM OLD.sales_line_id
       OR NEW.item_id IS DISTINCT FROM OLD.item_id
       OR NEW.mould_id IS DISTINCT FROM OLD.mould_id
       OR NEW.quantity <> OLD.quantity
       OR NEW.description <> OLD.description
       OR NEW.drawing_no <> OLD.drawing_no
       OR NEW.drawing_revision <> OLD.drawing_revision
       OR NEW.due_date <> OLD.due_date
       OR NEW.routing_id IS DISTINCT FROM OLD.routing_id
       OR NEW.bom_id IS DISTINCT FROM OLD.bom_id) THEN
    RAISE EXCEPTION 'Job order % is released: what it makes never changes', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status <> OLD.status AND NOT (
       (OLD.status = 'draft' AND NEW.status IN ('released', 'cancelled'))
       OR (OLD.status = 'released' AND NEW.status IN ('completed', 'cancelled'))
       OR (OLD.status = 'completed' AND NEW.status = 'closed')) THEN
    RAISE EXCEPTION 'A job order cannot go from % to %', OLD.status, NEW.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_job_guard
BEFORE UPDATE OR DELETE ON production_joborder
FOR EACH ROW EXECUTE FUNCTION production_job_guard();

CREATE OR REPLACE FUNCTION production_job_lines_guard() RETURNS trigger AS $$
DECLARE
  state text;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  SELECT status INTO state FROM production_joborder
    WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.job_id ELSE NEW.job_id END;
  IF state IS NOT NULL AND state <> 'draft' THEN
    RAISE EXCEPTION 'The operations and materials of a released job never change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_job_operation_guard
BEFORE INSERT OR UPDATE OR DELETE ON production_joboperation
FOR EACH ROW EXECUTE FUNCTION production_job_lines_guard();

CREATE TRIGGER production_job_material_guard
BEFORE INSERT OR UPDATE OR DELETE ON production_jobmaterial
FOR EACH ROW EXECUTE FUNCTION production_job_lines_guard();

CREATE OR REPLACE FUNCTION production_job_issue_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'Issues to a job never change; return the material instead'
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_job_issue_guard
BEFORE UPDATE OR DELETE ON production_jobissue
FOR EACH ROW EXECUTE FUNCTION production_job_issue_guard();

CREATE OR REPLACE FUNCTION production_job_excess_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A request to issue more is never deleted'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status <> 'awaiting'
     OR NEW.job_id <> OLD.job_id OR NEW.component_id <> OLD.component_id
     OR NEW.quantity <> OLD.quantity OR NEW.reason <> OLD.reason
     OR NEW.created_by_id <> OLD.created_by_id OR NEW.created_at <> OLD.created_at THEN
    RAISE EXCEPTION 'A decided request to issue more never changes'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_job_excess_guard
BEFORE UPDATE OR DELETE ON production_jobexcess
FOR EACH ROW EXECUTE FUNCTION production_job_excess_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_job_excess_guard ON production_jobexcess;
DROP FUNCTION IF EXISTS production_job_excess_guard();
DROP TRIGGER IF EXISTS production_job_issue_guard ON production_jobissue;
DROP FUNCTION IF EXISTS production_job_issue_guard();
DROP TRIGGER IF EXISTS production_job_material_guard ON production_jobmaterial;
DROP TRIGGER IF EXISTS production_job_operation_guard ON production_joboperation;
DROP FUNCTION IF EXISTS production_job_lines_guard();
DROP TRIGGER IF EXISTS production_job_guard ON production_joborder;
DROP FUNCTION IF EXISTS production_job_guard();
"""


def seed(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    NumberSeries.objects.get_or_create(
        document_type="job_order",
        defaults={
            "name": "Job orders",
            "format": "JO{YY}{MM}{NNNN}",
            "reset_period": "monthly",
            "when_full": "grow",
        },
    )
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    manager = Role.objects.filter(code="production_manager").first()
    if manager and not ApprovalRule.objects.filter(document_type="job_excess").exists():
        ApprovalRule.objects.create(document_type="job_excess", level=2, role=manager)
    ApprovalReminder.objects.get_or_create(
        document_type="job_excess", defaults={"enabled": True, "after_days": 1}
    )


class Migration(migrations.Migration):
    dependencies = [
        ("production", "0022_job_orders"),
        ("core", "0027_company_epf_etf"),
    ]

    operations = [
        migrations.RunSQL(SQL, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
