import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# P2B-10: salary advances and staff loans.
# - Approved by the Director (approval type "staff_credit"); numbered on approval.
# - Decided (approved, rejected, withdrawn): never changed; never deleted.
SQL = """
CREATE OR REPLACE FUNCTION payroll_credit_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'An advance or loan is never deleted; withdraw it instead'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status IN ('approved', 'rejected', 'withdrawn') THEN
    RAISE EXCEPTION 'An advance or loan that is % never changes', OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_credit_guard
BEFORE UPDATE OR DELETE ON payroll_staffcredit
FOR EACH ROW EXECUTE FUNCTION payroll_credit_guard();

ALTER TABLE payroll_staffcredit
  ADD CONSTRAINT payroll_credit_first CHECK (EXTRACT(DAY FROM first_month) = 1);
"""

BACKWARD = """
ALTER TABLE payroll_staffcredit DROP CONSTRAINT IF EXISTS payroll_credit_first;
DROP TRIGGER IF EXISTS payroll_credit_guard ON payroll_staffcredit;
DROP FUNCTION IF EXISTS payroll_credit_guard();
"""

SERIES = ("staff_credit", "Advances and loans", "SL{YY}{MM}{XX}", "monthly", "grow")


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
    if director and not ApprovalRule.objects.filter(document_type="staff_credit").exists():
        ApprovalRule.objects.create(document_type="staff_credit", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="staff_credit", defaults={"enabled": True, "after_days": 1}
    )


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0011_payslip_email"),
        ("core", "0027_company_epf_etf"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffCredit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[("advance", "Salary advance"), ("loan", "Loan")], max_length=10
                    ),
                ),
                ("number", models.CharField(blank=True, max_length=30)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("interest", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ("months", models.PositiveSmallIntegerField(default=1)),
                ("first_month", models.DateField()),
                ("reason", models.CharField(max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("awaiting", "Waiting for the Director"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("withdrawn", "Withdrawn"),
                        ],
                        default="draft",
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
                        related_name="credits",
                        to="payroll.employee",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(amount__gt=0, interest__gte=0, months__gte=1),
                        name="payroll_credit_amounts",
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="payrollitem",
            name="credit",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="recoveries",
                to="payroll.staffcredit",
            ),
        ),
        migrations.RunSQL(SQL, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
