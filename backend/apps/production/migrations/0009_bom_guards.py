from django.db import migrations

# P3-04: an approved or obsolete BOM never changes (only approved -> obsolete when a new
# revision is approved) and is never deleted; its lines and outputs change only while it is
# a draft. The Production Manager approves BOMs (approval engine, "bom").
SQL = """
CREATE OR REPLACE FUNCTION production_bom_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'BOM revision % is %: it is never deleted', OLD.revision, OLD.status
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status IN ('approved', 'obsolete') AND NOT (
       OLD.status = 'approved' AND NEW.status = 'obsolete'
       AND (NEW.item_id, NEW.revision, NEW.kind, NEW.division_id, NEW.drawing_revision,
            NEW.effective_from, NEW.base_quantity, NEW.reject_pct, NEW.notes)
           IS NOT DISTINCT FROM
           (OLD.item_id, OLD.revision, OLD.kind, OLD.division_id, OLD.drawing_revision,
            OLD.effective_from, OLD.base_quantity, OLD.reject_pct, OLD.notes)
       AND NEW.mould_id IS NOT DISTINCT FROM OLD.mould_id
       AND NEW.max_regrind_pct IS NOT DISTINCT FROM OLD.max_regrind_pct
       AND NEW.approved_at IS NOT DISTINCT FROM OLD.approved_at) THEN
    RAISE EXCEPTION 'An approved BOM never changes; make a new revision'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_bom_guard
BEFORE UPDATE OR DELETE ON production_bom
FOR EACH ROW EXECUTE FUNCTION production_bom_guard();

CREATE OR REPLACE FUNCTION production_bom_part_guard() RETURNS trigger AS $$
DECLARE
  state text;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  SELECT status INTO state FROM production_bom
   WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.bom_id ELSE NEW.bom_id END;
  -- A draft BOM being deleted takes its lines with it (state is then null).
  IF state IS NOT NULL AND state <> 'draft' THEN
    RAISE EXCEPTION 'The lines of a BOM that is % never change', state
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_bomline_guard
BEFORE INSERT OR UPDATE OR DELETE ON production_bomline
FOR EACH ROW EXECUTE FUNCTION production_bom_part_guard();

CREATE TRIGGER production_bomoutput_guard
BEFORE INSERT OR UPDATE OR DELETE ON production_bomoutput
FOR EACH ROW EXECUTE FUNCTION production_bom_part_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_bomoutput_guard ON production_bomoutput;
DROP TRIGGER IF EXISTS production_bomline_guard ON production_bomline;
DROP FUNCTION IF EXISTS production_bom_part_guard();
DROP TRIGGER IF EXISTS production_bom_guard ON production_bom;
DROP FUNCTION IF EXISTS production_bom_guard();
"""


def seed(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    manager = Role.objects.filter(code="production_manager").first()
    if manager and not ApprovalRule.objects.filter(document_type="bom").exists():
        ApprovalRule.objects.create(document_type="bom", level=2, role=manager)
    ApprovalReminder.objects.get_or_create(
        document_type="bom", defaults={"enabled": True, "after_days": 1}
    )


class Migration(migrations.Migration):
    dependencies = [("production", "0008_boms"), ("core", "0027_company_epf_etf")]

    operations = [
        migrations.RunSQL(SQL, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
