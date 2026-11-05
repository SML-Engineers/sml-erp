import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# P2B-02: pay components and each employee's dated amounts.
# - A component is never deleted and its code never changes (rule 9).
# - An amount row is never changed (rule 11): a raise is a new row from its month. A row that
#   has not yet taken effect (its month is still to come) may be withdrawn; nothing else.
FORWARD = """
CREATE OR REPLACE FUNCTION payroll_component_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Pay component % is never deleted; deactivate it instead', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.code IS DISTINCT FROM OLD.code OR NEW.kind IS DISTINCT FROM OLD.kind THEN
    RAISE EXCEPTION 'A pay component''s code and kind never change (%)', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_component_guard
BEFORE UPDATE OR DELETE ON payroll_paycomponent
FOR EACH ROW EXECUTE FUNCTION payroll_component_guard();

CREATE OR REPLACE FUNCTION payroll_rate_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW IS NOT DISTINCT FROM OLD THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'A pay amount is never changed; enter a new amount from a later month'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.effective_from <= CURRENT_DATE THEN
    RAISE EXCEPTION 'A pay amount that has taken effect is never withdrawn'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_rate_guard
BEFORE UPDATE OR DELETE ON payroll_payrate
FOR EACH ROW EXECUTE FUNCTION payroll_rate_guard();

ALTER TABLE payroll_payrate
  ADD CONSTRAINT payroll_rate_first_of_month CHECK (EXTRACT(DAY FROM effective_from) = 1);
"""

BACKWARD = """
ALTER TABLE payroll_payrate DROP CONSTRAINT IF EXISTS payroll_rate_first_of_month;
DROP TRIGGER IF EXISTS payroll_rate_guard ON payroll_payrate;
DROP FUNCTION IF EXISTS payroll_rate_guard();
DROP TRIGGER IF EXISTS payroll_component_guard ON payroll_paycomponent;
DROP FUNCTION IF EXISTS payroll_component_guard();
"""

# Starting list (backlog question 6 still open): HR changes names and flags, adds and
# deactivates components. Which count for EPF and APIT is confirmed with the Accountant.
# The budgetary relief allowance is not here: it stopped being paid separately on
# 31 March 2025 and is part of the basic wage (Acts No. 9 and 10 of 2025).
COMPONENTS = [
    # code, name, kind, basis, EPF, APIT, order
    ("BASIC", "Basic salary", "earning", "fixed", True, True, 10),
    ("FIXED", "Fixed allowance", "earning", "fixed", True, True, 20),
    ("ATTEND", "Attendance allowance", "earning", "variable", True, True, 30),
    ("TRAVEL", "Travelling allowance", "earning", "fixed", False, True, 40),
    ("INCENTIVE", "Incentive", "earning", "variable", False, True, 50),
    ("WELFARE", "Welfare society", "deduction", "fixed", False, False, 10),
    ("UNION", "Trade union", "deduction", "fixed", False, False, 20),
    ("LOAN", "Loan recovery", "deduction", "fixed", False, False, 30),
    ("ADVANCE", "Salary advance recovery", "deduction", "variable", False, False, 40),
]


def seed(apps, schema_editor):
    PayComponent = apps.get_model("payroll", "PayComponent")
    for code, name, kind, basis, epf, apit, order in COMPONENTS:
        PayComponent.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "kind": kind,
                "basis": basis,
                "epf_liable": epf,
                "apit_taxable": apit,
                "sort_order": order,
            },
        )


def _user(**extra):
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to=settings.AUTH_USER_MODEL,
        **extra,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PayComponent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=100)),
                (
                    "kind",
                    models.CharField(
                        choices=[("earning", "Earning"), ("deduction", "Deduction")],
                        max_length=10,
                    ),
                ),
                (
                    "basis",
                    models.CharField(
                        choices=[
                            ("fixed", "Fixed each month"),
                            ("variable", "Entered each month"),
                        ],
                        default="fixed",
                        max_length=10,
                    ),
                ),
                (
                    "epf_liable",
                    models.BooleanField(default=False, verbose_name="counts for EPF and ETF"),
                ),
                (
                    "apit_taxable",
                    models.BooleanField(default=False, verbose_name="taxable for APIT"),
                ),
                ("sort_order", models.PositiveSmallIntegerField(default=100)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", _user(blank=True, null=True)),
            ],
            options={
                "ordering": ["kind", "sort_order", "code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("kind", "earning"))
                        | models.Q(("epf_liable", False), ("apit_taxable", False)),
                        name="payroll_component_deduction_flags",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="PayRate",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("effective_from", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("reason", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "component",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="payroll.paycomponent",
                    ),
                ),
                ("created_by", _user()),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="pay_rates",
                        to="payroll.employee",
                    ),
                ),
            ],
            options={
                "ordering": ["employee", "component", "-effective_from"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("employee", "component", "effective_from"),
                        name="payroll_rate_once",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("amount__gte", 0)), name="payroll_rate_amount"
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
