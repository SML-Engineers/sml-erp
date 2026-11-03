import django.db.models.deletion
from django.db import migrations, models

# Export invoices and exchange differences (backlog P2-09).
# - Tax invoices, receipts and advance set-offs carry their currency, the exchange rate used
#   and their LKR values. Existing rows were all in LKR: they get the base currency, rate 1
#   and LKR values equal to their amounts. Issued and posted rows are frozen by their database
#   guards, so those guards are paused only for this one-time fill.
# - The database now also refuses: a receipt paying an invoice in another currency; setting
#   off an advance against an invoice in another currency, or more than the advance (in its
#   currency); and changing a receipt's currency, rate or LKR amount once recorded.

FILL = """
-- Foreign keys are checked at once, so no check is left pending when the columns are made
-- required just after (PostgreSQL refuses to alter a table with pending checks).
SET CONSTRAINTS ALL IMMEDIATE;
ALTER TABLE sales_taxinvoice DISABLE TRIGGER sales_invoice_guard;
ALTER TABLE sales_creditnote DISABLE TRIGGER sales_cn_guard;
ALTER TABLE sales_customerreceipt DISABLE TRIGGER sales_receipt_guard;
ALTER TABLE sales_receiptallocation DISABLE TRIGGER sales_allocation_guard;
ALTER TABLE sales_advancesetoff DISABLE TRIGGER sales_set_off_guard;

UPDATE sales_taxinvoice
  SET currency_id = (SELECT id FROM masters_currency WHERE is_base ORDER BY id LIMIT 1),
      total_lkr = total_amount;
UPDATE sales_creditnote SET total_lkr = total_amount;
UPDATE sales_customerreceipt
  SET currency_id = (SELECT id FROM masters_currency WHERE is_base ORDER BY id LIMIT 1),
      amount_lkr = amount;
UPDATE sales_receiptallocation SET carrying_lkr = amount;
UPDATE sales_advancesetoff SET amount_lkr = amount, carrying_lkr = amount;

ALTER TABLE sales_taxinvoice ENABLE TRIGGER sales_invoice_guard;
ALTER TABLE sales_creditnote ENABLE TRIGGER sales_cn_guard;
ALTER TABLE sales_customerreceipt ENABLE TRIGGER sales_receipt_guard;
ALTER TABLE sales_receiptallocation ENABLE TRIGGER sales_allocation_guard;
ALTER TABLE sales_advancesetoff ENABLE TRIGGER sales_set_off_guard;
SET CONSTRAINTS ALL DEFERRED;
"""

GUARDS = """
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

CREATE OR REPLACE FUNCTION sales_allocation_guard() RETURNS trigger AS $$
DECLARE
  rec record;
  inv record;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'What a receipt paid never changes' USING ERRCODE = 'restrict_violation';
  END IF;
  SELECT number, status, customer_id, currency_id INTO rec
    FROM sales_customerreceipt WHERE id = NEW.receipt_id;
  IF rec.status <> 'awaiting_approval' THEN
    RAISE EXCEPTION 'Receipt % has been decided: nothing is added to it', rec.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  SELECT number, status, customer_id, currency_id INTO inv FROM sales_taxinvoice
    WHERE id = NEW.invoice_id FOR UPDATE;
  IF inv.status <> 'issued' OR inv.customer_id <> rec.customer_id THEN
    RAISE EXCEPTION 'A receipt pays only issued invoices of its own customer'
      USING ERRCODE = 'check_violation';
  END IF;
  IF inv.currency_id <> rec.currency_id THEN
    RAISE EXCEPTION 'Receipt % is in another currency than invoice %', rec.number, inv.number
      USING ERRCODE = 'check_violation';
  END IF;
  IF sales_invoice_open(NEW.invoice_id) < NEW.amount THEN
    RAISE EXCEPTION 'Receipt % pays more than is open on invoice %', rec.number, inv.number
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sales_set_off_guard() RETURNS trigger AS $$
DECLARE
  adv record;
  inv record;
  used numeric;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'An advance set-off never changes' USING ERRCODE = 'restrict_violation';
  END IF;
  SELECT number, status, customer_id, currency_id, amount INTO adv FROM sales_customeradvance
    WHERE id = NEW.advance_id FOR UPDATE;
  SELECT number, status, customer_id, currency_id INTO inv FROM sales_taxinvoice
    WHERE id = NEW.invoice_id FOR UPDATE;
  IF adv.status <> 'approved' OR inv.status <> 'issued' OR inv.customer_id <> adv.customer_id THEN
    RAISE EXCEPTION 'An approved advance is set off only against an issued invoice of its customer'
      USING ERRCODE = 'check_violation';
  END IF;
  IF inv.currency_id <> adv.currency_id THEN
    RAISE EXCEPTION 'Advance % is in another currency than invoice %', adv.number, inv.number
      USING ERRCODE = 'check_violation';
  END IF;
  IF sales_invoice_open(NEW.invoice_id) < NEW.amount THEN
    RAISE EXCEPTION 'Advance % sets off more than is open on invoice %', adv.number, inv.number
      USING ERRCODE = 'check_violation';
  END IF;
  SELECT COALESCE(SUM(amount), 0) INTO used FROM sales_advancesetoff WHERE advance_id = NEW.advance_id;
  IF used + NEW.amount > adv.amount THEN
    RAISE EXCEPTION 'Advance % has less left than %', adv.number, NEW.amount
      USING ERRCODE = 'check_violation';
  END IF;
  -- The advance's check constraint refuses setting off more than it holds in LKR.
  UPDATE sales_customeradvance SET set_off_lkr = set_off_lkr + NEW.amount_lkr
    WHERE id = NEW.advance_id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


def currency(null):
    return models.ForeignKey(
        blank=False,
        null=null,
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to="masters.currency",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0013_credit_control"),
        ("masters", "0011_limit_no_maximum"),
    ]

    operations = [
        migrations.AddField("taxinvoice", "currency", currency(null=True)),
        migrations.AddField(
            "taxinvoice",
            "exchange_rate",
            models.DecimalField(decimal_places=6, default=1, max_digits=18),
        ),
        migrations.AddField("taxinvoice", "rate_date", models.DateField(blank=True, null=True)),
        migrations.AddField(
            "taxinvoice", "total_lkr", money(default=0, verbose_name="Total (LKR)")
        ),
        migrations.AddField(
            "creditnote", "total_lkr", money(default=0, verbose_name="Total (LKR)")
        ),
        migrations.AddField("customerreceipt", "currency", currency(null=True)),
        migrations.AddField(
            "customerreceipt",
            "exchange_rate",
            models.DecimalField(decimal_places=6, default=1, max_digits=18),
        ),
        migrations.AddField(
            "customerreceipt", "rate_date", models.DateField(blank=True, null=True)
        ),
        migrations.AddField(
            "customerreceipt", "amount_lkr", money(default=0, verbose_name="Amount (LKR)")
        ),
        migrations.AddField("receiptallocation", "carrying_lkr", money(default=0)),
        migrations.AddField("advancesetoff", "amount_lkr", money(default=0)),
        migrations.AddField("advancesetoff", "carrying_lkr", money(default=0)),
        migrations.RunSQL(FILL, migrations.RunSQL.noop),
        migrations.AlterField("taxinvoice", "currency", currency(null=False)),
        migrations.AlterField("customerreceipt", "currency", currency(null=False)),
        migrations.RunSQL(GUARDS, migrations.RunSQL.noop),
    ]
