import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Delivery notes (backlog P2-04, spec 5.3 and 6).
# - Numbered DN{YY}{MM}{DD}{XX}, in the saving transaction.
# - A sales order gains the status Delivered (everything delivered, not yet invoiced).
# - The database refuses:
#   - delivering more of an order line than was ordered (checked when a note is issued);
#   - changing a delivery note, or its lines, once it has left draft: only its status moves
#     on (issued -> signed by the customer, or cancelled with a reason), and the signed copy
#     and who received it are written once;
#   - deleting a note that is not a draft. A cancelled note stays cancelled.

SERIES = ("delivery_note", "Delivery notes", "DN{YY}{MM}{DD}{XX}", "daily", "grow")

FORWARD = """
CREATE OR REPLACE FUNCTION sales_dn_guard() RETURNS trigger AS $$
DECLARE
  over text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Delivery note % cannot be deleted', OLD.number
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW.number IS DISTINCT FROM OLD.number OR NEW.order_id IS DISTINCT FROM OLD.order_id
     OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id THEN
    RAISE EXCEPTION 'The number, order and author of delivery note % never change', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status = 'cancelled' THEN
    RAISE EXCEPTION 'Delivery note % is cancelled for good', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'draft' AND (
       NEW.delivery_date IS DISTINCT FROM OLD.delivery_date
       OR NEW.vehicle_no IS DISTINCT FROM OLD.vehicle_no
       OR NEW.driver IS DISTINCT FROM OLD.driver
       OR NEW.delivery_address IS DISTINCT FROM OLD.delivery_address
       OR NEW.notes IS DISTINCT FROM OLD.notes
       OR NEW.issued_by_id IS DISTINCT FROM OLD.issued_by_id
       OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
  ) THEN
    RAISE EXCEPTION 'Delivery note % has been issued: it cannot be changed', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status = 'received' AND (
       NEW.received_by IS DISTINCT FROM OLD.received_by
       OR NEW.received_on IS DISTINCT FROM OLD.received_on
       OR NEW.signed_copy IS DISTINCT FROM OLD.signed_copy
  ) THEN
    RAISE EXCEPTION 'The signed copy of delivery note % is kept as it is', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
       (OLD.status = 'draft' AND NEW.status = 'issued')
       OR (OLD.status = 'issued' AND NEW.status IN ('received', 'cancelled'))
       OR (OLD.status = 'received' AND NEW.status = 'cancelled')
  ) THEN
    RAISE EXCEPTION 'Delivery note % cannot go from % to %', OLD.number, OLD.status, NEW.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status = 'cancelled' AND btrim(NEW.cancel_reason) = '' THEN
    RAISE EXCEPTION 'Delivery note % is cancelled only with a reason', OLD.number
      USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status = 'draft' AND NEW.status = 'issued' THEN
    SELECT string_agg(ol.line_no::text, ', ') INTO over
    FROM sales_salesorderline ol
    WHERE ol.id IN (SELECT order_line_id FROM sales_deliverynoteline WHERE note_id = NEW.id)
      AND ol.quantity < (
        SELECT COALESCE(SUM(l.quantity), 0)
        FROM sales_deliverynoteline l
        JOIN sales_deliverynote n ON n.id = l.note_id
        WHERE l.order_line_id = ol.id
          AND (n.id = NEW.id OR n.status IN ('issued', 'received'))
      );
    IF over IS NOT NULL THEN
      RAISE EXCEPTION 'Delivery note % delivers more than ordered on line %', OLD.number, over
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_dn_guard
BEFORE UPDATE OR DELETE ON sales_deliverynote
FOR EACH ROW EXECUTE FUNCTION sales_dn_guard();

CREATE OR REPLACE FUNCTION sales_dn_line_guard() RETURNS trigger AS $$
DECLARE
  parent_id bigint;
  parent_status text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    parent_id := OLD.note_id;
  ELSE
    parent_id := NEW.note_id;
  END IF;
  SELECT status INTO parent_status FROM sales_deliverynote WHERE id = parent_id;
  IF parent_status IS NOT NULL AND parent_status <> 'draft' THEN
    RAISE EXCEPTION 'Delivery note % has been issued: its lines cannot be changed', parent_id
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_dn_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_deliverynoteline
FOR EACH ROW EXECUTE FUNCTION sales_dn_line_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS sales_dn_line_guard ON sales_deliverynoteline;
DROP FUNCTION IF EXISTS sales_dn_line_guard();
DROP TRIGGER IF EXISTS sales_dn_guard ON sales_deliverynote;
DROP FUNCTION IF EXISTS sales_dn_guard();
"""


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


def id_field():
    return (
        "id",
        models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0008_sales_orders"),
        ("core", "0020_tax_rate_action"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="salesorder",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("awaiting_approval", "Awaiting approval"),
                    ("open", "Open"),
                    ("partly_delivered", "Partly delivered"),
                    ("delivered", "Delivered"),
                    ("completed", "Completed"),
                    ("cancelled", "Cancelled"),
                ],
                default="draft",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="DeliveryNote",
            fields=[
                id_field(),
                ("number", models.CharField(max_length=30, unique=True)),
                ("delivery_date", models.DateField()),
                ("vehicle_no", models.CharField(blank=True, max_length=30, verbose_name="Vehicle no.")),
                ("driver", models.CharField(blank=True, max_length=100)),
                ("delivery_address", models.TextField(blank=True)),
                ("notes", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("issued", "Issued"),
                            ("received", "Signed by the customer"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="draft",
                        max_length=10,
                    ),
                ),
                ("issued_at", models.DateTimeField(blank=True, null=True)),
                (
                    "received_by",
                    models.CharField(blank=True, max_length=100, verbose_name="Received by (name)"),
                ),
                ("received_on", models.DateField(blank=True, null=True)),
                ("signed_copy", models.FileField(blank=True, upload_to="delivery-notes/%Y/%m/")),
                ("signed_copy_name", models.CharField(blank=True, max_length=200)),
                ("signed_copy_type", models.CharField(blank=True, max_length=100)),
                ("signed_copy_sha256", models.CharField(blank=True, max_length=64)),
                ("cancel_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "issued_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="deliveries",
                        to="sales.salesorder",
                    ),
                ),
            ],
            options={"ordering": ["-delivery_date", "-number"]},
        ),
        migrations.CreateModel(
            name="DeliveryNoteLine",
            fields=[
                id_field(),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=18)),
                (
                    "note",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="sales.deliverynote",
                    ),
                ),
                (
                    "order_line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="delivered",
                        to="sales.salesorderline",
                    ),
                ),
            ],
            options={
                "ordering": ["note", "order_line__line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("note", "order_line"), name="sales_dn_line_once"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("quantity__gt", 0)), name="sales_dn_line_qty"
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
