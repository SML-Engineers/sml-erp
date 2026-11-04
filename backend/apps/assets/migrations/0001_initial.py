import datetime

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Fixed asset register and depreciation (backlog P2-19).
# - Classes loaded from the list proposed to the owner (3 Nov 2026), with their accounts from
#   the starter chart. Their depreciation methods and rates are agreed with the auditors and
#   entered by the Accountant; until then nothing is depreciated (land never is).
# - A posted depreciation month and its lines never change; a rate is fixed once a posted
#   month used it; an asset's cost and dates are fixed once it
#   has posted depreciation, and a disposed asset never changes (shot count apart).
# - Asset codes FA{NNNN}.

FORWARD = """
CREATE OR REPLACE FUNCTION assets_run_guard() RETURNS trigger AS $$
BEGIN
  IF OLD.status = 'posted' THEN
    RAISE EXCEPTION 'Depreciation for % is posted and never changes', OLD.month_end
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER assets_run_guard
BEFORE UPDATE OR DELETE ON assets_depreciationrun
FOR EACH ROW EXECUTE FUNCTION assets_run_guard();

CREATE OR REPLACE FUNCTION assets_line_guard() RETURNS trigger AS $$
DECLARE
  run_status text;
BEGIN
  SELECT status INTO run_status FROM assets_depreciationrun
    WHERE id = COALESCE(NEW.run_id, OLD.run_id);
  IF run_status = 'posted' THEN
    RAISE EXCEPTION 'The lines of a posted depreciation month never change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER assets_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON assets_depreciationline
FOR EACH ROW EXECUTE FUNCTION assets_line_guard();

CREATE OR REPLACE FUNCTION assets_rate_guard() RETURNS trigger AS $$
BEGIN
  -- A rate is fixed once a posted month has used it; before that it may still be corrected.
  IF EXISTS (
    SELECT 1 FROM assets_depreciationrun r
    WHERE r.status = 'posted' AND r.month_end >= OLD.effective_from
  ) THEN
    RAISE EXCEPTION 'The rate from % has been used for posted depreciation and never changes',
      OLD.effective_from USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER assets_rate_guard
BEFORE UPDATE OR DELETE ON assets_assetclassrate
FOR EACH ROW EXECUTE FUNCTION assets_rate_guard();

CREATE OR REPLACE FUNCTION assets_asset_guard() RETURNS trigger AS $$
DECLARE
  depreciated boolean;
BEGIN
  SELECT EXISTS (
    SELECT 1 FROM assets_depreciationline l JOIN assets_depreciationrun r ON r.id = l.run_id
    WHERE l.asset_id = OLD.id AND r.status = 'posted'
  ) INTO depreciated;
  IF TG_OP = 'DELETE' THEN
    IF depreciated OR OLD.status = 'disposed' THEN
      RAISE EXCEPTION 'Fixed asset % has history and is never deleted', OLD.code
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW.code IS DISTINCT FROM OLD.code THEN
    RAISE EXCEPTION 'Asset codes never change (%)', OLD.code USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status = 'disposed' AND (
       NEW.status IS DISTINCT FROM OLD.status
    OR NEW.name IS DISTINCT FROM OLD.name
    OR NEW.cost IS DISTINCT FROM OLD.cost
    OR NEW.disposed_on IS DISTINCT FROM OLD.disposed_on
    OR NEW.proceeds IS DISTINCT FROM OLD.proceeds
    OR NEW.disposal_entry_id IS DISTINCT FROM OLD.disposal_entry_id
    OR NEW.asset_class_id IS DISTINCT FROM OLD.asset_class_id
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
  ) THEN
    RAISE EXCEPTION 'Fixed asset % is disposed and never changes', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF depreciated AND (
       NEW.cost IS DISTINCT FROM OLD.cost
    OR NEW.residual_value IS DISTINCT FROM OLD.residual_value
    OR NEW.opening_accumulated IS DISTINCT FROM OLD.opening_accumulated
    OR NEW.depreciation_from IS DISTINCT FROM OLD.depreciation_from
    OR NEW.acquisition_date IS DISTINCT FROM OLD.acquisition_date
    OR NEW.asset_class_id IS DISTINCT FROM OLD.asset_class_id
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
  ) THEN
    RAISE EXCEPTION 'Fixed asset % has posted depreciation; its cost, class and dates are fixed',
      OLD.code USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER assets_asset_guard
BEFORE UPDATE OR DELETE ON assets_fixedasset
FOR EACH ROW EXECUTE FUNCTION assets_asset_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS assets_asset_guard ON assets_fixedasset;
DROP FUNCTION IF EXISTS assets_asset_guard();
DROP TRIGGER IF EXISTS assets_rate_guard ON assets_assetclassrate;
DROP FUNCTION IF EXISTS assets_rate_guard();
DROP TRIGGER IF EXISTS assets_line_guard ON assets_depreciationline;
DROP FUNCTION IF EXISTS assets_line_guard();
DROP TRIGGER IF EXISTS assets_run_guard ON assets_depreciationrun;
DROP FUNCTION IF EXISTS assets_run_guard();
"""

# (code, name, cost account number, order)
CLASSES = [
    ("LAND", "Land", "1500", 10),
    ("BUILDINGS", "Buildings", "1510", 20),
    ("PLANT", "Plant and machinery", "1520", 30),
    ("MOULDS", "Moulds and tooling", "1530", 40),
    ("VEHICLES", "Motor vehicles", "1540", 50),
    ("FURNITURE", "Furniture and fittings", "1550", 60),
    ("COMPUTERS", "Office and computer equipment", "1560", 70),
]


