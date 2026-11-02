import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Tax invoices (backlog P2-05, spec 6.1).
# - The number (YYMMM_QQQQ_XX, the "tax_invoice" series of P0-07b) is given when the invoice
#   is issued, so drafts leave no gaps in the tax office's series.
# - The database refuses changing or deleting an issued invoice, its lines and its taxes; an
#   invoice is issued only with its number and its journal entry; each delivery note line is
#   invoiced once; a delivery note on an issued invoice cannot be cancelled.
# - Sales accounts per division: goods and services, and tooling. Starting values from the
#   starter chart: WS 4010 Machined parts, IM 4020 Injection moulded products, HO 4000 Sales,
#   tooling 4030 Mould making. The Accountant changes them on Accounts -> Sales accounts.

FORWARD = """
CREATE OR REPLACE FUNCTION sales_invoice_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Tax invoice % cannot be deleted: a credit note corrects it', OLD.number
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status = 'issued' THEN
    RAISE EXCEPTION 'Tax invoice % has been issued: it is never changed', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.order_id IS DISTINCT FROM OLD.order_id
     OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id THEN
    RAISE EXCEPTION 'The order and author of an invoice never change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status = 'issued' AND (NEW.number = '' OR NEW.journal_entry_id IS NULL) THEN
    RAISE EXCEPTION 'A tax invoice is issued only with its number and its journal entry'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status = 'draft' AND NEW.number <> '' THEN
    RAISE EXCEPTION 'A draft invoice has no number' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_invoice_guard
BEFORE UPDATE OR DELETE ON sales_taxinvoice
FOR EACH ROW EXECUTE FUNCTION sales_invoice_guard();

CREATE OR REPLACE FUNCTION sales_invoice_child_guard() RETURNS trigger AS $$
DECLARE
  parent_id bigint;
  parent_status text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    parent_id := OLD.invoice_id;
  ELSE
    parent_id := NEW.invoice_id;
  END IF;
  SELECT status INTO parent_status FROM sales_taxinvoice WHERE id = parent_id;
  IF parent_status = 'issued' THEN
    RAISE EXCEPTION 'Tax invoice % has been issued: its lines and taxes never change', parent_id
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_invoice_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_taxinvoiceline
FOR EACH ROW EXECUTE FUNCTION sales_invoice_child_guard();

CREATE TRIGGER sales_invoice_tax_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_taxinvoicetax
FOR EACH ROW EXECUTE FUNCTION sales_invoice_child_guard();

CREATE OR REPLACE FUNCTION sales_dn_invoiced_guard() RETURNS trigger AS $$
BEGIN
  IF NEW.status = 'cancelled' AND OLD.status <> 'cancelled' AND EXISTS (
    SELECT 1 FROM sales_deliverynoteline l
    JOIN sales_taxinvoiceline il ON il.delivery_line_id = l.id
    JOIN sales_taxinvoice i ON i.id = il.invoice_id
    WHERE l.note_id = NEW.id AND i.status = 'issued'
  ) THEN
    RAISE EXCEPTION 'Delivery note % has been invoiced: a credit note corrects it', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_dn_invoiced_guard
BEFORE UPDATE ON sales_deliverynote
FOR EACH ROW EXECUTE FUNCTION sales_dn_invoiced_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS sales_dn_invoiced_guard ON sales_deliverynote;
DROP FUNCTION IF EXISTS sales_dn_invoiced_guard();
DROP TRIGGER IF EXISTS sales_invoice_tax_guard ON sales_taxinvoicetax;
DROP TRIGGER IF EXISTS sales_invoice_line_guard ON sales_taxinvoiceline;
DROP FUNCTION IF EXISTS sales_invoice_child_guard();
DROP TRIGGER IF EXISTS sales_invoice_guard ON sales_taxinvoice;
DROP FUNCTION IF EXISTS sales_invoice_guard();
"""

ACCOUNTS = {"WS": "4010", "IM": "4020", "HO": "4000"}
TOOLING = "4030"


def seed(apps, schema_editor):
    Division = apps.get_model("core", "Division")
    Account = apps.get_model("accounting", "Account")
    SalesAccount = apps.get_model("sales", "SalesAccount")
    tooling = Account.objects.filter(number=TOOLING, account_type="income").first()
    fallback = Account.objects.filter(number="4000", account_type="income").first()
    for division in Division.objects.all():
        account = (
            Account.objects.filter(
                number=ACCOUNTS.get(division.code, ""), account_type="income"
            ).first()
            or fallback
        )
        if account is not None and not SalesAccount.objects.filter(division=division).exists():
            SalesAccount.objects.create(
                division=division, account=account, tooling_account=tooling or account
            )


