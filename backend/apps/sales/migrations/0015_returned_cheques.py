import django.db.models.deletion
from django.db import migrations, models

# Returned cheques (backlog P2-14). A posted cheque receipt can be marked returned once, with
# the date, the reason and the entry that puts the money back on the customer's account; the
# invoices it paid are open again. Nothing else on a posted receipt ever changes.

FORWARD = r"""
CREATE OR REPLACE FUNCTION sales_invoice_open(invoice bigint) RETURNS numeric AS $$
  SELECT i.total_amount
    - COALESCE((SELECT SUM(n.total_amount) FROM sales_creditnote n
                WHERE n.invoice_id = i.id AND n.status = 'approved'), 0)
    - COALESCE((SELECT SUM(a.amount) FROM sales_receiptallocation a
                JOIN sales_customerreceipt r ON r.id = a.receipt_id
                WHERE a.invoice_id = i.id AND r.status NOT IN ('rejected', 'returned')), 0)
    - COALESCE((SELECT SUM(s.amount) FROM sales_advancesetoff s
                WHERE s.invoice_id = i.id), 0)
  FROM sales_taxinvoice i WHERE i.id = $1;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION sales_receipt_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Receipt % cannot be deleted', OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.number IS DISTINCT FROM OLD.number
     OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
     OR NEW.receipt_date IS DISTINCT FROM OLD.receipt_date
     OR NEW.method IS DISTINCT FROM OLD.method
     OR NEW.account_id IS DISTINCT FROM OLD.account_id
     OR NEW.reference IS DISTINCT FROM OLD.reference
     OR NEW.cheque_date IS DISTINCT FROM OLD.cheque_date
     OR NEW.cheque_bank IS DISTINCT FROM OLD.cheque_bank
     OR NEW.currency_id IS DISTINCT FROM OLD.currency_id
     OR NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate
     OR NEW.amount IS DISTINCT FROM OLD.amount
     OR NEW.amount_lkr IS DISTINCT FROM OLD.amount_lkr
     OR NEW.notes IS DISTINCT FROM OLD.notes
     OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Receipt % cannot be changed once recorded', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status IN ('rejected', 'returned') THEN
    RAISE EXCEPTION 'Receipt % is % for good', OLD.number, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  -- A posted receipt changes once only: its cheque came back unpaid (P2-14).
  IF OLD.status = 'posted' AND NOT (
       NEW.status = 'returned' AND OLD.method = 'cheque'
       AND NEW.journal_entry_id IS NOT DISTINCT FROM OLD.journal_entry_id
       AND NEW.approved_by_id IS NOT DISTINCT FROM OLD.approved_by_id
       AND NEW.approved_at IS NOT DISTINCT FROM OLD.approved_at
       AND NEW.posted_at IS NOT DISTINCT FROM OLD.posted_at
       AND NEW.return_entry_id IS NOT NULL AND NEW.returned_on IS NOT NULL
  ) THEN
    RAISE EXCEPTION 'Receipt % is posted for good; only its returned cheque is recorded',
      OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'posted' AND (
       NEW.return_entry_id IS NOT NULL OR NEW.returned_on IS NOT NULL OR NEW.return_reason <> ''
  ) THEN
    RAISE EXCEPTION 'Only a posted cheque receipt is returned'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
       (OLD.status = 'awaiting_approval' AND NEW.status IN ('post_dated', 'posted', 'rejected'))
    OR (OLD.status = 'post_dated' AND NEW.status = 'posted')
    OR (OLD.status = 'posted' AND NEW.status = 'returned')
  ) THEN
    RAISE EXCEPTION 'Receipt % cannot go from % to %', OLD.number, OLD.status, NEW.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF (NEW.status IN ('posted', 'returned')) <> (NEW.journal_entry_id IS NOT NULL) THEN
    RAISE EXCEPTION 'A receipt has a journal entry exactly when it is posted'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

BACKWARD = r"""
CREATE OR REPLACE FUNCTION sales_invoice_open(invoice bigint) RETURNS numeric AS $$
  SELECT i.total_amount
    - COALESCE((SELECT SUM(n.total_amount) FROM sales_creditnote n
                WHERE n.invoice_id = i.id AND n.status = 'approved'), 0)
    - COALESCE((SELECT SUM(a.amount) FROM sales_receiptallocation a
                JOIN sales_customerreceipt r ON r.id = a.receipt_id
                WHERE a.invoice_id = i.id AND r.status <> 'rejected'), 0)
    - COALESCE((SELECT SUM(s.amount) FROM sales_advancesetoff s
                WHERE s.invoice_id = i.id), 0)
  FROM sales_taxinvoice i WHERE i.id = $1;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION sales_receipt_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Receipt % cannot be deleted', OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.number IS DISTINCT FROM OLD.number
     OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
     OR NEW.receipt_date IS DISTINCT FROM OLD.receipt_date
     OR NEW.method IS DISTINCT FROM OLD.method
     OR NEW.account_id IS DISTINCT FROM OLD.account_id
     OR NEW.reference IS DISTINCT FROM OLD.reference
     OR NEW.cheque_date IS DISTINCT FROM OLD.cheque_date
     OR NEW.cheque_bank IS DISTINCT FROM OLD.cheque_bank
     OR NEW.currency_id IS DISTINCT FROM OLD.currency_id
     OR NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate
     OR NEW.amount IS DISTINCT FROM OLD.amount
     OR NEW.amount_lkr IS DISTINCT FROM OLD.amount_lkr
     OR NEW.notes IS DISTINCT FROM OLD.notes
     OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Receipt % cannot be changed once recorded', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status IN ('posted', 'rejected') THEN
    RAISE EXCEPTION 'Receipt % is % for good', OLD.number, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
       (OLD.status = 'awaiting_approval' AND NEW.status IN ('post_dated', 'posted', 'rejected'))
    OR (OLD.status = 'post_dated' AND NEW.status = 'posted')
  ) THEN
    RAISE EXCEPTION 'Receipt % cannot go from % to %', OLD.number, OLD.status, NEW.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF (NEW.status = 'posted') <> (NEW.journal_entry_id IS NOT NULL) THEN
    RAISE EXCEPTION 'A receipt has a journal entry exactly when it is posted'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0014_export_invoices"),
        ("accounting", "0014_zero_rated_code"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customerreceipt",
            name="status",
            field=models.CharField(
                choices=[
                    ("awaiting_approval", "Awaiting approval"),
                    ("post_dated", "Approved, cheque not yet due"),
                    ("posted", "Approved and posted"),
                    ("rejected", "Rejected"),
                    ("returned", "Cheque returned"),
                ],
                default="awaiting_approval",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="customerreceipt",
            name="returned_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customerreceipt",
            name="return_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="customerreceipt",
            name="return_entry",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="returned_receipt",
                to="accounting.journalentry",
            ),
        ),
        migrations.AddConstraint(
            model_name="customerreceipt",
            constraint=models.CheckConstraint(
                condition=~models.Q(status="returned")
                | models.Q(
                    method="cheque",
                    journal_entry__isnull=False,
                    return_entry__isnull=False,
                    returned_on__isnull=False,
                ),
                name="sales_receipt_returned_cheque",
            ),
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
