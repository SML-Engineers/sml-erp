from django.db import migrations

# P3-09: the Production Manager approves or returns shift reports (approval engine
# "shift_report"); an approved report goes back to "returned" only through an approved
# correction, whose approval reverses what the report posted. What approval put into stock
# (production receipts) is never changed except being marked undone by a correction, and a
# correction request is never deleted. Corrections are approved by the Production Manager,
# the Director, or a person the Admin gives "approve_production_corrections" (the Director
# confirming), never the person who asked (owner, 7 Nov 2026).

SQL = """
CREATE OR REPLACE FUNCTION production_shift_report_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A shift report is never deleted' USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF NEW.section_id <> OLD.section_id OR NEW.day <> OLD.day OR NEW.shift_id <> OLD.shift_id THEN
    RAISE EXCEPTION 'A shift report keeps its section, day and shift'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status IN ('submitted', 'approved') AND NOT (
       (OLD.status = 'submitted' AND NEW.status IN ('approved', 'returned'))
       OR (OLD.status = 'approved' AND NEW.status = 'returned')) THEN
    RAISE EXCEPTION 'The shift report is % and locked', OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status <> OLD.status AND NOT (
       (OLD.status IN ('draft', 'returned') AND NEW.status = 'submitted')
       OR (OLD.status = 'submitted' AND NEW.status IN ('approved', 'returned'))
       OR (OLD.status = 'approved' AND NEW.status = 'returned')) THEN
    RAISE EXCEPTION 'A shift report cannot go from % to %', OLD.status, NEW.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION production_receipt_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A production receipt is never deleted' USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF NOT NEW.undone
     OR (OLD.undone AND NEW.run_id IS NOT NULL)
     OR (NOT OLD.undone AND NEW.run_id IS DISTINCT FROM OLD.run_id)
     OR (NEW.id, NEW.report_id, NEW.order_id, NEW.item_id, NEW.is_regrind,
         NEW.quantity, NEW.material_value, NEW.regrind_credit, NEW.value, NEW.movement_id,
         NEW.created_at)
        IS DISTINCT FROM
        (OLD.id, OLD.report_id, OLD.order_id, OLD.item_id, OLD.is_regrind,
         OLD.quantity, OLD.material_value, OLD.regrind_credit, OLD.value, OLD.movement_id,
         OLD.created_at) THEN
    RAISE EXCEPTION 'A production receipt never changes; a correction marks it undone'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_receipt_guard
BEFORE UPDATE OR DELETE ON production_productionreceipt
FOR EACH ROW EXECUTE FUNCTION production_receipt_guard();

CREATE OR REPLACE FUNCTION production_correction_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A correction request is never deleted' USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status <> 'awaiting'
     OR NEW.reason <> OLD.reason OR NEW.original::text <> OLD.original::text
     OR NEW.report_id <> OLD.report_id OR NEW.requested_by_id <> OLD.requested_by_id THEN
    RAISE EXCEPTION 'A correction request never changes once decided, nor what it asked'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_correction_guard
BEFORE UPDATE OR DELETE ON production_shiftcorrection
FOR EACH ROW EXECUTE FUNCTION production_correction_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_correction_guard ON production_shiftcorrection;
DROP FUNCTION IF EXISTS production_correction_guard();
DROP TRIGGER IF EXISTS production_receipt_guard ON production_productionreceipt;
DROP FUNCTION IF EXISTS production_receipt_guard();
"""

ACTION = "approve_production_corrections"


def seed(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    RoleAction = apps.get_model("core", "RoleAction")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    manager = Role.objects.filter(code="production_manager").first()
    for document_type in ("shift_report", "shift_correction"):
        if manager and not ApprovalRule.objects.filter(document_type=document_type).exists():
            ApprovalRule.objects.create(document_type=document_type, level=2, role=manager)
        ApprovalReminder.objects.get_or_create(
            document_type=document_type, defaults={"enabled": True, "after_days": 1}
        )
    for code in ("production_manager", "director"):
        role = Role.objects.filter(code=code).first()
        if role is not None:
            RoleAction.objects.get_or_create(role=role, action=ACTION)


def unseed(apps, schema_editor):
    apps.get_model("core", "RoleAction").objects.filter(action=ACTION).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("production", "0018_shift_approval"),
        ("core", "0027_company_epf_etf"),
    ]

    operations = [migrations.RunSQL(SQL, BACKWARD), migrations.RunPython(seed, unseed)]
