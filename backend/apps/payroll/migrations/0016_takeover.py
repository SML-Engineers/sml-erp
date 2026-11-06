import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# P2B-14: taking over from the old payroll: the year's opening figures (the Director approves)
# and the parallel run's comparison and sign-off.
SQL = """
CREATE TRIGGER payroll_openingfigures_insert_only
BEFORE UPDATE OR DELETE ON payroll_openingfigures
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();

CREATE OR REPLACE FUNCTION payroll_openingbatch_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Opening figures are never deleted' USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status <> 'awaiting' OR NEW.file_name <> OLD.file_name
     OR NEW.tax_year <> OLD.tax_year OR NEW.created_by_id <> OLD.created_by_id THEN
    RAISE EXCEPTION 'Opening figures once decided never change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_openingbatch_guard
BEFORE UPDATE OR DELETE ON payroll_openingbatch
FOR EACH ROW EXECUTE FUNCTION payroll_openingbatch_guard();

CREATE OR REPLACE FUNCTION payroll_parallelcheck_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A parallel check is never deleted' USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.signed_off_at IS NOT NULL OR NEW.run_id <> OLD.run_id
     OR NEW.result IS DISTINCT FROM OLD.result OR NEW.differences <> OLD.differences
     OR NEW.created_by_id <> OLD.created_by_id OR NEW.file_name <> OLD.file_name THEN
    RAISE EXCEPTION 'A parallel check is kept as compared; it is only signed off'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_parallelcheck_guard
BEFORE UPDATE OR DELETE ON payroll_parallelcheck
FOR EACH ROW EXECUTE FUNCTION payroll_parallelcheck_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS payroll_parallelcheck_guard ON payroll_parallelcheck;
DROP FUNCTION IF EXISTS payroll_parallelcheck_guard();
DROP TRIGGER IF EXISTS payroll_openingbatch_guard ON payroll_openingbatch;
DROP FUNCTION IF EXISTS payroll_openingbatch_guard();
DROP TRIGGER IF EXISTS payroll_openingfigures_insert_only ON payroll_openingfigures;
"""


def seed(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    director = Role.objects.filter(code="director").first()
    if director and not ApprovalRule.objects.filter(document_type="payroll_opening").exists():
        ApprovalRule.objects.create(document_type="payroll_opening", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="payroll_opening", defaults={"enabled": True, "after_days": 1}
    )


def money():
    return models.DecimalField(decimal_places=2, max_digits=18)


def user(related="+", null=False):
    return models.ForeignKey(
        blank=null,
        null=null,
        on_delete=django.db.models.deletion.PROTECT,
        related_name=related,
        to=settings.AUTH_USER_MODEL,
    )


def key():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0015_gratuity"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OpeningBatch",
            fields=[
                ("id", key()),
                ("file_name", models.CharField(max_length=200)),
                ("tax_year", models.DateField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("awaiting", "Waiting for the Director"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        default="awaiting",
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", user()),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="OpeningFigures",
            fields=[
                ("id", key()),
                ("last_month", models.DateField()),
                ("months", models.PositiveSmallIntegerField()),
                ("gross", money()),
                ("apit_earnings", money()),
                ("apit", money()),
                ("epf_employee", money()),
                ("epf_employer", money()),
                ("etf", money()),
                ("net", money()),
                ("gratuity_provision", money()),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="figures",
                        to="payroll.openingbatch",
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="openings",
                        to="payroll.employee",
                    ),
                ),
            ],
            options={
                "ordering": ["batch", "employee__number"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=["batch", "employee"], name="payroll_opening_once"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ParallelCheck",
            fields=[
                ("id", key()),
                ("file_name", models.CharField(max_length=200)),
                ("result", models.JSONField()),
                ("differences", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("signed_off_at", models.DateTimeField(blank=True, null=True)),
                ("note", models.CharField(blank=True, max_length=300)),
                ("created_by", user()),
                ("signed_off_by", user(null=True)),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="parallel_checks",
                        to="payroll.payrollrun",
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.RunSQL(SQL, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
