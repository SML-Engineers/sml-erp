import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Supplier invoices with three-way match (backlog P16-10, spec 5A.4).
# - Numbered SI{YY}{MM}{DD}{XX}; exceptions approved by the Director ("invoice_exception").
# - Once posted or cancelled an invoice never changes; its lines change only as a draft; its
#   scans are never removed once it has left draft.
# - The same supplier + invoice number (ignoring case and spaces) is refused against other
#   supplier invoices that are not cancelled and against vouchers that still count (owner's
#   decision 5, 31 Oct 2026). The voucher trigger checks supplier invoices the other way
#   (vouchers migration 0008).

SERIES = ("supplier_invoice", "Supplier invoices", "SI{YY}{MM}{DD}{XX}", "daily", "grow")


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
    if director and not ApprovalRule.objects.filter(document_type="invoice_exception").exists():
        ApprovalRule.objects.create(document_type="invoice_exception", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="invoice_exception", defaults={"enabled": True, "after_days": 1}
    )


FORWARD = r"""
CREATE OR REPLACE FUNCTION purchasing_invoice_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Supplier invoice % cannot be deleted', OLD.number
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status IN ('posted', 'cancelled') THEN
    RAISE EXCEPTION 'Supplier invoice % is % and cannot be changed', OLD.number, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION purchasing_invoice_child_guard() RETURNS trigger AS $$
DECLARE
  st TEXT;
BEGIN
  SELECT i.status INTO st FROM purchasing_supplierinvoice i
   WHERE i.id = CASE WHEN TG_OP = 'INSERT' THEN NEW.invoice_id ELSE OLD.invoice_id END;
  IF st IS NOT NULL AND st <> 'draft' THEN
    RAISE EXCEPTION 'The lines and scans of a supplier invoice that has left draft cannot change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
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
       AND v.status NOT IN ('deleted', 'rejected', 'amended', 'cancelled')
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

CREATE TRIGGER purchasing_invoice_guard
BEFORE UPDATE OR DELETE ON purchasing_supplierinvoice
FOR EACH ROW EXECUTE FUNCTION purchasing_invoice_guard();

CREATE TRIGGER purchasing_unique_supplier_invoice
BEFORE INSERT OR UPDATE OF invoice_no, supplier_id, status ON purchasing_supplierinvoice
FOR EACH ROW EXECUTE FUNCTION purchasing_unique_supplier_invoice();

CREATE TRIGGER purchasing_invoice_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON purchasing_supplierinvoiceline
FOR EACH ROW EXECUTE FUNCTION purchasing_invoice_child_guard();

CREATE TRIGGER purchasing_invoice_attachment_guard
BEFORE UPDATE OR DELETE ON purchasing_supplierinvoiceattachment
FOR EACH ROW EXECUTE FUNCTION purchasing_invoice_child_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS purchasing_invoice_attachment_guard ON purchasing_supplierinvoiceattachment;
DROP TRIGGER IF EXISTS purchasing_invoice_line_guard ON purchasing_supplierinvoiceline;
DROP TRIGGER IF EXISTS purchasing_unique_supplier_invoice ON purchasing_supplierinvoice;
DROP TRIGGER IF EXISTS purchasing_invoice_guard ON purchasing_supplierinvoice;
DROP FUNCTION IF EXISTS purchasing_unique_supplier_invoice();
DROP FUNCTION IF EXISTS purchasing_invoice_child_guard();
DROP FUNCTION IF EXISTS purchasing_invoice_guard();
"""


def id_field():
    return (
        "id",
        models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
    )


def money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


def fk(to, related_name="+", null=False):
    extra = {"blank": True, "null": True} if null else {}
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name=related_name, to=to, **extra
    )


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0001_initial"),
        ("inventory", "0005_stock_movements"),
        ("accounting", "0006_price_variance_account"),
        ("vouchers", "0007_unique_supplier_invoice"),
        ("core", "0019_purchasing_roles"),
        ("masters", "0010_costing_rates"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SupplierInvoice",
            fields=[
                id_field(),
                ("number", models.CharField(max_length=30, unique=True)),
                ("invoice_no", models.CharField(max_length=50)),
                ("invoice_date", models.DateField()),
                ("due_date", models.DateField()),
                ("stated_total", money(blank=True, null=True)),
                ("subtotal", money(default=0)),
                ("tax_total", money(default=0)),
                ("total_amount", money(default=0)),
                ("total_lkr", money(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("held", "Held: discrepancy"),
                            ("exception_requested", "Exception waiting for the Director"),
                            ("posted", "Matched and posted"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("discrepancies", models.JSONField(blank=True, default=list)),
                ("notes", models.TextField(blank=True)),
                ("exception_reason", models.TextField(blank=True)),
                ("cancel_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
                ("currency", fk("masters.currency")),
                ("division", fk("core.division")),
                ("journal_entry", fk("accounting.journalentry", null=True)),
                ("supplier", fk("masters.supplier")),
            ],
            options={"ordering": ["-invoice_date", "-number"]},
        ),
        migrations.CreateModel(
            name="SupplierInvoiceLine",
            fields=[
                id_field(),
                ("line_no", models.PositiveSmallIntegerField()),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=18)),
                ("unit_price", money()),
                ("amount", money(default=0)),
                ("tax_amount", money(default=0)),
                ("total", money(default=0)),
                ("po_unit_price", money(default=0)),
                ("grn_line", fk("inventory.goodsreceiptline", "invoice_lines")),
                ("item", fk("inventory.item")),
                ("tax_code", fk("accounting.taxcode", null=True)),
                ("po_tax_code", fk("accounting.taxcode", null=True)),
                (
                    "invoice",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="purchasing.supplierinvoice",
                    ),
                ),
            ],
            options={
                "ordering": ["invoice", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("invoice", "line_no"), name="purchasing_si_line_no"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("quantity__gt", 0)),
                        name="purchasing_si_line_quantity",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SupplierInvoiceAttachment",
            fields=[
                id_field(),
                ("file", models.FileField(upload_to="supplier-invoices/%Y/%m/")),
                ("file_name", models.CharField(max_length=200)),
                ("content_type", models.CharField(max_length=100)),
                ("size", models.PositiveIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("uploaded_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("invoice", fk("purchasing.supplierinvoice", "attachments")),
                ("uploaded_by", fk(settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
