import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# Approval, revisions and status of quotations (backlog P15-06, spec 5.1).
# - Every quotation is approved by the Director before it is printed or sent (owner, 31 Oct
#   2026): the "quotation" document type, level 2 = Director, in the approval matrix.
# - The database refuses changes to a quotation that is no longer a draft (its customer,
#   terms, figures, lines, quantity breaks and costing); a change is a new revision. Only the
#   status and its own dates move on.

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

CREATE OR REPLACE FUNCTION sales_line_guard() RETURNS trigger AS $$
DECLARE
  ids BIGINT[] := ARRAY[]::BIGINT[];
  quotation_ids BIGINT[];
BEGIN
  IF TG_TABLE_NAME = 'sales_quotationline' THEN
    IF TG_OP <> 'INSERT' THEN ids := ids || OLD.quotation_id; END IF;
    IF TG_OP <> 'DELETE' THEN ids := ids || NEW.quotation_id; END IF;
    quotation_ids := ids;
  ELSIF TG_TABLE_NAME IN ('sales_quotationqtybreak', 'sales_quotationcosting') THEN
    IF TG_OP <> 'INSERT' THEN ids := ids || OLD.line_id; END IF;
    IF TG_OP <> 'DELETE' THEN ids := ids || NEW.line_id; END IF;
    SELECT ARRAY_AGG(l.quotation_id) INTO quotation_ids
      FROM sales_quotationline l WHERE l.id = ANY(ids);
  ELSE
    IF TG_OP <> 'INSERT' THEN ids := ids || OLD.costing_id; END IF;
    IF TG_OP <> 'DELETE' THEN ids := ids || NEW.costing_id; END IF;
    SELECT ARRAY_AGG(l.quotation_id) INTO quotation_ids
      FROM sales_quotationcosting c JOIN sales_quotationline l ON l.id = c.line_id
      WHERE c.id = ANY(ids);
  END IF;
  IF EXISTS (
    SELECT 1 FROM sales_quotation q WHERE q.id = ANY(quotation_ids) AND q.status <> 'draft'
  ) THEN
    RAISE EXCEPTION 'Quotation lines and costing cannot change after the draft; make a revision'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_quotation_guard
BEFORE UPDATE OR DELETE ON sales_quotation
FOR EACH ROW EXECUTE FUNCTION sales_quotation_guard();

CREATE TRIGGER sales_quotationline_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_quotationline
FOR EACH ROW EXECUTE FUNCTION sales_line_guard();

CREATE TRIGGER sales_quotationqtybreak_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_quotationqtybreak
FOR EACH ROW EXECUTE FUNCTION sales_line_guard();

CREATE TRIGGER sales_quotationcosting_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_quotationcosting
FOR EACH ROW EXECUTE FUNCTION sales_line_guard();

CREATE TRIGGER sales_quotationcostingoperation_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_quotationcostingoperation
FOR EACH ROW EXECUTE FUNCTION sales_line_guard();

CREATE TRIGGER sales_quotationcostingextra_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_quotationcostingextra
FOR EACH ROW EXECUTE FUNCTION sales_line_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS sales_quotationcostingextra_guard ON sales_quotationcostingextra;
DROP TRIGGER IF EXISTS sales_quotationcostingoperation_guard ON sales_quotationcostingoperation;
DROP TRIGGER IF EXISTS sales_quotationcosting_guard ON sales_quotationcosting;
DROP TRIGGER IF EXISTS sales_quotationqtybreak_guard ON sales_quotationqtybreak;
DROP TRIGGER IF EXISTS sales_quotationline_guard ON sales_quotationline;
DROP TRIGGER IF EXISTS sales_quotation_guard ON sales_quotation;
DROP FUNCTION IF EXISTS sales_line_guard();
DROP FUNCTION IF EXISTS sales_quotation_guard();
"""

REASONS = [
    ("price", "Price"),
    ("lead_time", "Delivery time"),
    ("quality", "Quality or specification"),
    ("relationship", "Customer relationship"),
    ("competitor", "Went to a competitor"),
    ("cancelled", "Customer cancelled the need"),
    ("no_response", "No response from the customer"),
    ("other", "Other"),
]


def seed(apps, schema_editor):
    """The Director approves every quotation (level 2); reminders after 3 days, as for
    vouchers."""
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    director = Role.objects.filter(code="director").first()
    if director and not ApprovalRule.objects.filter(document_type="quotation").exists():
        ApprovalRule.objects.create(document_type="quotation", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="quotation", defaults={"enabled": True, "after_days": 3}
    )


def user_fk():
    return models.ForeignKey(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to=settings.AUTH_USER_MODEL,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0016_sales_roles_active"),
        ("sales", "0003_moulding_costing"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="quotation",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="quotation",
            name="sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(model_name="quotation", name="sent_by", field=user_fk()),
        migrations.AddField(
            model_name="quotation",
            name="outcome_reason",
            field=models.CharField(
                blank=True, choices=REASONS, max_length=30, verbose_name="Why won or lost"
            ),
        ),
        migrations.AddField(
            model_name="quotation",
            name="outcome_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="quotation",
            name="outcome_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(model_name="quotation", name="outcome_by", field=user_fk()),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
