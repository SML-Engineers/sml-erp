from django.db import migrations

# P3-03: an approved or obsolete routing never changes (only approved -> obsolete when a new
# revision is approved) and is never deleted; its operations change only while it is a draft.
# The Production Manager approves routings (approval engine, "routing").
SQL = """
CREATE OR REPLACE FUNCTION production_routing_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Routing revision % is %: it is never deleted', OLD.revision, OLD.status
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status IN ('approved', 'obsolete') AND NOT (
       OLD.status = 'approved' AND NEW.status = 'obsolete'
       AND NEW.item_id = OLD.item_id AND NEW.revision = OLD.revision
       AND NEW.drawing_revision = OLD.drawing_revision AND NEW.notes = OLD.notes
       AND NEW.approved_at IS NOT DISTINCT FROM OLD.approved_at) THEN
    RAISE EXCEPTION 'An approved routing never changes; make a new revision'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_routing_guard
BEFORE UPDATE OR DELETE ON production_routing
FOR EACH ROW EXECUTE FUNCTION production_routing_guard();

CREATE OR REPLACE FUNCTION production_operation_guard() RETURNS trigger AS $$
DECLARE
  state text;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  SELECT status INTO state FROM production_routing
   WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.routing_id ELSE NEW.routing_id END;
  -- A draft routing being deleted takes its operations with it (state is then null).
  IF state IS NOT NULL AND state <> 'draft' THEN
    RAISE EXCEPTION 'The operations of a routing that is % never change', state
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_operation_guard
BEFORE INSERT OR UPDATE OR DELETE ON production_routingoperation
FOR EACH ROW EXECUTE FUNCTION production_operation_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_operation_guard ON production_routingoperation;
DROP FUNCTION IF EXISTS production_operation_guard();
DROP TRIGGER IF EXISTS production_routing_guard ON production_routing;
DROP FUNCTION IF EXISTS production_routing_guard();
"""


def seed(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    manager = Role.objects.filter(code="production_manager").first()
    if manager and not ApprovalRule.objects.filter(document_type="routing").exists():
        ApprovalRule.objects.create(document_type="routing", level=2, role=manager)
    ApprovalReminder.objects.get_or_create(
        document_type="routing", defaults={"enabled": True, "after_days": 1}
    )


class Migration(migrations.Migration):
    dependencies = [("production", "0006_routings"), ("core", "0027_company_epf_etf")]

    operations = [
        migrations.RunSQL(SQL, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
