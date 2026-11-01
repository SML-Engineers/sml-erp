import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Purchase orders (backlog P16-04, spec 5A.1).
# - Numbered PO{YY}{MM}{DD}{XX}, as on the owner's sample PO26061701.
# - Every PO is approved by the Director: the "purchase_order" document type, level 2.
# - Once a PO leaves draft the database refuses changing what was ordered; only the status,
#   the approval time, the reason it ended and the received quantities (P16-06) change.
#   Closed, cancelled and revised POs stay that way. Nothing but a draft is deleted.

SERIES = ("purchase_order", "Purchase orders", "PO{YY}{MM}{DD}{XX}", "daily", "grow")


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
    if director and not ApprovalRule.objects.filter(document_type="purchase_order").exists():
        ApprovalRule.objects.create(document_type="purchase_order", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="purchase_order", defaults={"enabled": True, "after_days": 2}
    )


FORWARD = """
CREATE OR REPLACE FUNCTION purchasing_order_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Purchase order % cannot be deleted', OLD.number
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status IN ('closed', 'cancelled', 'revised') AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'Purchase order % is % for good', OLD.number, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'draft' AND (
       NEW.number IS DISTINCT FROM OLD.number
    OR NEW.revision IS DISTINCT FROM OLD.revision
    OR NEW.parent_id IS DISTINCT FROM OLD.parent_id
    OR NEW.supplier_id IS DISTINCT FROM OLD.supplier_id
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
    OR NEW.po_date IS DISTINCT FROM OLD.po_date
    OR NEW.delivery_date IS DISTINCT FROM OLD.delivery_date
    OR NEW.deliver_to IS DISTINCT FROM OLD.deliver_to
    OR NEW.pay_mode IS DISTINCT FROM OLD.pay_mode
    OR NEW.payment_terms IS DISTINCT FROM OLD.payment_terms
    OR NEW.currency_id IS DISTINCT FROM OLD.currency_id
    OR NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate
    OR NEW.notes IS DISTINCT FROM OLD.notes
    OR NEW.subtotal IS DISTINCT FROM OLD.subtotal
    OR NEW.tax_total IS DISTINCT FROM OLD.tax_total
    OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
    OR NEW.total_lkr IS DISTINCT FROM OLD.total_lkr
    OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
  ) THEN
    RAISE EXCEPTION 'Purchase order % has left draft and cannot be changed; revise it instead',
      OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION purchasing_line_guard() RETURNS trigger AS $$
DECLARE
  st TEXT;
BEGIN
  SELECT o.status INTO st FROM purchasing_purchaseorder o
   WHERE o.id = CASE WHEN TG_OP = 'INSERT' THEN NEW.order_id ELSE OLD.order_id END;
  IF st IS NULL OR st = 'draft' THEN
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' AND NOT (
       NEW.order_id IS DISTINCT FROM OLD.order_id
    OR NEW.line_no IS DISTINCT FROM OLD.line_no
    OR NEW.item_id IS DISTINCT FROM OLD.item_id
    OR NEW.description IS DISTINCT FROM OLD.description
    OR NEW.unit IS DISTINCT FROM OLD.unit
    OR NEW.quantity IS DISTINCT FROM OLD.quantity
    OR NEW.unit_price IS DISTINCT FROM OLD.unit_price
    OR NEW.amount IS DISTINCT FROM OLD.amount
    OR NEW.tax_code_id IS DISTINCT FROM OLD.tax_code_id
    OR NEW.tax_amount IS DISTINCT FROM OLD.tax_amount
    OR NEW.total IS DISTINCT FROM OLD.total
  ) THEN
    RETURN NEW;  -- only the received quantity changed (goods receipts)
  END IF;
  RAISE EXCEPTION 'The lines of a purchase order that has left draft cannot change'
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER purchasing_order_guard
BEFORE UPDATE OR DELETE ON purchasing_purchaseorder
FOR EACH ROW EXECUTE FUNCTION purchasing_order_guard();

CREATE TRIGGER purchasing_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON purchasing_purchaseorderline
FOR EACH ROW EXECUTE FUNCTION purchasing_line_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS purchasing_line_guard ON purchasing_purchaseorderline;
DROP TRIGGER IF EXISTS purchasing_order_guard ON purchasing_purchaseorder;
DROP FUNCTION IF EXISTS purchasing_line_guard();
DROP FUNCTION IF EXISTS purchasing_order_guard();
"""


def money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


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
    initial = True

    dependencies = [
        ("core", "0019_purchasing_roles"),
        ("accounting", "0004_taxes"),
        ("masters", "0010_costing_rates"),
        ("inventory", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PurchaseOrder",
            fields=[
                id_field(),
                ("number", models.CharField(db_index=True, max_length=30)),
                ("revision", models.PositiveSmallIntegerField(default=0)),
                ("po_date", models.DateField()),
                ("delivery_date", models.DateField(blank=True, null=True)),
                ("deliver_to", models.TextField(blank=True)),
                (
                    "pay_mode",
                    models.CharField(
                        choices=[("online", "Online"), ("cheque", "Cheque"), ("cash", "Cash")],
                        default="online",
                        max_length=10,
                    ),
                ),
                ("payment_terms", models.CharField(blank=True, max_length=100)),
                (
                    "exchange_rate",
                    models.DecimalField(decimal_places=6, default=1, max_digits=18),
                ),
                ("rate_date", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("awaiting_approval", "Waiting for the Director"),
                            ("approved", "Approved"),
                            ("partly_received", "Partly received"),
                            ("received", "Received"),
                            ("closed", "Closed short"),
                            ("cancelled", "Cancelled"),
                            ("revised", "Replaced by a revision"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("subtotal", money(default=0)),
                ("tax_total", money(default=0)),
                ("total_amount", money(default=0)),
                ("total_lkr", money(default=0)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("end_reason", models.TextField(blank=True)),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
                ("currency", fk("masters.currency")),
                ("division", fk("core.division")),
                (
                    "parent",
                    fk("purchasing.purchaseorder", related_name="revisions", null=True),
                ),
                ("supplier", fk("masters.supplier", related_name="purchase_orders")),
            ],
            options={
                "ordering": ["-po_date", "-number", "-revision"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("number", "revision"), name="purchasing_po_revision"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="PurchaseOrderLine",
            fields=[
                id_field(),
                ("line_no", models.PositiveSmallIntegerField()),
                ("description", models.CharField(max_length=300)),
                ("unit", models.CharField(max_length=10)),
                ("quantity", qty()),
                ("unit_price", money()),
                ("amount", money()),
                ("tax_amount", money(default=0)),
                ("total", money()),
                ("received_quantity", qty(default=0)),
                ("item", fk("inventory.item")),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="purchasing.purchaseorder",
                    ),
                ),
                ("tax_code", fk("accounting.taxcode", null=True)),
            ],
            options={
                "ordering": ["order", "line_no"],
                "constraints": [
                    models.UniqueConstraint(fields=("order", "line_no"), name="purchasing_line_no"),
                    models.CheckConstraint(
                        condition=models.Q(("quantity__gt", 0)), name="purchasing_qty_pos"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("received_quantity__gte", 0)),
                        name="purchasing_received_pos",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
