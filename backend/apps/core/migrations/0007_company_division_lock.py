from django.db import migrations, models

# Company profile and the division code lock (backlog P0-07).
#
# The database itself refuses, whatever the application does:
# - changing the code of a division that has been used on a document, deleting it, or
#   clearing its "first used" date (rule 9: codes used on transactions are immutable);
# - deleting the company row, or changing the base currency (every amount in the books is
#   in it).
FORWARD = """
CREATE OR REPLACE FUNCTION core_division_guard() RETURNS trigger AS $$
BEGIN
  IF OLD.first_used_at IS NULL THEN
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Division % has been used on documents: it cannot be deleted, only deactivated', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.code IS DISTINCT FROM OLD.code THEN
    RAISE EXCEPTION 'Division % has been used on documents: its code cannot change', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.first_used_at IS DISTINCT FROM OLD.first_used_at THEN
    RAISE EXCEPTION 'Division %: the date it was first used cannot change', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER core_division_guard
BEFORE UPDATE OR DELETE ON core_division
FOR EACH ROW EXECUTE FUNCTION core_division_guard();

CREATE OR REPLACE FUNCTION core_company_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'The company profile cannot be deleted'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.base_currency IS DISTINCT FROM OLD.base_currency THEN
    RAISE EXCEPTION 'The base currency cannot change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER core_company_guard
BEFORE UPDATE OR DELETE ON core_company
FOR EACH ROW EXECUTE FUNCTION core_company_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS core_company_guard ON core_company;
DROP FUNCTION IF EXISTS core_company_guard();
DROP TRIGGER IF EXISTS core_division_guard ON core_division;
DROP FUNCTION IF EXISTS core_division_guard();
"""


def create_company(apps, schema_editor):
    Company = apps.get_model("core", "Company")
    Company.objects.get_or_create(pk=1, defaults={"name": "SML Engineers"})


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_audit_log"),
    ]

    operations = [
        migrations.CreateModel(
            name="Company",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(max_length=200)),
                (
                    "registration_no",
                    models.CharField(
                        blank=True, max_length=50, verbose_name="Business registration no."
                    ),
                ),
                (
                    "tin",
                    models.CharField(
                        blank=True,
                        max_length=50,
                        verbose_name="Taxpayer identification no. (TIN)",
                    ),
                ),
                (
                    "vat_no",
                    models.CharField(
                        blank=True, max_length=50, verbose_name="VAT registration no."
                    ),
                ),
                ("address", models.TextField(blank=True)),
                ("phone", models.CharField(blank=True, max_length=50)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("website", models.CharField(blank=True, max_length=200)),
                ("base_currency", models.CharField(default="LKR", max_length=3)),
                (
                    "financial_year_start_month",
                    models.PositiveSmallIntegerField(
                        choices=[
                            (1, "January"),
                            (2, "February"),
                            (3, "March"),
                            (4, "April"),
                            (5, "May"),
                            (6, "June"),
                            (7, "July"),
                            (8, "August"),
                            (9, "September"),
                            (10, "October"),
                            (11, "November"),
                            (12, "December"),
                        ],
                        default=4,
                    ),
                ),
                ("logo", models.FileField(blank=True, upload_to="company/")),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name_plural": "company",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("id", 1)), name="core_company_single_row"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("financial_year_start_month__gte", 1),
                            ("financial_year_start_month__lte", 12),
                        ),
                        name="core_company_fy_month_valid",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="division",
            name="first_used_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddConstraint(
            model_name="division",
            constraint=models.CheckConstraint(
                condition=models.Q(("code__regex", "^[A-Z0-9]{2}$")),
                name="core_division_code_format",
            ),
        ),
        migrations.RunPython(create_company, migrations.RunPython.noop),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
