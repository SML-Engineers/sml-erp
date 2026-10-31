from django.db import migrations, models

# A discount on quotations (owner, 31 Oct 2026; backlog P15-07b): a % on every line before
# taxes. The guard of migration 0004 now also refuses changing the discount once a
# quotation has left draft.

FORWARD = """
CREATE OR REPLACE FUNCTION sales_quotation_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Quotation % Rev % cannot be deleted', OLD.number, OLD.revision
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status <> 'draft' AND (
       NEW.number IS DISTINCT FROM OLD.number
    OR NEW.revision IS DISTINCT FROM OLD.revision
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
    OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
    OR NEW.contact_id IS DISTINCT FROM OLD.contact_id
    OR NEW.enquiry_ref IS DISTINCT FROM OLD.enquiry_ref
    OR NEW.quote_date IS DISTINCT FROM OLD.quote_date
    OR NEW.valid_until IS DISTINCT FROM OLD.valid_until
    OR NEW.currency_id IS DISTINCT FROM OLD.currency_id
    OR NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate
    OR NEW.payment_terms IS DISTINCT FROM OLD.payment_terms
    OR NEW.delivery_lead_time IS DISTINCT FROM OLD.delivery_lead_time
    OR NEW.incoterm IS DISTINCT FROM OLD.incoterm
    OR NEW.notes IS DISTINCT FROM OLD.notes
    OR NEW.discount_pct IS DISTINCT FROM OLD.discount_pct
    OR NEW.discount_total IS DISTINCT FROM OLD.discount_total
    OR NEW.subtotal IS DISTINCT FROM OLD.subtotal
    OR NEW.tax_total IS DISTINCT FROM OLD.tax_total
    OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
    OR NEW.total_lkr IS DISTINCT FROM OLD.total_lkr
  ) THEN
    RAISE EXCEPTION 'Quotation % Rev % is no longer a draft and cannot be changed; make a revision',
      OLD.number, OLD.revision USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

BACKWARD = """
CREATE OR REPLACE FUNCTION sales_quotation_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Quotation % Rev % cannot be deleted', OLD.number, OLD.revision
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status <> 'draft' AND (
       NEW.number IS DISTINCT FROM OLD.number
    OR NEW.revision IS DISTINCT FROM OLD.revision
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
    OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
    OR NEW.contact_id IS DISTINCT FROM OLD.contact_id
    OR NEW.enquiry_ref IS DISTINCT FROM OLD.enquiry_ref
    OR NEW.quote_date IS DISTINCT FROM OLD.quote_date
    OR NEW.valid_until IS DISTINCT FROM OLD.valid_until
    OR NEW.currency_id IS DISTINCT FROM OLD.currency_id
    OR NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate
    OR NEW.payment_terms IS DISTINCT FROM OLD.payment_terms
    OR NEW.delivery_lead_time IS DISTINCT FROM OLD.delivery_lead_time
    OR NEW.incoterm IS DISTINCT FROM OLD.incoterm
    OR NEW.notes IS DISTINCT FROM OLD.notes
    OR NEW.subtotal IS DISTINCT FROM OLD.subtotal
    OR NEW.tax_total IS DISTINCT FROM OLD.tax_total
    OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
    OR NEW.total_lkr IS DISTINCT FROM OLD.total_lkr
  ) THEN
    RAISE EXCEPTION 'Quotation % Rev % is no longer a draft and cannot be changed; make a revision',
      OLD.number, OLD.revision USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [("sales", "0005_customer_advances")]

    operations = [
        migrations.AddField(
            model_name="quotation",
            name="discount_pct",
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=5, verbose_name="Discount %"
            ),
        ),
        migrations.AddField(
            model_name="quotation",
            name="discount_total",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AddField(
            model_name="quotationline",
            name="discount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AddConstraint(
            model_name="quotation",
            constraint=models.CheckConstraint(
                condition=models.Q(("discount_pct__gte", 0), ("discount_pct__lt", 100)),
                name="sales_quotation_discount_range",
            ),
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
