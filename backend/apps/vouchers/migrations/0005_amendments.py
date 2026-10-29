from django.db import migrations, models

# Amendments (backlog P1-05, spec 4.2). A Director-approved voucher is never edited: an
# amendment is a new revision. The database also refuses:
# - changing the payee, type, division, description or total of a voucher once it is
#   Director-approved, paid, amended (replaced) or deleted;
# - adding, changing or removing its lines or division splits.

FORWARD = """
CREATE OR REPLACE FUNCTION vouchers_voucher_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Voucher % cannot be deleted from the database; it is marked Deleted',
      OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.number IS DISTINCT FROM OLD.number THEN
    RAISE EXCEPTION 'Voucher numbers never change (%)', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status = 'deleted' THEN
    RAISE EXCEPTION 'Voucher % is deleted and cannot change', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status = 'deleted' AND OLD.status IN ('partly_paid', 'paid') THEN
    RAISE EXCEPTION 'Voucher % has payments and cannot be deleted', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status IN ('director_approved', 'partly_paid', 'paid', 'amended') AND (
       NEW.payee_id IS DISTINCT FROM OLD.payee_id
    OR NEW.transfer_to_id IS DISTINCT FROM OLD.transfer_to_id
    OR NEW.voucher_type_id IS DISTINCT FROM OLD.voucher_type_id
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
    OR NEW.description IS DISTINCT FROM OLD.description
    OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
  ) THEN
    RAISE EXCEPTION 'Voucher % is approved and cannot be edited; amend it instead', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION vouchers_line_guard() RETURNS trigger AS $$
DECLARE
  ids BIGINT[];
BEGIN
  IF TG_TABLE_NAME = 'vouchers_voucherline' THEN
    IF TG_OP = 'INSERT' THEN
      ids := ARRAY[NEW.voucher_id];
    ELSIF TG_OP = 'UPDATE' THEN
      ids := ARRAY[OLD.voucher_id, NEW.voucher_id];
    ELSE
      ids := ARRAY[OLD.voucher_id];
    END IF;
  ELSE
    IF TG_OP = 'INSERT' THEN
      SELECT ARRAY_AGG(l.voucher_id) INTO ids FROM vouchers_voucherline l WHERE l.id = NEW.line_id;
    ELSIF TG_OP = 'UPDATE' THEN
      SELECT ARRAY_AGG(l.voucher_id) INTO ids FROM vouchers_voucherline l
        WHERE l.id IN (OLD.line_id, NEW.line_id);
    ELSE
      SELECT ARRAY_AGG(l.voucher_id) INTO ids FROM vouchers_voucherline l WHERE l.id = OLD.line_id;
    END IF;
  END IF;
  IF EXISTS (
    SELECT 1 FROM vouchers_voucher v
    WHERE v.id = ANY(ids)
      AND v.status IN ('director_approved', 'partly_paid', 'paid', 'amended', 'deleted')
  ) THEN
    RAISE EXCEPTION 'The lines of an approved or closed voucher cannot change; amend it instead'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER vouchers_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON vouchers_voucherline
FOR EACH ROW EXECUTE FUNCTION vouchers_line_guard();

CREATE TRIGGER vouchers_split_guard
BEFORE INSERT OR UPDATE OR DELETE ON vouchers_voucherlinesplit
FOR EACH ROW EXECUTE FUNCTION vouchers_line_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS vouchers_split_guard ON vouchers_voucherlinesplit;
DROP TRIGGER IF EXISTS vouchers_line_guard ON vouchers_voucherline;
DROP FUNCTION IF EXISTS vouchers_line_guard();
"""

STATUSES = [
    ("draft", "Draft"),
    ("submitted", "Submitted"),
    ("accountant_approved", "Accountant approved"),
    ("director_approved", "Director approved"),
    ("returned", "Returned"),
    ("rejected", "Rejected"),
    ("partly_paid", "Partly paid"),
    ("paid", "Paid"),
    ("cancelled", "Cancelled"),
    ("deleted", "Deleted"),
    ("amended", "Amended"),
]


class Migration(migrations.Migration):
    dependencies = [("vouchers", "0004_delete_and_print")]

    operations = [
        migrations.AlterField(
            model_name="voucher",
            name="status",
            field=models.CharField(choices=STATUSES, default="draft", max_length=30),
        ),
        migrations.AddField(
            model_name="voucher",
            name="amendment_reason",
            field=models.CharField(blank=True, editable=False, max_length=500),
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
