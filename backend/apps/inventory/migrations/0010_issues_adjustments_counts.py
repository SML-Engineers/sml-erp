import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Stock issues, returns, adjustments and counts (backlog P2-18).
# - Issues and returns are posted when saved and never change (database guard).
# - An adjustment changes only while it is a draft; posted or rejected, it never changes.
#   Its lines change only while it is a draft. The Director approves ("stock_adjustment").
# - A count sheet's counted quantities change only while it is being counted.
# - Numbers: MI{YY}{MM}{NNNN} issues and returns, SA{YY}{MM}{NNNN} adjustments,
#   SC{YY}{MM}{NNNN} counts.

FORWARD = """
CREATE TRIGGER inventory_issue_insert_only
BEFORE UPDATE OR DELETE ON inventory_stockissue
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();
CREATE TRIGGER inventory_issue_line_insert_only
BEFORE UPDATE OR DELETE ON inventory_stockissueline
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();

CREATE OR REPLACE FUNCTION inventory_adjustment_guard() RETURNS trigger AS $$
BEGIN
  IF OLD.status IN ('posted', 'rejected') THEN
    RAISE EXCEPTION 'Stock adjustment % is % and never changes', OLD.number, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Stock adjustment % has been sent and is not deleted', OLD.number
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER inventory_adjustment_guard
BEFORE UPDATE OR DELETE ON inventory_stockadjustment
FOR EACH ROW EXECUTE FUNCTION inventory_adjustment_guard();

CREATE OR REPLACE FUNCTION inventory_adjustment_line_guard() RETURNS trigger AS $$
DECLARE
  parent record;
BEGIN
  SELECT number, status INTO parent FROM inventory_stockadjustment
    WHERE id = COALESCE(NEW.adjustment_id, OLD.adjustment_id);
  -- Posting writes each line's value once, as the adjustment is approved.
  IF TG_OP = 'UPDATE' AND parent.status = 'awaiting_approval'
     AND NEW.item_id = OLD.item_id AND NEW.lot_no = OLD.lot_no
     AND NEW.quantity = OLD.quantity AND NEW.line_no = OLD.line_no
     AND NEW.unit_cost IS NOT DISTINCT FROM OLD.unit_cost THEN
    RETURN NEW;
  END IF;
  IF parent.status IS NOT NULL AND parent.status <> 'draft' THEN
    RAISE EXCEPTION 'The lines of stock adjustment % change only while it is a draft',
      parent.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER inventory_adjustment_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON inventory_stockadjustmentline
FOR EACH ROW EXECUTE FUNCTION inventory_adjustment_line_guard();

CREATE OR REPLACE FUNCTION inventory_count_line_guard() RETURNS trigger AS $$
DECLARE
  parent record;
BEGIN
  SELECT number, status INTO parent FROM inventory_stockcount
    WHERE id = COALESCE(NEW.count_id, OLD.count_id);
  IF parent.status IS NOT NULL AND parent.status <> 'counting' THEN
    RAISE EXCEPTION 'Count % is closed; its quantities never change', parent.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER inventory_count_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON inventory_stockcountline
FOR EACH ROW EXECUTE FUNCTION inventory_count_line_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS inventory_count_line_guard ON inventory_stockcountline;
DROP FUNCTION IF EXISTS inventory_count_line_guard();
DROP TRIGGER IF EXISTS inventory_adjustment_line_guard ON inventory_stockadjustmentline;
DROP FUNCTION IF EXISTS inventory_adjustment_line_guard();
DROP TRIGGER IF EXISTS inventory_adjustment_guard ON inventory_stockadjustment;
DROP FUNCTION IF EXISTS inventory_adjustment_guard();
DROP TRIGGER IF EXISTS inventory_issue_line_insert_only ON inventory_stockissueline;
DROP TRIGGER IF EXISTS inventory_issue_insert_only ON inventory_stockissue;
"""

SERIES = [
    ("stock_issue", "Stock issues and returns", "MI{YY}{MM}{NNNN}", "monthly", "grow"),
    ("stock_adjustment", "Stock adjustments", "SA{YY}{MM}{NNNN}", "monthly", "grow"),
    ("stock_count", "Stock counts", "SC{YY}{MM}{NNNN}", "monthly", "grow"),
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
    if director and not ApprovalRule.objects.filter(document_type="stock_adjustment").exists():
        ApprovalRule.objects.create(document_type="stock_adjustment", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="stock_adjustment", defaults={"enabled": True, "after_days": 1}
    )


ID = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")


def fk(to, null=False, related_name="+"):
    return models.ForeignKey(
        blank=null,
        null=null,
        on_delete=django.db.models.deletion.PROTECT,
        related_name=related_name,
        to=to,
    )


def qty(null=False):
    if null:
        return models.DecimalField(blank=True, decimal_places=3, max_digits=18, null=True)
    return models.DecimalField(decimal_places=3, max_digits=18)


def money(default=None):
    if default is None:
        return models.DecimalField(decimal_places=2, max_digits=18)
    return models.DecimalField(decimal_places=2, default=default, max_digits=18)


def cost(null=False):
    if null:
        return models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True)
    return models.DecimalField(decimal_places=4, max_digits=18)


