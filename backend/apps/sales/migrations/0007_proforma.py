import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Proforma invoices and their packing list (backlog P15-08, spec 5.2, 5.5).
# - Numbered in the owner's old style PI{YY}{MM}{DD}-{XX}, e.g. PI261031-01 (owner, 31 Oct
#   2026): the "proforma" series is changed from PI-{YYYY}-{NNNN} (never used yet).
# - The database refuses changing an issued or cancelled proforma (its figures, terms and
#   lines); an issued one can only be cancelled, with a reason. Nothing is ever deleted.
# - A customer advance can be against a proforma (P15-09); its guard covers that link too.

FORWARD = """
CREATE OR REPLACE FUNCTION sales_proforma_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Proforma % cannot be deleted', OLD.number
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status = 'cancelled' AND NEW.status <> 'cancelled' THEN
    RAISE EXCEPTION 'Proforma % is cancelled for good', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'draft' AND (
       NEW.status = 'draft'
    OR NEW.number IS DISTINCT FROM OLD.number
    OR NEW.quotation_id IS DISTINCT FROM OLD.quotation_id
    OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
    OR NEW.contact_id IS DISTINCT FROM OLD.contact_id
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
    OR NEW.issue_date IS DISTINCT FROM OLD.issue_date
    OR NEW.currency_id IS DISTINCT FROM OLD.currency_id
    OR NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate
    OR NEW.customer_po IS DISTINCT FROM OLD.customer_po
    OR NEW.payment_terms IS DISTINCT FROM OLD.payment_terms
    OR NEW.delivery_lead_time IS DISTINCT FROM OLD.delivery_lead_time
    OR NEW.incoterm IS DISTINCT FROM OLD.incoterm
    OR NEW.port_of_loading IS DISTINCT FROM OLD.port_of_loading
    OR NEW.port_of_destination IS DISTINCT FROM OLD.port_of_destination
    OR NEW.bank_account_id IS DISTINCT FROM OLD.bank_account_id
    OR NEW.advance_pct IS DISTINCT FROM OLD.advance_pct
    OR NEW.notes IS DISTINCT FROM OLD.notes
    OR NEW.discount_pct IS DISTINCT FROM OLD.discount_pct
    OR NEW.discount_total IS DISTINCT FROM OLD.discount_total
    OR NEW.subtotal IS DISTINCT FROM OLD.subtotal
    OR NEW.tax_total IS DISTINCT FROM OLD.tax_total
    OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
    OR NEW.total_lkr IS DISTINCT FROM OLD.total_lkr
  ) THEN
    RAISE EXCEPTION 'Proforma % is issued and cannot be changed; cancel it and make another',
      OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sales_proforma_line_guard() RETURNS trigger AS $$
DECLARE
  ids BIGINT[] := ARRAY[]::BIGINT[];
BEGIN
  IF TG_OP <> 'INSERT' THEN ids := ids || OLD.proforma_id; END IF;
  IF TG_OP <> 'DELETE' THEN ids := ids || NEW.proforma_id; END IF;
  IF EXISTS (
    SELECT 1 FROM sales_proformainvoice p WHERE p.id = ANY(ids) AND p.status <> 'draft'
  ) THEN
    RAISE EXCEPTION 'The lines of an issued proforma cannot change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_proforma_guard
BEFORE UPDATE OR DELETE ON sales_proformainvoice
FOR EACH ROW EXECUTE FUNCTION sales_proforma_guard();

CREATE TRIGGER sales_proformaline_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_proformaline
FOR EACH ROW EXECUTE FUNCTION sales_proforma_line_guard();

CREATE OR REPLACE FUNCTION sales_advance_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Advance % cannot be deleted', OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'awaiting_approval' AND (
       NEW.number IS DISTINCT FROM OLD.number
    OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
    OR NEW.quotation_id IS DISTINCT FROM OLD.quotation_id
    OR NEW.proforma_id IS DISTINCT FROM OLD.proforma_id
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
    OR NEW.receipt_date IS DISTINCT FROM OLD.receipt_date
    OR NEW.account_id IS DISTINCT FROM OLD.account_id
    OR NEW.method IS DISTINCT FROM OLD.method
    OR NEW.reference IS DISTINCT FROM OLD.reference
    OR NEW.currency_id IS DISTINCT FROM OLD.currency_id
    OR NEW.amount IS DISTINCT FROM OLD.amount
    OR NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate
    OR NEW.amount_lkr IS DISTINCT FROM OLD.amount_lkr
    OR NEW.status IS DISTINCT FROM OLD.status
    OR NEW.journal_entry_id IS DISTINCT FROM OLD.journal_entry_id
  ) THEN
    RAISE EXCEPTION 'Advance % is % and cannot be changed', OLD.number, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

"""

