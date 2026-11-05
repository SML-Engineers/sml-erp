import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Employees (backlog P2B-01). The employee number never changes and an employee is never
# deleted, only deactivated (rule 9).

FORWARD = """
CREATE OR REPLACE FUNCTION payroll_employee_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Employee % is never deleted; deactivate them instead', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.number IS DISTINCT FROM OLD.number THEN
    RAISE EXCEPTION 'Employee numbers never change (%)', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_employee_guard
BEFORE UPDATE OR DELETE ON payroll_employee
FOR EACH ROW EXECUTE FUNCTION payroll_employee_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS payroll_employee_guard ON payroll_employee;
DROP FUNCTION IF EXISTS payroll_employee_guard();
"""


def _user(**extra):
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to=settings.AUTH_USER_MODEL,
        **extra,
    )


def hr_role_on(apps, schema_editor):
    # Phase 2b (P2B-01): the HR and Payroll Officer role is switched on.
    apps.get_model("core", "Role").objects.filter(code="hr_payroll_officer").update(is_active=True)


def hr_role_off(apps, schema_editor):
    apps.get_model("core", "Role").objects.filter(code="hr_payroll_officer").update(
        is_active=False
    )


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0026_sentemail_other_attachments"),
        ("masters", "0011_limit_no_maximum"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Employee",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("number", models.CharField(max_length=20, unique=True)),
                ("full_name", models.CharField(max_length=200)),
                ("name_with_initials", models.CharField(blank=True, max_length=100)),
                ("nic", models.CharField(max_length=12, unique=True, verbose_name="NIC")),
                ("date_of_birth", models.DateField(blank=True, null=True)),
                ("address", models.CharField(blank=True, max_length=300)),
                ("phone", models.CharField(blank=True, max_length=30)),
                ("email", models.EmailField(blank=True, max_length=254)),
                (
                    "epf_no",
                    models.CharField(blank=True, max_length=20, verbose_name="EPF number"),
                ),
                (
                    "etf_no",
                    models.CharField(blank=True, max_length=20, verbose_name="ETF number"),
                ),
                ("designation", models.CharField(blank=True, max_length=100)),
                ("grade", models.CharField(blank=True, max_length=30)),
                (
                    "employment_type",
                    models.CharField(
                        choices=[
                            ("permanent", "Permanent"),
                            ("probation", "On probation"),
                            ("contract", "Contract"),
                            ("casual", "Casual"),
                            ("trainee", "Trainee"),
                        ],
                        max_length=12,
                    ),
                ),
                ("join_date", models.DateField()),
                ("confirmation_date", models.DateField(blank=True, null=True)),
                ("leaving_date", models.DateField(blank=True, null=True)),
                ("leaving_reason", models.CharField(blank=True, max_length=200)),
                ("bank_name", models.CharField(blank=True, max_length=100)),
                ("bank_branch", models.CharField(blank=True, max_length=100)),
                ("account_name", models.CharField(blank=True, max_length=200)),
                ("account_number", models.CharField(blank=True, max_length=34)),
                ("bank_changed_at", models.DateTimeField(blank=True, null=True)),
                ("bank_checked_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "division",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="core.division",
                    ),
                ),
                (
                    "section",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="masters.section",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="employee",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("bank_changed_by", _user(blank=True, null=True)),
                ("bank_checked_by", _user(blank=True, null=True)),
                ("created_by", _user()),
            ],
            options={
                "ordering": ["number"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("leaving_date__isnull", True))
                        | models.Q(("leaving_date__gte", models.F("join_date"))),
                        name="payroll_employee_dates",
                    )
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(hr_role_on, hr_role_off),
    ]
