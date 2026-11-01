import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Goods receiving notes (backlog P16-06, spec 5A.2).
# - Numbered GRN{YY}{MM}{DD}{XX}.
# - Excess over the PO, and reversing a confirmed GRN, are approved by the Director
#   ("goods_receipt" and "goods_receipt_reversal" document types, level 2).
# - Once a GRN leaves draft the database refuses changing it or its lines; only its status and
#   the confirmation and reversal fields move on. A reversed GRN stays reversed. Only a draft
#   is deleted. Photos are never removed once the GRN is confirmed.

SERIES = ("goods_receipt", "Goods receiving notes", "GRN{YY}{MM}{DD}{XX}", "daily", "grow")


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
    for kind in ("goods_receipt", "goods_receipt_reversal"):
        if director and not ApprovalRule.objects.filter(document_type=kind).exists():
            ApprovalRule.objects.create(document_type=kind, level=2, role=director)
        ApprovalReminder.objects.get_or_create(
            document_type=kind, defaults={"enabled": True, "after_days": 1}
        )


FORWARD = """
CREATE OR REPLACE FUNCTION inventory_grn_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'GRN % cannot be deleted', OLD.number USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status = 'reversed' AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'GRN % is reversed for good', OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'draft' AND (
       NEW.number IS DISTINCT FROM OLD.number
    OR NEW.purchase_order_id IS DISTINCT FROM OLD.purchase_order_id
    OR NEW.supplier_id IS DISTINCT FROM OLD.supplier_id
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
    OR NEW.store_id IS DISTINCT FROM OLD.store_id
    OR NEW.receipt_date IS DISTINCT FROM OLD.receipt_date
    OR NEW.delivery_note_no IS DISTINCT FROM OLD.delivery_note_no
    OR NEW.vehicle_no IS DISTINCT FROM OLD.vehicle_no
    OR NEW.supplier_invoice_no IS DISTINCT FROM OLD.supplier_invoice_no
    OR NEW.notes IS DISTINCT FROM OLD.notes
    OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
    OR (OLD.confirmed_at IS NOT NULL AND (
          NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at
       OR NEW.confirmed_by_id IS DISTINCT FROM OLD.confirmed_by_id))
  ) THEN
    RAISE EXCEPTION 'GRN % has left draft and cannot be changed; reverse it instead', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION inventory_grn_child_guard() RETURNS trigger AS $$
DECLARE
  st TEXT;
BEGIN
  SELECT r.status INTO st FROM inventory_goodsreceipt r
   WHERE r.id = CASE WHEN TG_OP = 'INSERT' THEN NEW.receipt_id ELSE OLD.receipt_id END;
  IF st IS NOT NULL AND st <> 'draft' THEN
    RAISE EXCEPTION 'The lines and photos of a GRN that has left draft cannot change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER inventory_grn_guard
BEFORE UPDATE OR DELETE ON inventory_goodsreceipt
FOR EACH ROW EXECUTE FUNCTION inventory_grn_guard();

CREATE TRIGGER inventory_grn_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON inventory_goodsreceiptline
FOR EACH ROW EXECUTE FUNCTION inventory_grn_child_guard();

CREATE TRIGGER inventory_grn_photo_guard
BEFORE UPDATE OR DELETE ON inventory_goodsreceiptphoto
FOR EACH ROW EXECUTE FUNCTION inventory_grn_child_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS inventory_grn_photo_guard ON inventory_goodsreceiptphoto;
DROP TRIGGER IF EXISTS inventory_grn_line_guard ON inventory_goodsreceiptline;
DROP TRIGGER IF EXISTS inventory_grn_guard ON inventory_goodsreceipt;
DROP FUNCTION IF EXISTS inventory_grn_child_guard();
DROP FUNCTION IF EXISTS inventory_grn_guard();
"""


def qty(**extra):
    return models.DecimalField(decimal_places=3, max_digits=18, **extra)


def fk(to, related_name="+", null=False):
    extra = {"blank": True, "null": True} if null else {}
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name=related_name, to=to, **extra
    )


def id_field():
    return (
        "id",
        models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
        ("purchasing", "0001_initial"),
        ("core", "0019_purchasing_roles"),
        ("masters", "0010_costing_rates"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="GoodsReceipt",
            fields=[
                id_field(),
                ("number", models.CharField(max_length=30, unique=True)),
                ("receipt_date", models.DateField()),
                ("delivery_note_no", models.CharField(blank=True, max_length=50)),
                ("vehicle_no", models.CharField(blank=True, max_length=30)),
                ("supplier_invoice_no", models.CharField(blank=True, max_length=50)),
                ("notes", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("awaiting_approval", "Excess waiting for the Director"),
                            ("confirmed", "Confirmed"),
                            ("reversal_requested", "Reversal waiting for the Director"),
                            ("reversed", "Reversed"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("reversal_reason", models.TextField(blank=True)),
                ("reversed_at", models.DateTimeField(blank=True, null=True)),
                ("confirmed_by", fk(settings.AUTH_USER_MODEL, null=True)),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
                ("division", fk("core.division")),
                ("purchase_order", fk("purchasing.purchaseorder", related_name="receipts")),
                ("store", fk("inventory.store", related_name="receipts")),
                ("supplier", fk("masters.supplier")),
            ],
            options={"ordering": ["-receipt_date", "-number"]},
        ),
        migrations.CreateModel(
            name="GoodsReceiptLine",
            fields=[
                id_field(),
                ("line_no", models.PositiveSmallIntegerField()),
                ("outstanding_quantity", qty(default=0)),
                ("received_quantity", qty(default=0)),
                ("damaged_quantity", qty(default=0)),
                ("excess_quantity", qty(default=0)),
                ("notes", models.CharField(blank=True, max_length=300)),
                ("item", fk("inventory.item")),
                ("po_line", fk("purchasing.purchaseorderline", related_name="receipt_lines")),
                (
                    "receipt",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="inventory.goodsreceipt",
                    ),
                ),
            ],
            options={
                "ordering": ["receipt", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("receipt", "line_no"), name="inventory_grn_line_no"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("received_quantity__gte", 0))
                        & models.Q(("damaged_quantity__gte", 0))
                        & models.Q(("damaged_quantity__lte", models.F("received_quantity"))),
                        name="inventory_grn_quantities",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="GoodsReceiptPhoto",
            fields=[
                id_field(),
                ("file", models.FileField(upload_to="receipts/%Y/%m/")),
                ("file_name", models.CharField(max_length=200)),
                ("content_type", models.CharField(max_length=100)),
                ("size", models.PositiveIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("uploaded_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "receipt",
                    fk("inventory.goodsreceipt", related_name="photos"),
                ),
                ("uploaded_by", fk(settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
