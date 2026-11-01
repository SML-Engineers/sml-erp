import django.db.models.deletion
from django.db import migrations, models

# Advance payments on a purchase order (backlog P16-11a): a voucher line can pay in advance
# on an approved PO of the payee. The advances on a PO, on vouchers that still count, can
# never add up to more than the PO (database guard).
# - What vouchers pay on a supplier invoice now also leaves room for the advances set off
#   against it (purchasing_advancesetoff, purchasing migration 0003).

FORWARD = r"""
CREATE OR REPLACE FUNCTION vouchers_advance_within_order() RETURNS trigger AS $$
DECLARE
  po RECORD;
  payee bigint;
  others numeric;
BEGIN
  IF NEW.advance_order_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT * INTO po FROM purchasing_purchaseorder WHERE id = NEW.advance_order_id FOR UPDATE;
  SELECT v.payee_id INTO payee FROM vouchers_voucher v WHERE v.id = NEW.voucher_id;
  IF payee IS DISTINCT FROM po.supplier_id THEN
    RAISE EXCEPTION 'Purchase order % is not of this voucher''s payee', po.number
      USING ERRCODE = 'check_violation';
  END IF;
  SELECT coalesce(sum(l.amount + l.tax_amount), 0) INTO others
    FROM vouchers_voucherline l JOIN vouchers_voucher v ON v.id = l.voucher_id
   WHERE l.advance_order_id = NEW.advance_order_id
     AND l.id <> coalesce(NEW.id, -1)
     AND v.status NOT IN ('deleted', 'rejected', 'amended', 'cancelled');
  IF others + NEW.amount + NEW.tax_amount > po.total_lkr THEN
    RAISE EXCEPTION 'The advances on purchase order % would be more than the order', po.number
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION vouchers_invoice_not_overpaid() RETURNS trigger AS $$
DECLARE
  inv RECORD;
  payee bigint;
  others numeric;
  set_off numeric;
BEGIN
  IF NEW.supplier_invoice_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT * INTO inv FROM purchasing_supplierinvoice WHERE id = NEW.supplier_invoice_id FOR UPDATE;
  SELECT v.payee_id INTO payee FROM vouchers_voucher v WHERE v.id = NEW.voucher_id;
  IF inv.status <> 'posted' THEN
    RAISE EXCEPTION 'Supplier invoice % is not matched and posted', inv.number
      USING ERRCODE = 'check_violation';
  END IF;
  IF payee IS DISTINCT FROM inv.supplier_id THEN
    RAISE EXCEPTION 'Supplier invoice % is not of this voucher''s payee', inv.number
      USING ERRCODE = 'check_violation';
  END IF;
  SELECT coalesce(sum(l.amount + l.tax_amount), 0) INTO others
    FROM vouchers_voucherline l JOIN vouchers_voucher v ON v.id = l.voucher_id
   WHERE l.supplier_invoice_id = NEW.supplier_invoice_id
     AND l.id <> coalesce(NEW.id, -1)
     AND v.status NOT IN ('deleted', 'rejected', 'amended', 'cancelled');
  SELECT coalesce(sum(s.amount), 0) INTO set_off
    FROM purchasing_advancesetoff s WHERE s.invoice_id = NEW.supplier_invoice_id;
  IF others + set_off + NEW.amount + NEW.tax_amount > inv.total_lkr THEN
    RAISE EXCEPTION 'Supplier invoice % would be paid more than its total', inv.number
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER vouchers_advance_within_order
BEFORE INSERT OR UPDATE OF advance_order_id, amount, tax_amount, voucher_id
ON vouchers_voucherline
FOR EACH ROW EXECUTE FUNCTION vouchers_advance_within_order();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS vouchers_advance_within_order ON vouchers_voucherline;
DROP FUNCTION IF EXISTS vouchers_advance_within_order();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("vouchers", "0009_pay_supplier_invoices"),
        ("purchasing", "0002_supplier_invoices"),
        ("accounting", "0007_supplier_advances_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="voucherline",
            name="advance_order",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="advance_lines",
                to="purchasing.purchaseorder",
            ),
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