BACKWARD = """
DROP TRIGGER IF EXISTS sales_proformaline_guard ON sales_proformaline;
DROP TRIGGER IF EXISTS sales_proforma_guard ON sales_proformainvoice;
DROP FUNCTION IF EXISTS sales_proforma_line_guard();
DROP FUNCTION IF EXISTS sales_proforma_guard();
CREATE OR REPLACE FUNCTION sales_advance_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Advance % cannot be deleted', OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'awaiting_approval' AND (
       NEW.number IS DISTINCT FROM OLD.number
    OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
    OR NEW.quotation_id IS DISTINCT FROM OLD.quotation_id
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
    OR NEW.receipt_date IS DISTINCT FROM OLD.receipt_date
    OR NEW.account_id IS DISTINCT FROM OLD.account_id
    OR NEW.method IS DISTINCT FROM OLD.method
    OR NEW.reference IS DISTINCT FROM OLD.reference
    OR NEW.currency_id IS DISTINCT FROM OLD.currency_id
    OR NEW.amount IS DISTINCT FROM OLD.amount
    OR NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate
    OR NEW.amount_lkr IS DISTINCT FROM OLD.amount_lkr
    OR NEW.status IS DISTINCT FROM OLD.status
    OR NEW.journal_entry_id IS DISTINCT FROM OLD.journal_entry_id
  ) THEN
    RAISE EXCEPTION 'Advance % is % and cannot be changed', OLD.number, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

"""


def old_style_numbers(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    NumberSeries.objects.filter(document_type="proforma").update(
        format="PI{YY}{MM}{DD}-{XX}", reset_period="daily", when_full="grow"
    )


def new_style_numbers(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    NumberSeries.objects.filter(document_type="proforma").update(
        format="PI-{YYYY}-{NNNN}", reset_period="yearly"
    )


def money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


def optional(digits, places, **extra):
    return models.DecimalField(
        blank=True, decimal_places=places, max_digits=digits, null=True, **extra
    )


def fk(to, related_name="+", null=False):
    return models.ForeignKey(
        blank=null,
        null=null,
        on_delete=django.db.models.deletion.PROTECT,
        related_name=related_name,
        to=to,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0004_taxes"),
        ("core", "0017_receipt_action"),
        ("masters", "0010_costing_rates"),
        ("sales", "0006_discount"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProformaInvoice",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("number", models.CharField(max_length=30, unique=True)),
                ("issue_date", models.DateField()),
                (
                    "exchange_rate",
                    models.DecimalField(decimal_places=6, default=1, max_digits=18),
                ),
                ("rate_date", models.DateField(blank=True, null=True)),
                (
                    "customer_po",
                    models.CharField(blank=True, max_length=50, verbose_name="Customer's PO no."),
                ),
                ("payment_terms", models.CharField(blank=True, max_length=200)),
                ("delivery_lead_time", models.CharField(blank=True, max_length=100)),
                (
                    "incoterm",
                    models.CharField(blank=True, max_length=3, verbose_name="Delivery term"),
                ),
                ("port_of_loading", models.CharField(blank=True, max_length=100)),
                ("port_of_destination", models.CharField(blank=True, max_length=100)),
                (
                    "advance_pct",
                    models.DecimalField(
                        decimal_places=2, default=0, max_digits=5, verbose_name="Advance %"
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                (
                    "discount_pct",
                    models.DecimalField(
                        decimal_places=2, default=0, max_digits=5, verbose_name="Discount %"
                    ),
                ),
                ("discount_total", money(default=0)),
                ("subtotal", money(default=0)),
                ("tax_total", money(default=0)),
                ("total_amount", money(default=0)),
                ("total_lkr", money(default=0, verbose_name="Total (LKR)")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("issued", "Issued"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("cancel_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("issued_at", models.DateTimeField(blank=True, null=True)),
                ("bank_account", fk("masters.companyaccount", null=True)),
                ("contact", fk("masters.customercontact", null=True)),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
                ("currency", fk("masters.currency")),
                ("customer", fk("masters.customer", related_name="proformas")),
                ("division", fk("core.division")),
                ("quotation", fk("sales.quotation", related_name="proformas")),
            ],
            options={
                "ordering": ["-issue_date", "-number"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("exchange_rate__gt", 0),
                            ("advance_pct__gte", 0),
                            ("advance_pct__lte", 100),
                            ("discount_pct__gte", 0),
                            ("discount_pct__lt", 100),
                        ),
                        name="sales_proforma_figures",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ProformaLine",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("line_no", models.PositiveSmallIntegerField()),
                ("description", models.TextField()),
                ("drawing_no", models.CharField(blank=True, max_length=50)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=18)),
                ("unit", models.CharField(default="pcs", max_length=20)),
                ("unit_price", money()),
                ("is_tooling", models.BooleanField(default=False)),
                ("amount", money()),
                ("discount", money(default=0)),
                ("tax_amount", money(default=0)),
                ("total", money()),
                ("cartons", models.PositiveIntegerField(blank=True, null=True)),
                ("qty_per_carton", optional(18, 3)),
                ("net_weight_kg", optional(12, 3)),
                ("gross_weight_kg", optional(12, 3)),
                ("carton_length_cm", optional(8, 1)),
                ("carton_width_cm", optional(8, 1)),
                ("carton_height_cm", optional(8, 1)),
                (
                    "proforma",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="sales.proformainvoice",
                    ),
                ),
                ("quotation_line", fk("sales.quotationline", related_name="proforma_lines")),
                ("tax_code", fk("accounting.taxcode", null=True)),
            ],
            options={
                "ordering": ["proforma", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("proforma", "line_no"), name="sales_proforma_line_no"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("quantity__gt", 0), ("unit_price__gte", 0)),
                        name="sales_proforma_line_figures",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="customeradvance",
            name="proforma",
            field=fk("sales.proformainvoice", related_name="advances", null=True),
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(old_style_numbers, new_style_numbers),
    ]
