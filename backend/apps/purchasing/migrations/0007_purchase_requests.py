import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Reorder levels and purchase requests (backlog P2-13).
# - A purchase request is numbered PR{YY}{MM}{NNNN} and approved through the approval engine
#   ("purchase_request"; the Director by default, which the Admin can change).
# - The database keeps a request's lines as they were once it leaves draft, and a request
#   that was rejected, cancelled or made into a purchase order never changes again.

FORWARD = """
CREATE OR REPLACE FUNCTION purchasing_request_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Purchase request % is never deleted; it is cancelled', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status IN ('rejected', 'cancelled', 'ordered') THEN
    RAISE EXCEPTION 'Purchase request % is closed and never changes', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.number IS DISTINCT FROM OLD.number
     OR NEW.division_id IS DISTINCT FROM OLD.division_id
     OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'The number, division and author of purchase request % never change',
      OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER purchasing_request_guard
BEFORE UPDATE OR DELETE ON purchasing_purchaserequest
FOR EACH ROW EXECUTE FUNCTION purchasing_request_guard();

CREATE OR REPLACE FUNCTION purchasing_request_line_guard() RETURNS trigger AS $$
DECLARE
  parent_status text;
BEGIN
  SELECT status INTO parent_status FROM purchasing_purchaserequest
    WHERE id = COALESCE(NEW.request_id, OLD.request_id);
  IF parent_status IS DISTINCT FROM 'draft' THEN
    RAISE EXCEPTION 'The lines of a purchase request change only while it is a draft'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER purchasing_request_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON purchasing_purchaserequestline
FOR EACH ROW EXECUTE FUNCTION purchasing_request_line_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS purchasing_request_line_guard ON purchasing_purchaserequestline;
DROP FUNCTION IF EXISTS purchasing_request_line_guard();
DROP TRIGGER IF EXISTS purchasing_request_guard ON purchasing_purchaserequest;
DROP FUNCTION IF EXISTS purchasing_request_guard();
"""

SERIES = ("purchase_request", "Purchase requests", "PR{YY}{MM}{NNNN}", "monthly", "grow")


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
    if director and not ApprovalRule.objects.filter(document_type="purchase_request").exists():
        ApprovalRule.objects.create(document_type="purchase_request", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="purchase_request", defaults={"enabled": True, "after_days": 1}
    )


def fk(to, null=False, related_name="+"):
    return models.ForeignKey(
        blank=null,
        null=null,
        on_delete=django.db.models.deletion.PROTECT,
        related_name=related_name,
        to=to,
    )


def qty():
    return models.DecimalField(decimal_places=3, max_digits=18)


ID = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0006_supplier_statements"),
        ("inventory", "0009_receipt_exchange_rate"),
        ("masters", "0011_limit_no_maximum"),
        ("core", "0025_credit_terms_action"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ReorderLevel",
            fields=[
                ("id", ID.clone()),
                ("level", qty()),
                ("quantity", qty()),
                ("alerted_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("item", fk("inventory.item")),
                ("store", fk("inventory.store")),
                ("usual_supplier", fk("masters.supplier", null=True)),
                ("updated_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["store__code", "item__code"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("item", "store"), name="purchasing_reorder_unique"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(level__gte=0), name="purchasing_reorder_lvl"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(quantity__gt=0), name="purchasing_reorder_qty"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PurchaseRequest",
            fields=[
                ("id", ID.clone()),
                ("number", models.CharField(max_length=30, unique=True)),
                ("needed_by", models.DateField(blank=True, null=True)),
                ("reason", models.TextField(blank=True)),
                ("from_reorder", models.BooleanField(default=False)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("awaiting_approval", "Awaiting approval"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("ordered", "Purchase order made"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("end_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("division", fk("core.division")),
                ("store", fk("inventory.store", null=True)),
                ("supplier", fk("masters.supplier", null=True)),
                (
                    "purchase_order",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="request",
                        to="purchasing.purchaseorder",
                    ),
                ),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=~models.Q(status="ordered")
                        | models.Q(purchase_order__isnull=False),
                        name="purchasing_request_ordered_po",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PurchaseRequestLine",
            fields=[
                ("id", ID.clone()),
                ("line_no", models.PositiveSmallIntegerField()),
                ("quantity", qty()),
                ("notes", models.CharField(blank=True, max_length=300)),
                ("item", fk("inventory.item")),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="purchasing.purchaserequest",
                    ),
                ),
            ],
            options={
                "ordering": ["request", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("request", "line_no"), name="purchasing_req_line_no"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(quantity__gt=0), name="purchasing_req_qty"
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
