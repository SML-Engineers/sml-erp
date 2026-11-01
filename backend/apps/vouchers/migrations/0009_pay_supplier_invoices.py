import django.db.models.deletion
from django.db import migrations, models

# Payment vouchers from matched supplier invoices (backlog P16-11, spec 5A.5).
# - A voucher line may pay a posted supplier invoice; such a line is checked by the amount
#   still unpaid on the invoice instead of by its invoice number, so an invoice can be paid
#   in parts but never twice: the database refuses lines that would take what the vouchers
#   that still count pay on an invoice above its total.
# - The invoice-number uniqueness of voucher lines and supplier invoices leaves these lines
#   out (they repeat the invoice's own number on purpose).

COUNTING = "('deleted', 'rejected', 'amended', 'cancelled')"

FORWARD = rf"""
CREATE OR REPLACE FUNCTION vouchers_unique_supplier_invoice() RETURNS trigger AS $$
DECLARE
  payee bigint;
  clash text;
  key text;
BEGIN
  IF NEW.supplier_invoice_id IS NOT NULL THEN
    RETURN NEW;
  END IF;
  key := upper(regexp_replace(coalesce(NEW.invoice_no, ''), '\s', '', 'g'));
  IF key = '' THEN
    RETURN NEW;
  END IF;
  SELECT v.payee_id INTO payee FROM vouchers_voucher v WHERE v.id = NEW.voucher_id;
  IF payee IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT v.number INTO clash
    FROM vouchers_voucherline l JOIN vouchers_voucher v ON v.id = l.voucher_id
   WHERE v.payee_id = payee
     AND l.voucher_id <> NEW.voucher_id
     AND v.status NOT IN {COUNTING}
     AND upper(regexp_replace(l.invoice_no, '\s', '', 'g')) = key
   LIMIT 1;
  IF clash IS NOT NULL THEN
    clash := 'voucher ' || clash;
  ELSE
    SELECT 'supplier invoice ' || i.number INTO clash FROM purchasing_supplierinvoice i
     WHERE i.supplier_id = payee AND i.status <> 'cancelled'
       AND upper(regexp_replace(i.invoice_no, '\s', '', 'g')) = key
     LIMIT 1;
  END IF;
  IF clash IS NOT NULL THEN
    RAISE EXCEPTION 'Invoice % of this supplier is already on %', NEW.invoice_no, clash
      USING ERRCODE = 'unique_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION purchasing_unique_supplier_invoice() RETURNS trigger AS $$
DECLARE
  key text;
  clash text;
BEGIN
  IF NEW.status = 'cancelled' THEN
    RETURN NEW;
  END IF;
  key := upper(regexp_replace(coalesce(NEW.invoice_no, ''), '\s', '', 'g'));
  SELECT 'supplier invoice ' || i.number INTO clash FROM purchasing_supplierinvoice i
   WHERE i.supplier_id = NEW.supplier_id AND i.id <> NEW.id AND i.status <> 'cancelled'
     AND upper(regexp_replace(i.invoice_no, '\s', '', 'g')) = key
   LIMIT 1;
  IF clash IS NULL THEN
    SELECT 'voucher ' || v.number INTO clash
      FROM vouchers_voucherline l JOIN vouchers_voucher v ON v.id = l.voucher_id
     WHERE v.payee_id = NEW.supplier_id
       AND l.supplier_invoice_id IS NULL
       AND v.status NOT IN {COUNTING}
       AND upper(regexp_replace(l.invoice_no, '\s', '', 'g')) = key
     LIMIT 1;
  END IF;
  IF clash IS NOT NULL THEN
    RAISE EXCEPTION 'Invoice % of this supplier is already on %', NEW.invoice_no, clash
      USING ERRCODE = 'unique_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION vouchers_invoice_not_overpaid() RETURNS trigger AS $$
DECLARE
  inv RECORD;
  payee bigint;
  others numeric;
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
     AND v.status NOT IN {COUNTING};
  IF others + NEW.amount + NEW.tax_amount > inv.total_lkr THEN
    RAISE EXCEPTION 'Supplier invoice % would be paid more than its total', inv.number
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER vouchers_invoice_not_overpaid
BEFORE INSERT OR UPDATE OF supplier_invoice_id, amount, tax_amount, voucher_id
ON vouchers_voucherline
FOR EACH ROW EXECUTE FUNCTION vouchers_invoice_not_overpaid();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS vouchers_invoice_not_overpaid ON vouchers_voucherline;
DROP FUNCTION IF EXISTS vouchers_invoice_not_overpaid();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("vouchers", "0008_supplier_invoices_count"),
        ("purchasing", "0002_supplier_invoices"),
    ]

    operations = [
        migrations.AddField(
            model_name="voucherline",
            name="supplier_invoice",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="voucher_lines",
                to="purchasing.supplierinvoice",
            ),
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
