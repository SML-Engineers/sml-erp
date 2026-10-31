from django.db import migrations

# The same supplier invoice cannot be entered twice (owner's decision, 31 Oct 2026): the
# database refuses a voucher line whose supplier and invoice number (ignoring case and
# spaces) are already on another voucher that still counts. Deleted, rejected, amended and
# cancelled vouchers free their invoices. The service gives the friendly message first.

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
    RAISE EXCEPTION 'Invoice % of this supplier is already on voucher %', NEW.invoice_no, clash
      USING ERRCODE = 'unique_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER vouchers_unique_supplier_invoice
BEFORE INSERT OR UPDATE OF invoice_no, voucher_id ON vouchers_voucherline
FOR EACH ROW EXECUTE FUNCTION vouchers_unique_supplier_invoice();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS vouchers_unique_supplier_invoice ON vouchers_voucherline;
DROP FUNCTION IF EXISTS vouchers_unique_supplier_invoice();
"""


class Migration(migrations.Migration):
    dependencies = [("vouchers", "0006_cancellation")]

    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
