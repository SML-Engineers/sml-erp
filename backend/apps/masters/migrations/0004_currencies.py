import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Currencies and exchange rates (backlog P0-11, spec 3A.4).
#
# The database refuses, whatever the application does:
# - changing, deactivating or deleting the base currency (LKR);
# - changing or deleting an exchange rate once a document has used it (rule 11).

CURRENCIES_V1 = [
    # code, name, symbol, decimal places, base
    ("LKR", "Sri Lankan rupee", "Rs", 2, True),
    ("USD", "US dollar", "$", 2, False),
    ("EUR", "Euro", "€", 2, False),
    ("GBP", "Pound sterling", "£", 2, False),
    ("AUD", "Australian dollar", "A$", 2, False),
    ("JPY", "Japanese yen", "¥", 0, False),
    ("CNY", "Chinese yuan", "CN¥", 2, False),
    ("INR", "Indian rupee", "₹", 2, False),
    ("SGD", "Singapore dollar", "S$", 2, False),
    ("AED", "UAE dirham", "AED", 2, False),
]


def load(apps, schema_editor):
    Currency = apps.get_model("masters", "Currency")
    for code, name, symbol, places, base in CURRENCIES_V1:
        Currency.objects.get_or_create(
            code=code,
            defaults={"name": name, "symbol": symbol, "decimal_places": places, "is_base": base},
        )


FORWARD = """
CREATE OR REPLACE FUNCTION masters_currency_guard() RETURNS trigger AS $$
BEGIN
  IF NOT OLD.is_base THEN
    IF TG_OP = 'UPDATE' AND NEW.is_base THEN
      RAISE EXCEPTION 'Only LKR is the base currency' USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' OR NEW.code IS DISTINCT FROM OLD.code OR NOT NEW.is_base
     OR NOT NEW.is_active THEN
    RAISE EXCEPTION 'The base currency % cannot be changed, deactivated or deleted', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER masters_currency_guard
BEFORE UPDATE OR DELETE ON masters_currency
FOR EACH ROW EXECUTE FUNCTION masters_currency_guard();

CREATE OR REPLACE FUNCTION masters_exchangerate_guard() RETURNS trigger AS $$
BEGIN
  IF OLD.first_used_at IS NULL THEN
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE'
     OR NEW.rate IS DISTINCT FROM OLD.rate
     OR NEW.buying IS DISTINCT FROM OLD.buying
     OR NEW.selling IS DISTINCT FROM OLD.selling
     OR NEW.date IS DISTINCT FROM OLD.date
     OR NEW.currency_id IS DISTINCT FROM OLD.currency_id
     OR NEW.first_used_at IS DISTINCT FROM OLD.first_used_at THEN
    RAISE EXCEPTION 'The exchange rate of % has been used on documents and cannot change', OLD.date
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER masters_exchangerate_guard
BEFORE UPDATE OR DELETE ON masters_exchangerate
FOR EACH ROW EXECUTE FUNCTION masters_exchangerate_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS masters_exchangerate_guard ON masters_exchangerate;
DROP FUNCTION IF EXISTS masters_exchangerate_guard();
DROP TRIGGER IF EXISTS masters_currency_guard ON masters_currency;
DROP FUNCTION IF EXISTS masters_currency_guard();
"""


def big_id():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0003_shifts_rosters"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Currency",
            fields=[
                ("id", big_id()),
                ("code", models.CharField(max_length=3, unique=True)),
                ("name", models.CharField(max_length=60)),
                ("symbol", models.CharField(blank=True, max_length=8)),
                ("decimal_places", models.PositiveSmallIntegerField(default=2)),
                ("is_base", models.BooleanField(default=False, editable=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "verbose_name_plural": "currencies",
                "ordering": ["-is_base", "code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("code__regex", "^[A-Z]{3}$")),
                        name="masters_currency_code_format",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("decimal_places__lte", 4)),
                        name="masters_currency_decimals",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("is_base", True)),
                        fields=("is_base",),
                        name="masters_currency_one_base",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ExchangeRate",
            fields=[
                ("id", big_id()),
                ("date", models.DateField()),
                (
                    "rate",
                    models.DecimalField(decimal_places=6, max_digits=18, verbose_name="Rate (LKR)"),
                ),
                (
                    "buying",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=18, null=True),
                ),
                (
                    "selling",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=18, null=True),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[("manual", "Entered"), ("import", "Imported")],
                        default="manual",
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("first_used_at", models.DateTimeField(blank=True, editable=False, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "currency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rates",
                        to="masters.currency",
                    ),
                ),
            ],
            options={
                "ordering": ["-date", "currency__code"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("currency", "date"), name="masters_rate_one_per_day"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("rate__gt", 0)), name="masters_rate_positive"
                    ),
                ],
            },
        ),
        migrations.RunPython(load, migrations.RunPython.noop),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
