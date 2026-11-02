from django.db import migrations, models

# Goods received in a foreign currency are valued at the rate of the receipt date (IAS 21;
# backlog P16-19). The rate is fixed when the GRN is confirmed and never changes after.

GUARD = """
CREATE OR REPLACE FUNCTION inventory_grn_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'GRN % cannot be deleted', OLD.number USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status = 'reversed' AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'GRN % is reversed for good', OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'draft' AND (
       NEW.number IS DISTINCT FROM OLD.number
    OR NEW.purchase_order_id IS DISTINCT FROM OLD.purchase_order_id
    OR NEW.supplier_id IS DISTINCT FROM OLD.supplier_id
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
    OR NEW.store_id IS DISTINCT FROM OLD.store_id
    OR NEW.receipt_date IS DISTINCT FROM OLD.receipt_date
    OR NEW.delivery_note_no IS DISTINCT FROM OLD.delivery_note_no
    OR NEW.vehicle_no IS DISTINCT FROM OLD.vehicle_no
    OR NEW.supplier_invoice_no IS DISTINCT FROM OLD.supplier_invoice_no
    OR NEW.notes IS DISTINCT FROM OLD.notes
    OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
    OR (OLD.exchange_rate IS NOT NULL AND (
          NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate
       OR NEW.rate_date IS DISTINCT FROM OLD.rate_date))
    OR (OLD.confirmed_at IS NOT NULL AND (
          NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at
       OR NEW.confirmed_by_id IS DISTINCT FROM OLD.confirmed_by_id))
  ) THEN
    RAISE EXCEPTION 'GRN % has left draft and cannot be changed; reverse it instead', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [("inventory", "0008_price_differences")]

    operations = [
        migrations.AddField(
            model_name="goodsreceipt",
            name="exchange_rate",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name="goodsreceipt",
            name="rate_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunSQL(GUARD, migrations.RunSQL.noop),
    ]
