import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Opening stock (backlog P16-15; owner's decision of 2 Nov 2026: count the stores and load
# the balances at go-live).
# - Numbered OS{YY}{MM}{DD}{XX}; approved by the Director ("opening_stock", level 2), which
#   puts the stock in and posts Dr Inventory, Cr Opening balance equity.
# - Once sent for approval an opening stock and its lines never change; posted and rejected
#   ones stay that way for good; only a draft is deleted.

SERIES = ("opening_stock", "Opening stock", "OS{YY}{MM}{DD}{XX}", "daily", "grow")


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
    if director and not ApprovalRule.objects.filter(document_type="opening_stock").exists():
        ApprovalRule.objects.create(document_type="opening_stock", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="opening_stock", defaults={"enabled": True, "after_days": 1}
    )


FORWARD = """
CREATE OR REPLACE FUNCTION inventory_os_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Opening stock % cannot be deleted', OLD.number
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status IN ('posted', 'rejected') THEN
    RAISE EXCEPTION 'Opening stock % is % for good', OLD.number, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.number IS DISTINCT FROM OLD.number OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
  THEN
    RAISE EXCEPTION 'The number and author of opening stock % never change', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'draft' AND (
       NEW.count_date IS DISTINCT FROM OLD.count_date OR NEW.notes IS DISTINCT FROM OLD.notes
  ) THEN
    RAISE EXCEPTION 'Opening stock % has been sent for approval: it cannot be changed',
      OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status = 'posted' AND NEW.journal_entry_id IS NULL THEN
    RAISE EXCEPTION 'Opening stock % is posted only with its journal entry', OLD.number
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER inventory_os_guard
BEFORE UPDATE OR DELETE ON inventory_openingstock
FOR EACH ROW EXECUTE FUNCTION inventory_os_guard();

CREATE OR REPLACE FUNCTION inventory_os_line_guard() RETURNS trigger AS $$
DECLARE
  parent_id bigint;
  parent_status text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    parent_id := OLD.opening_id;
  ELSE
    parent_id := NEW.opening_id;
  END IF;
  SELECT status INTO parent_status FROM inventory_openingstock WHERE id = parent_id;
  IF parent_status IS NOT NULL AND parent_status <> 'draft' THEN
    RAISE EXCEPTION 'Opening stock % has been sent for approval: it cannot be changed',
      parent_id USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER inventory_os_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON inventory_openingstockline
FOR EACH ROW EXECUTE FUNCTION inventory_os_line_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS inventory_os_line_guard ON inventory_openingstockline;
DROP FUNCTION IF EXISTS inventory_os_line_guard();
DROP TRIGGER IF EXISTS inventory_os_guard ON inventory_openingstock;
DROP FUNCTION IF EXISTS inventory_os_guard();
"""


def id_field():
    return (
        "id",
        models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
    )


def fk(to, related_name="+", null=False):
    extra = {"blank": True, "null": True} if null else {}
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name=related_name, to=to, **extra
    )


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0006_returned_movements"),
        ("accounting", "0008_manual_journals"),
        ("core", "0019_purchasing_roles"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OpeningStock",
            fields=[
                id_field(),
                ("number", models.CharField(max_length=30, unique=True)),
                ("count_date", models.DateField()),
                ("notes", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("awaiting_approval", "Waiting for the Director"),
                            ("posted", "Approved and in stock"),
                            ("rejected", "Rejected"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "journal_entry",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="opening_stock",
                        to="accounting.journalentry",
                    ),
                ),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-count_date", "-number"]},
        ),
        migrations.CreateModel(
            name="OpeningStockLine",
            fields=[
                id_field(),
                ("line_no", models.PositiveIntegerField()),
                ("lot_no", models.CharField(max_length=40)),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=18)),
                ("unit_cost", models.DecimalField(decimal_places=4, max_digits=18)),
                ("value", models.DecimalField(decimal_places=2, max_digits=18)),
                ("item", fk("inventory.item")),
                ("store", fk("inventory.store")),
                (
                    "opening",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="inventory.openingstock",
                    ),
                ),
            ],
            options={
                "ordering": ["opening", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("opening", "line_no"), name="inventory_os_line_no"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("quantity__gt", 0), ("unit_cost__gt", 0)),
                        name="inventory_os_line_positive",
                    ),
                ],
            },
        ),
        migrations.AlterField(
            model_name="stockmovement",
            name="kind",
            field=models.CharField(
                choices=[
                    ("received", "Received into quarantine"),
                    ("damaged", "Received damaged"),
                    ("accepted", "Accepted by QC"),
                    ("rejected", "Rejected by QC"),
                    ("reversed", "GRN reversed"),
                    ("returned", "Returned to the supplier"),
                    ("opening", "Opening stock"),
                ],
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="opening_line",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="movements",
                to="inventory.openingstockline",
            ),
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
