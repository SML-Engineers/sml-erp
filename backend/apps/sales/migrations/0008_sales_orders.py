import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Sales orders (backlog P15-10, spec 5.3).
# - Numbered SO{YY}{MM}{DD}{XX}, in the style of quotations.
# - A repeat order entered directly (without a quotation) is approved by the Director before
#   it is confirmed: the "sales_order" document type, level 2 = Director.
# - The database refuses changing an order once it has left draft (its customer, PO, terms,
#   figures, lines and delivery schedule); only its status moves on. Nothing is deleted
#   once confirmed. A customer advance can be against a sales order (P15-09).

FORWARD = """
CREATE OR REPLACE FUNCTION sales_order_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Sales order % cannot be deleted', OLD.number
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status IN ('completed', 'cancelled') AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'Sales order % is % for good', OLD.number, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'draft' AND (
       FALSE
    OR NEW.number IS DISTINCT FROM OLD.number
    OR NEW.source IS DISTINCT FROM OLD.source
    OR NEW.quotation_id IS DISTINCT FROM OLD.quotation_id
    OR NEW.proforma_id IS DISTINCT FROM OLD.proforma_id
    OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
    OR NEW.contact_id IS DISTINCT FROM OLD.contact_id
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
    OR NEW.order_date IS DISTINCT FROM OLD.order_date
    OR NEW.customer_po IS DISTINCT FROM OLD.customer_po
    OR NEW.po_date IS DISTINCT FROM OLD.po_date
    OR NEW.currency_id IS DISTINCT FROM OLD.currency_id
    OR NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate
    OR NEW.payment_terms IS DISTINCT FROM OLD.payment_terms
    OR NEW.incoterm IS DISTINCT FROM OLD.incoterm
    OR NEW.delivery_address IS DISTINCT FROM OLD.delivery_address
    OR NEW.notes IS DISTINCT FROM OLD.notes
    OR NEW.discount_pct IS DISTINCT FROM OLD.discount_pct
    OR NEW.discount_total IS DISTINCT FROM OLD.discount_total
    OR NEW.subtotal IS DISTINCT FROM OLD.subtotal
    OR NEW.tax_total IS DISTINCT FROM OLD.tax_total
    OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
    OR NEW.total_lkr IS DISTINCT FROM OLD.total_lkr
  ) THEN
    RAISE EXCEPTION 'Sales order % is confirmed and cannot be changed', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sales_order_line_guard() RETURNS trigger AS $$
DECLARE
  ids BIGINT[] := ARRAY[]::BIGINT[];
  order_ids BIGINT[];
BEGIN
  IF TG_TABLE_NAME = 'sales_salesorderline' THEN
    IF TG_OP <> 'INSERT' THEN ids := ids || OLD.order_id; END IF;
    IF TG_OP <> 'DELETE' THEN ids := ids || NEW.order_id; END IF;
    order_ids := ids;
  ELSE
    IF TG_OP <> 'INSERT' THEN ids := ids || OLD.line_id; END IF;
    IF TG_OP <> 'DELETE' THEN ids := ids || NEW.line_id; END IF;
    SELECT ARRAY_AGG(l.order_id) INTO order_ids FROM sales_salesorderline l WHERE l.id = ANY(ids);
  END IF;
  IF EXISTS (
    SELECT 1 FROM sales_salesorder o WHERE o.id = ANY(order_ids) AND o.status <> 'draft'
  ) THEN
    RAISE EXCEPTION 'The lines and delivery schedule of a confirmed sales order cannot change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_order_guard
BEFORE UPDATE OR DELETE ON sales_salesorder
FOR EACH ROW EXECUTE FUNCTION sales_order_guard();

CREATE TRIGGER sales_salesorderline_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_salesorderline
FOR EACH ROW EXECUTE FUNCTION sales_order_line_guard();

CREATE TRIGGER sales_deliveryschedule_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_deliveryschedule
FOR EACH ROW EXECUTE FUNCTION sales_order_line_guard();

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
    OR NEW.sales_order_id IS DISTINCT FROM OLD.sales_order_id
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
DROP TRIGGER IF EXISTS sales_deliveryschedule_guard ON sales_deliveryschedule;
DROP TRIGGER IF EXISTS sales_salesorderline_guard ON sales_salesorderline;
DROP TRIGGER IF EXISTS sales_order_guard ON sales_salesorder;
DROP FUNCTION IF EXISTS sales_order_line_guard();
DROP FUNCTION IF EXISTS sales_order_guard();
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

SERIES = ("sales_order", "Sales orders", "SO{YY}{MM}{DD}{XX}", "daily", "grow")


def seed(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    document_type, name, number_format, reset, when_full = SERIES
    NumberSeries.objects.get_or_create(
        document_type=document_type,
        defaults={
            "name": name,
            "format": number_format,
            "reset_period": reset,
            "when_full": when_full,
        },
    )
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    director = Role.objects.filter(code="director").first()
    if director and not ApprovalRule.objects.filter(document_type="sales_order").exists():
        ApprovalRule.objects.create(document_type="sales_order", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="sales_order", defaults={"enabled": True, "after_days": 3}
    )


def money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


def fk(to, related_name="+", null=False):
    return models.ForeignKey(
        blank=null,
        null=null,
        on_delete=django.db.models.deletion.PROTECT,
        related_name=related_name,
        to=to,
    )


def id_field():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0004_taxes"),
        ("core", "0017_receipt_action"),
        ("masters", "0010_costing_rates"),
        ("sales", "0007_proforma"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SalesOrder",
            fields=[
                ("id", id_field()),
                ("number", models.CharField(max_length=30, unique=True)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("quotation", "Quotation"),
                            ("proforma", "Proforma invoice"),
                            ("direct", "Repeat order, entered directly"),
                        ],
                        max_length=10,
                    ),
                ),
                ("order_date", models.DateField()),
                (
                    "customer_po",
                    models.CharField(blank=True, max_length=50, verbose_name="Customer's PO no."),
                ),
                (
                    "po_date",
                    models.DateField(blank=True, null=True, verbose_name="Customer's PO date"),
                ),
                (
                    "exchange_rate",
                    models.DecimalField(decimal_places=6, default=1, max_digits=18),
                ),
                ("rate_date", models.DateField(blank=True, null=True)),
                ("payment_terms", models.CharField(blank=True, max_length=200)),
                (
                    "incoterm",
                    models.CharField(blank=True, max_length=3, verbose_name="Delivery term"),
                ),
                ("delivery_address", models.TextField(blank=True)),
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
                            ("awaiting_approval", "Awaiting approval"),
                            ("open", "Open"),
                            ("partly_delivered", "Partly delivered"),
                            ("completed", "Completed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("cancel_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("contact", fk("masters.customercontact", null=True)),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
                ("currency", fk("masters.currency")),
                ("customer", fk("masters.customer", related_name="sales_orders")),
                ("division", fk("core.division")),
                ("proforma", fk("sales.proformainvoice", related_name="sales_orders", null=True)),
                ("quotation", fk("sales.quotation", related_name="sales_orders", null=True)),
            ],
            options={
                "ordering": ["-order_date", "-number"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("exchange_rate__gt", 0),
                            ("discount_pct__gte", 0),
                            ("discount_pct__lt", 100),
                        ),
                        name="sales_order_figures",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="SalesOrderLine",
            fields=[
                ("id", id_field()),
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
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="sales.salesorder",
                    ),
                ),
                (
                    "quotation_line",
                    fk("sales.quotationline", related_name="sales_order_lines", null=True),
                ),
                ("tax_code", fk("accounting.taxcode", null=True)),
            ],
            options={
                "ordering": ["order", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("order", "line_no"), name="sales_order_line_no"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("quantity__gt", 0), ("unit_price__gte", 0)),
                        name="sales_order_line_figures",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DeliverySchedule",
            fields=[
                ("id", id_field()),
                ("seq", models.PositiveSmallIntegerField()),
                ("due_date", models.DateField()),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=18)),
                (
                    "line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="schedule",
                        to="sales.salesorderline",
                    ),
                ),
            ],
            options={
                "ordering": ["line", "due_date", "seq"],
                "constraints": [
                    models.UniqueConstraint(fields=("line", "seq"), name="sales_schedule_seq"),
                    models.CheckConstraint(
                        condition=models.Q(("quantity__gt", 0)), name="sales_schedule_quantity"
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="customeradvance",
            name="sales_order",
            field=fk("sales.salesorder", related_name="advances", null=True),
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