def seed(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    NumberSeries.objects.get_or_create(
        document_type="fixed_asset",
        defaults={
            "name": "Fixed assets",
            "format": "FA{NNNN}",
            "reset_period": "never",
            "when_full": "grow",
        },
    )
    Account = apps.get_model("accounting", "Account")

    def number(n):
        return Account.objects.filter(number=n, is_active=True).first()

    shared = {
        "accumulated_account": number("1590"),
        "expense_account": number("6800"),
        "gain_account": number("7030"),
        "loss_account": number("8020"),
    }
    if any(v is None for v in shared.values()):
        return  # no starter chart: the Accountant sets the classes up
    AssetClass = apps.get_model("assets", "AssetClass")
    Rate = apps.get_model("assets", "AssetClassRate")
    for code, name, cost, order in CLASSES:
        account = number(cost)
        if account is None:
            continue
        made, _ = AssetClass.objects.get_or_create(
            code=code,
            defaults={"name": name, "cost_account": account, "sort_order": order, **shared},
        )
        if code == "LAND" and not made.rates.exists():
            Rate.objects.create(
                asset_class=made,
                effective_from=datetime.date(2000, 1, 1),
                method="none",
                rate=0,
                reason="Land is not depreciated.",
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


def money(default=None):
    if default is None:
        return models.DecimalField(decimal_places=2, max_digits=18)
    return models.DecimalField(decimal_places=2, default=default, max_digits=18)


METHODS = [
    ("straight_line", "Straight line (on cost)"),
    ("reducing_balance", "Reducing balance (on book value)"),
    ("none", "Not depreciated (land)"),
]


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounting", "0015_stock_roles"),
        ("core", "0025_credit_terms_action"),
        ("masters", "0011_limit_no_maximum"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AssetClass",
            fields=[
                ("id", ID.clone()),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("cost_account", fk("accounting.account")),
                ("accumulated_account", fk("accounting.account")),
                ("expense_account", fk("accounting.account")),
                ("gain_account", fk("accounting.account")),
                ("loss_account", fk("accounting.account")),
            ],
            options={"ordering": ["sort_order", "code"]},
        ),
        migrations.CreateModel(
            name="AssetClassRate",
            fields=[
                ("id", ID.clone()),
                ("effective_from", models.DateField()),
                ("method", models.CharField(choices=METHODS, max_length=20)),
                ("rate", models.DecimalField(decimal_places=4, max_digits=7)),
                ("reason", models.TextField(blank=True)),
                ("set_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("asset_class", fk("assets.assetclass", related_name="rates")),
                ("set_by", fk(settings.AUTH_USER_MODEL, null=True)),
            ],
            options={
                "ordering": ["asset_class", "-effective_from"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("asset_class", "effective_from"), name="assets_rate_once_per_day"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(rate__gte=0) & models.Q(rate__lte=100),
                        name="assets_rate_percent",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="FixedAsset",
            fields=[
                ("id", ID.clone()),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("serial_no", models.CharField(blank=True, max_length=100)),
                ("supplier", models.CharField(blank=True, max_length=200)),
                ("acquisition_date", models.DateField()),
                ("depreciation_from", models.DateField()),
                ("cost", money()),
                ("residual_value", money(0)),
                ("opening_accumulated", money(0)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "In use"), ("disposed", "Disposed")],
                        default="active",
                        max_length=10,
                    ),
                ),
                ("disposed_on", models.DateField(blank=True, null=True)),
                ("proceeds", money(0)),
                ("disposal_reason", models.TextField(blank=True)),
                ("shot_count", models.PositiveBigIntegerField(default=0)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("asset_class", fk("assets.assetclass", related_name="assets")),
                ("division", fk("core.division")),
                ("machine", fk("masters.machine", null=True)),
                (
                    "disposal_entry",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="asset_disposal",
                        to="accounting.journalentry",
                    ),
                ),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(cost__gt=0)
                        & models.Q(residual_value__gte=0)
                        & models.Q(opening_accumulated__gte=0)
                        & models.Q(proceeds__gte=0),
                        name="assets_amounts",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            residual_value__lte=models.F("cost") - models.F("opening_accumulated")
                        ),
                        name="assets_residual_within_cost",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(status="active")
                        | models.Q(disposed_on__isnull=False, disposal_entry__isnull=False),
                        name="assets_disposed_posted",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DepreciationRun",
            fields=[
                ("id", ID.clone()),
                ("month_end", models.DateField(unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("draft", "Worked out, to check"), ("posted", "Posted")],
                        default="draft",
                        max_length=10,
                    ),
                ),
                ("total", money(0)),
                ("prepared_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "journal_entry",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="depreciation_run",
                        to="accounting.journalentry",
                    ),
                ),
                ("prepared_by", fk(settings.AUTH_USER_MODEL)),
                ("posted_by", fk(settings.AUTH_USER_MODEL, null=True)),
            ],
            options={
                "ordering": ["-month_end"],
                "constraints": [
                    models.CheckConstraint(
                        condition=~models.Q(status="posted") | models.Q(journal_entry__isnull=False),
                        name="assets_run_posted_entry",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DepreciationLine",
            fields=[
                ("id", ID.clone()),
                ("method", models.CharField(choices=METHODS, max_length=20)),
                ("rate", models.DecimalField(decimal_places=4, max_digits=7)),
                ("book_value_before", money()),
                ("amount", money()),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="assets.depreciationrun",
                    ),
                ),
                ("asset", fk("assets.fixedasset", related_name="depreciation")),
            ],
            options={
                "ordering": ["run", "asset__code"],
                "constraints": [
                    models.UniqueConstraint(fields=("run", "asset"), name="assets_line_once"),
                    models.CheckConstraint(
                        condition=models.Q(amount__gt=0), name="assets_line_amount"
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
