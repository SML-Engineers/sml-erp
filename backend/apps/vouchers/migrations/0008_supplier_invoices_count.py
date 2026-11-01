from django.db import migrations

# Supplier invoices entered in Accounts (backlog P16-10) count too: a voucher line cannot
# repeat a supplier + invoice number already on a supplier invoice that is not cancelled
# (owner's decision 5, 31 Oct 2026).

FORWARD = r"""
CREATE OR REPLACE FUNCTION vouchers_unique_supplier_invoice() RETURNS trigger AS $$
DECLARE
  payee bigint;
  clash text;
  key text;
BEGIN
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
     AND v.status NOT IN ('deleted', 'rejected', 'amended', 'cancelled')
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
"""

BACKWARD = r"""
CREATE OR REPLACE FUNCTION vouchers_unique_supplier_invoice() RETURNS trigger AS $$
DECLARE
  payee bigint;
  clash text;
  key text;
BEGIN
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
     AND v.status NOT IN ('deleted', 'rejected', 'amended', 'cancelled')
     AND upper(regexp_replace(l.invoice_no, '\s', '', 'g')) = key
   LIMIT 1;
  IF clash IS NOT NULL THEN
    RAISE EXCEPTION 'Invoice % of this supplier is already on voucher %', NEW.invoice_no, clash
      USING ERRCODE = 'unique_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("vouchers", "0007_unique_supplier_invoice"),
        ("purchasing", "0002_supplier_invoices"),
    ]

    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