def entry(related_name):
    return models.OneToOneField(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.PROTECT,
        related_name=related_name,
        to="accounting.journalentry",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0009_receipt_exchange_rate"),
        ("accounting", "0015_stock_roles"),
        ("masters", "0011_limit_no_maximum"),
        ("core", "0025_credit_terms_action"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StockIssue",
            fields=[
                ("id", ID.clone()),
                ("number", models.CharField(max_length=30, unique=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[("issue", "Issue"), ("return", "Return to stores")],
                        max_length=10,
                    ),
                ),
                ("issue_date", models.DateField()),
                ("purpose", models.CharField(blank=True, max_length=300)),
                ("total_value", money(0)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("store", fk("inventory.store")),
                ("division", fk("core.division")),
                ("section", fk("masters.section", null=True)),
                ("returns", fk("inventory.stockissue", null=True, related_name="returned_by")),
                ("journal_entry", entry("stock_issue")),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-issue_date", "-id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(kind="issue", returns__isnull=True)
                        | models.Q(kind="return", returns__isnull=False),
                        name="inventory_issue_return_of",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="StockIssueLine",
            fields=[
                ("id", ID.clone()),
                ("line_no", models.PositiveIntegerField()),
                ("lot_no", models.CharField(max_length=40)),
                ("quantity", qty()),
                ("unit_cost", cost()),
                ("value", money()),
                ("issue", fk("inventory.stockissue", related_name="lines")),
                ("item", fk("inventory.item")),
                (
                    "returned_from",
                    fk("inventory.stockissueline", null=True, related_name="returns"),
                ),
            ],
            options={
                "ordering": ["issue", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("issue", "line_no"), name="inventory_issue_line_no"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(quantity__gt=0) & models.Q(value__gte=0),
                        name="inventory_issue_line_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="StockCount",
            fields=[
                ("id", ID.clone()),
                ("number", models.CharField(max_length=30, unique=True)),
                ("count_date", models.DateField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("counting", "Being counted"),
                            ("submitted", "Differences sent for approval"),
                            ("agreed", "Counted, no differences"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="counting",
                        max_length=12,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("store", fk("inventory.store")),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-count_date", "-id"]},
        ),
        migrations.CreateModel(
            name="StockCountLine",
            fields=[
                ("id", ID.clone()),
                ("lot_no", models.CharField(max_length=40)),
                ("system_quantity", qty()),
                ("counted_quantity", qty(null=True)),
                (
                    "count",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="inventory.stockcount",
                    ),
                ),
                ("item", fk("inventory.item")),
            ],
            options={
                "ordering": ["count", "item__code", "lot_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("count", "item", "lot_no"), name="inventory_count_line_once"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(counted_quantity__isnull=True)
                        | models.Q(counted_quantity__gte=0),
                        name="inventory_count_not_negative",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="StockAdjustment",
            fields=[
                ("id", ID.clone()),
                ("number", models.CharField(max_length=30, unique=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("adjustment", "Adjustment"),
                            ("write_off", "Write-off"),
                            ("count", "Stock count differences"),
                        ],
                        max_length=12,
                    ),
                ),
                ("adjustment_date", models.DateField()),
                ("reason", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("awaiting_approval", "Waiting for the Director"),
                            ("posted", "Approved and posted"),
                            ("rejected", "Rejected"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("total_value", money(0)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("store", fk("inventory.store")),
                (
                    "count",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="adjustment",
                        to="inventory.stockcount",
                    ),
                ),
                ("journal_entry", entry("stock_adjustment")),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-adjustment_date", "-id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=~models.Q(status="posted") | models.Q(journal_entry__isnull=False),
                        name="inventory_adjustment_posted_entry",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="StockAdjustmentLine",
            fields=[
                ("id", ID.clone()),
                ("line_no", models.PositiveIntegerField()),
                ("lot_no", models.CharField(max_length=40)),
                ("quantity", qty()),
                ("unit_cost", cost(null=True)),
                ("value", money(0)),
                ("notes", models.CharField(blank=True, max_length=300)),
                (
                    "adjustment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="inventory.stockadjustment",
                    ),
                ),
                ("item", fk("inventory.item")),
            ],
            options={
                "ordering": ["adjustment", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("adjustment", "line_no"), name="inventory_adjustment_line_no"
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(quantity=0),
                        name="inventory_adjustment_line_quantity",
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
                    ("price_diff", "Invoice price difference"),
                    ("issued", "Issued from stores"),
                    ("back_in", "Returned to stores"),
                    ("adjusted", "Adjustment or write-off"),
                ],
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="issue_line",
            field=fk("inventory.stockissueline", null=True, related_name="movements"),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="adjustment_line",
            field=fk("inventory.stockadjustmentline", null=True, related_name="movements"),
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
