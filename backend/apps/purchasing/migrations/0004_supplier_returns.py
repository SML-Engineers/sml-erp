import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Supplier returns and debit notes (backlog P16-12).
# - Returns numbered RTN{YY}{MM}{DD}{XX}, debit notes DN{YY}{MM}{DD}{XX}.
# - A return of goods QC had accepted is approved by the Director ("supplier_return").
# - A confirmed return, its lines and debit notes never change (database guards).
# - What vouchers pay on an invoice, the advances set off and the debit notes together never
#   exceed the invoice; set-offs leave room for the debit notes too.

SERIES = [
    ("supplier_return", "Supplier returns", "RTN{YY}{MM}{DD}{XX}", "daily", "grow"),
    ("debit_note", "Debit notes", "DN{YY}{MM}{DD}{XX}", "daily", "grow"),
]


def seed(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    for document_type, name, number_format, reset, when_full in SERIES:
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
    if director and not ApprovalRule.objects.filter(document_type="supplier_return").exists():
        ApprovalRule.objects.create(document_type="supplier_return", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="supplier_return", defaults={"enabled": True, "after_days": 1}
    )


FORWARD = r"""
CREATE OR REPLACE FUNCTION purchasing_return_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Return % cannot be deleted', OLD.number USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status = 'confirmed' THEN
    RAISE EXCEPTION 'Return % is confirmed and cannot be changed', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION purchasing_return_line_guard() RETURNS trigger AS $$
DECLARE
  st TEXT;
BEGIN
  SELECT r.status INTO st FROM purchasing_supplierreturn r
   WHERE r.id = CASE WHEN TG_OP = 'INSERT' THEN NEW.supplier_return_id
                     ELSE OLD.supplier_return_id END;
  IF st = 'confirmed' THEN
    RAISE EXCEPTION 'The lines of a confirmed return cannot change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION purchasing_debit_note_guard() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'A debit note is never changed or deleted' USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER purchasing_return_guard
BEFORE UPDATE OR DELETE ON purchasing_supplierreturn
FOR EACH ROW EXECUTE FUNCTION purchasing_return_guard();

CREATE TRIGGER purchasing_return_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON purchasing_supplierreturnline
FOR EACH ROW EXECUTE FUNCTION purchasing_return_line_guard();

CREATE TRIGGER purchasing_debit_note_guard
BEFORE UPDATE OR DELETE ON purchasing_debitnote
FOR EACH ROW EXECUTE FUNCTION purchasing_debit_note_guard();

CREATE OR REPLACE FUNCTION vouchers_invoice_not_overpaid() RETURNS trigger AS $$
DECLARE
  inv RECORD;
  payee bigint;
  others numeric;
  set_off numeric;
  debited numeric;
BEGIN
  IF NEW.supplier_invoice_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT * INTO inv FROM purchasing_supplierinvoice WHERE id = NEW.supplier_invoice_id FOR UPDATE;
  SELECT v.payee_id INTO payee FROM vouchers_voucher v WHERE v.id = NEW.voucher_id;
  IF inv.status <> 'posted' THEN
    RAISE EXCEPTION 'Supplier invoice % is not matched and posted', inv.number
      USING ERRCODE = 'check_violation';
  END IF;
  IF payee IS DISTINCT FROM inv.supplier_id THEN
    RAISE EXCEPTION 'Supplier invoice % is not of this voucher''s payee', inv.number
      USING ERRCODE = 'check_violation';
  END IF;
  SELECT coalesce(sum(l.amount + l.tax_amount), 0) INTO others
    FROM vouchers_voucherline l JOIN vouchers_voucher v ON v.id = l.voucher_id
   WHERE l.supplier_invoice_id = NEW.supplier_invoice_id
     AND l.id <> coalesce(NEW.id, -1)
     AND v.status NOT IN ('deleted', 'rejected', 'amended', 'cancelled');
  SELECT coalesce(sum(s.amount), 0) INTO set_off
    FROM purchasing_advancesetoff s WHERE s.invoice_id = NEW.supplier_invoice_id;
  SELECT coalesce(sum(d.total_lkr), 0) INTO debited
    FROM purchasing_debitnote d WHERE d.invoice_id = NEW.supplier_invoice_id;
  IF others + set_off + debited + NEW.amount + NEW.tax_amount > inv.total_lkr THEN
    RAISE EXCEPTION 'Supplier invoice % would be paid more than its total', inv.number
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION purchasing_setoff_limits() RETURNS trigger AS $$
DECLARE
  inv RECORD;
  line_total numeric;
  used_line numeric;
  used_invoice numeric;
  on_vouchers numeric;
  debited numeric;
BEGIN
  SELECT * INTO inv FROM purchasing_supplierinvoice WHERE id = NEW.invoice_id FOR UPDATE;
  SELECT l.amount + l.tax_amount INTO line_total FROM vouchers_voucherline l
   WHERE l.id = NEW.voucher_line_id;
  SELECT coalesce(sum(amount), 0) INTO used_line FROM purchasing_advancesetoff
   WHERE voucher_line_id = NEW.voucher_line_id;
  SELECT coalesce(sum(amount), 0) INTO used_invoice FROM purchasing_advancesetoff
   WHERE invoice_id = NEW.invoice_id;
  SELECT coalesce(sum(l.amount + l.tax_amount), 0) INTO on_vouchers
    FROM vouchers_voucherline l JOIN vouchers_voucher v ON v.id = l.voucher_id
   WHERE l.supplier_invoice_id = NEW.invoice_id
     AND v.status NOT IN ('deleted', 'rejected', 'amended', 'cancelled');
  SELECT coalesce(sum(d.total_lkr), 0) INTO debited
    FROM purchasing_debitnote d WHERE d.invoice_id = NEW.invoice_id;
  IF used_line + NEW.amount > line_total
     OR used_invoice + on_vouchers + debited + NEW.amount > inv.total_lkr THEN
    RAISE EXCEPTION 'The set-off is more than the advance or the invoice still owes'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

BACKWARD = """
DROP TRIGGER IF EXISTS purchasing_debit_note_guard ON purchasing_debitnote;
DROP TRIGGER IF EXISTS purchasing_return_line_guard ON purchasing_supplierreturnline;
DROP TRIGGER IF EXISTS purchasing_return_guard ON purchasing_supplierreturn;
DROP FUNCTION IF EXISTS purchasing_debit_note_guard();
DROP FUNCTION IF EXISTS purchasing_return_line_guard();
DROP FUNCTION IF EXISTS purchasing_return_guard();
"""


def id_field():
    return (
        "id",
        models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
    )


def money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


def qty(**extra):
    return models.DecimalField(decimal_places=3, max_digits=18, **extra)


def fk(to, related_name="+", null=False):
    extra = {"blank": True, "null": True} if null else {}
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name=related_name, to=to, **extra
    )


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0003_advance_set_offs"),
        ("inventory", "0006_returned_movements"),
        ("accounting", "0007_supplier_advances_role"),
        ("vouchers", "0010_advance_payments"),
        ("core", "0019_purchasing_roles"),
        ("masters", "0010_costing_rates"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SupplierReturn",
            fields=[
                id_field(),
                ("number", models.CharField(max_length=30, unique=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("rejected", "Rejected or damaged goods"),
                            ("accepted", "Goods QC had accepted"),
                        ],
                        max_length=10,
                    ),
                ),
                ("return_date", models.DateField()),
                ("reason", models.TextField()),
                ("vehicle_no", models.CharField(blank=True, max_length=30)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("awaiting_approval", "Waiting for the Director"),
                            ("confirmed", "Returned"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
                ("division", fk("core.division")),
                ("journal_entry", fk("accounting.journalentry", null=True)),
                ("receipt", fk("inventory.goodsreceipt", "returns")),
                ("supplier", fk("masters.supplier")),
            ],
            options={"ordering": ["-return_date", "-number"]},
        ),
        migrations.CreateModel(
            name="SupplierReturnLine",
            fields=[
                id_field(),
                ("line_no", models.PositiveSmallIntegerField()),
                ("lot_no", models.CharField(max_length=40)),
                ("quantity", qty()),
                ("uninvoiced_quantity", qty(default=0)),
                ("invoiced_quantity", qty(default=0)),
                ("value", money(default=0)),
                ("grn_line", fk("inventory.goodsreceiptline", "return_lines")),
                (
                    "supplier_return",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="purchasing.supplierreturn",
                    ),
                ),
            ],
            options={
                "ordering": ["supplier_return", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("supplier_return", "line_no"), name="purchasing_return_line_no"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("quantity__gt", 0)),
                        name="purchasing_return_quantity",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DebitNote",
            fields=[
                id_field(),
                ("number", models.CharField(max_length=30, unique=True)),
                ("quantity", qty()),
                ("amount", money()),
                ("tax_amount", money(default=0)),
                ("total_lkr", money()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("invoice", fk("purchasing.supplierinvoice", "debit_notes")),
                ("return_line", fk("purchasing.supplierreturnline", "debit_notes")),
                ("journal_entry", fk("accounting.journalentry")),
                ("supplier_return", fk("purchasing.supplierreturn", "debit_notes")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