def money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


def id_field():
    return (
        "id",
        models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
    )


def fk(to, related_name="+", null=False, on_delete=django.db.models.deletion.PROTECT):
    extra = {"blank": True, "null": True} if null else {}
    return models.ForeignKey(on_delete=on_delete, related_name=related_name, to=to, **extra)


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0009_delivery_notes"),
        ("accounting", "0013_line_customer"),
        ("masters", "0011_limit_no_maximum"),
        ("core", "0020_tax_rate_action"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SalesAccount",
            fields=[
                id_field(),
                (
                    "division",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sales_account",
                        to="core.division",
                    ),
                ),
                ("account", fk("accounting.account")),
                ("tooling_account", fk("accounting.account")),
            ],
        ),
        migrations.CreateModel(
            name="TaxInvoice",
            fields=[
                id_field(),
                ("number", models.CharField(blank=True, max_length=40)),
                (
                    "status",
                    models.CharField(
                        choices=[("draft", "Draft"), ("issued", "Issued")],
                        default="draft",
                        max_length=10,
                    ),
                ),
                ("invoice_date", models.DateField()),
                ("supply_date", models.DateField()),
                ("due_date", models.DateField()),
                ("place_of_supply", models.CharField(blank=True, max_length=200)),
                ("terms", models.CharField(blank=True, max_length=200)),
                ("notes", models.TextField(blank=True)),
                ("supplier_name", models.CharField(blank=True, max_length=200)),
                ("supplier_tin", models.CharField(blank=True, max_length=50)),
                ("supplier_address", models.TextField(blank=True)),
                ("supplier_phone", models.CharField(blank=True, max_length=50)),
                ("supplier_email", models.CharField(blank=True, max_length=254)),
                ("customer_name", models.CharField(blank=True, max_length=200)),
                ("customer_tin", models.CharField(blank=True, max_length=50)),
                ("customer_address", models.TextField(blank=True)),
                ("customer_po", models.CharField(blank=True, max_length=50)),
                ("subtotal", money(default=0)),
                ("discount_total", money(default=0)),
                ("tax_total", money(default=0)),
                ("total_amount", money(default=0)),
                ("amount_in_words", models.CharField(blank=True, max_length=400)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("issued_at", models.DateTimeField(blank=True, null=True)),
                ("order", fk("sales.salesorder", "invoices")),
                ("customer", fk("masters.customer", "tax_invoices")),
                ("division", fk("core.division")),
                (
                    "journal_entry",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tax_invoice",
                        to="accounting.journalentry",
                    ),
                ),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
                ("issued_by", fk(settings.AUTH_USER_MODEL, null=True)),
            ],
            options={
                "ordering": ["-invoice_date", "-id"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("number", ""), _negated=True),
                        fields=("number",),
                        name="sales_invoice_number_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("status", "draft"))
                        | models.Q(("number", ""), _negated=True),
                        name="sales_invoice_issued_numbered",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="TaxInvoiceLine",
            fields=[
                id_field(),
                ("line_no", models.PositiveSmallIntegerField()),
                ("product_code", models.CharField(blank=True, max_length=50)),
                ("description", models.TextField()),
                ("po_no", models.CharField(blank=True, max_length=50)),
                ("unit", models.CharField(default="pcs", max_length=20)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=18)),
                ("rate", money()),
                ("amount", money()),
                ("discount", money(default=0)),
                ("tax_amount", money(default=0)),
                (
                    "invoice",
                    fk("sales.taxinvoice", "lines", on_delete=django.db.models.deletion.CASCADE),
                ),
                (
                    "delivery_line",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="invoice_line",
                        to="sales.deliverynoteline",
                    ),
                ),
                ("tax_code", fk("accounting.taxcode", null=True)),
                ("account", fk("accounting.account")),
            ],
            options={
                "ordering": ["invoice", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("invoice", "line_no"), name="sales_invoice_line_no"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("quantity__gt", 0), ("rate__gte", 0)),
                        name="sales_invoice_line_figures",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="TaxInvoiceTax",
            fields=[
                id_field(),
                ("seq", models.PositiveSmallIntegerField()),
                ("label", models.CharField(max_length=20)),
                ("rate", models.DecimalField(decimal_places=4, max_digits=7)),
                ("on_tax", models.BooleanField(default=False)),
                ("amount", money()),
                (
                    "invoice",
                    fk("sales.taxinvoice", "taxes", on_delete=django.db.models.deletion.CASCADE),
                ),
                ("component", fk("accounting.taxcomponent")),
            ],
            options={"ordering": ["invoice", "seq"]},
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
