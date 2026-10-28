import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

# Number series (backlog P0-08). The database guarantees a number is never given twice:
# - every issued number is kept for good (insert-only, reusing core_refuse_change);
# - a running-number counter can only go up, and is never deleted.
FORWARD = """
CREATE TRIGGER core_issuednumber_insert_only
BEFORE UPDATE OR DELETE ON core_issuednumber
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();

CREATE OR REPLACE FUNCTION core_numbercounter_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Running-number counters cannot be deleted'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.last_number < OLD.last_number THEN
    RAISE EXCEPTION 'A running number cannot go back (% to %)', OLD.last_number, NEW.last_number
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER core_numbercounter_guard
BEFORE UPDATE OR DELETE ON core_numbercounter
FOR EACH ROW EXECUTE FUNCTION core_numbercounter_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS core_numbercounter_guard ON core_numbercounter;
DROP FUNCTION IF EXISTS core_numbercounter_guard();
DROP TRIGGER IF EXISTS core_issuednumber_insert_only ON core_issuednumber;
"""

# The series the software starts with. Later phases add theirs in their own migrations.
SERIES_V1 = [
    ("voucher", "Payment vouchers", "{PP}{YY}{MM}{DD}{XXX}", "daily"),
]


def load(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    for document_type, name, number_format, reset in SERIES_V1:
        NumberSeries.objects.get_or_create(
            document_type=document_type,
            defaults={"name": name, "format": number_format, "reset_period": reset},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_company_division_lock"),
    ]

    operations = [
        migrations.CreateModel(
            name="NumberSeries",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("document_type", models.SlugField(unique=True)),
                ("name", models.CharField(max_length=100)),
                ("format", models.CharField(max_length=60)),
                (
                    "reset_period",
                    models.CharField(
                        choices=[
                            ("daily", "Every day"),
                            ("monthly", "Every month"),
                            ("yearly", "Every year"),
                            ("never", "Never"),
                        ],
                        max_length=10,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name_plural": "number series",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="NumberCounter",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("period", models.CharField(max_length=10)),
                ("last_number", models.PositiveIntegerField(default=0)),
                (
                    "division",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="number_counters",
                        to="core.division",
                    ),
                ),
                (
                    "series",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="counters",
                        to="core.numberseries",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("series", "division", "period"),
                        name="core_numbercounter_unique",
                        nulls_distinct=False,
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="IssuedNumber",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("number", models.CharField(max_length=60)),
                ("issued_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "division",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="issued_numbers",
                        to="core.division",
                    ),
                ),
                (
                    "series",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="issued",
                        to="core.numberseries",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("series", "number"), name="core_issuednumber_unique"
                    )
                ],
            },
        ),
        migrations.RunPython(load, migrations.RunPython.noop),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
