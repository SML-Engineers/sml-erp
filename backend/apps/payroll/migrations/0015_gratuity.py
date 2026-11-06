from decimal import Decimal

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# P2B-19: gratuity settings (the Accountant enters, the Director approves) and each payroll
# line's gratuity liability and monthly provision.
SQL = """
CREATE OR REPLACE FUNCTION payroll_gratuitysetting_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Gratuity settings are never deleted'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status <> 'awaiting' THEN
    RAISE EXCEPTION 'Gratuity settings that are % never change', OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.employee_id <> OLD.employee_id OR NEW.effective_from <> OLD.effective_from
     OR NEW.service_from <> OLD.service_from OR NEW.months_per_year <> OLD.months_per_year
     OR NEW.after_years <> OLD.after_years THEN
    RAISE EXCEPTION 'Gratuity settings are decided, never edited'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_gratuitysetting_guard
BEFORE UPDATE OR DELETE ON payroll_gratuitysetting
FOR EACH ROW EXECUTE FUNCTION payroll_gratuitysetting_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS payroll_gratuitysetting_guard ON payroll_gratuitysetting;
DROP FUNCTION IF EXISTS payroll_gratuitysetting_guard();
"""


def seed(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    director = Role.objects.filter(code="director").first()
    if director and not ApprovalRule.objects.filter(document_type="gratuity_setting").exists():
        ApprovalRule.objects.create(document_type="gratuity_setting", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="gratuity_setting", defaults={"enabled": True, "after_days": 1}
    )


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0014_detail_changes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollline",
            name="gratuity_years",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="payrollline",
            name="gratuity_liability",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AddField(
            model_name="payrollline",
            name="gratuity_charge",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.CreateModel(
            name="GratuitySetting",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("effective_from", models.DateField()),
                ("service_from", models.DateField()),
                ("months_per_year", models.DecimalField(decimal_places=2, max_digits=4)),
                ("after_years", models.PositiveSmallIntegerField()),
                ("reason", models.CharField(max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("awaiting", "Waiting for the Director"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("withdrawn", "Withdrawn"),
                        ],
                        default="awaiting",
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="gratuity_settings",
                        to="payroll.employee",
                    ),
                ),
            ],
            options={
                "ordering": ["employee", "-effective_from", "-id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            after_years__lte=5, months_per_year__gte=Decimal("0.5")
                        ),
                        name="payroll_gratuity_not_below_act",
                    )
                ],
            },
        ),
        migrations.RunSQL(SQL, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
