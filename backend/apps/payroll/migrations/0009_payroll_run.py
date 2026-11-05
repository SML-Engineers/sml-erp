from datetime import UTC, datetime
from decimal import Decimal

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# P2B-06: the monthly payroll run.
# - A payroll is never deleted; once approved or rejected it never changes.
# - Its lines, items and amounts typed in change only while it is a draft.
# - EPF/ETF rates and APIT tables are dated (rule 11); one in force never changes.
FORWARD = """
CREATE OR REPLACE FUNCTION payroll_run_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A payroll is never deleted' USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status IN ('approved', 'rejected') THEN
    RAISE EXCEPTION 'A payroll that is % never changes', OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_run_guard
BEFORE UPDATE OR DELETE ON payroll_payrollrun
FOR EACH ROW EXECUTE FUNCTION payroll_run_guard();

-- Lines and amounts typed in: only while the payroll is a draft.
CREATE OR REPLACE FUNCTION payroll_run_part_guard() RETURNS trigger AS $$
DECLARE
  run_status text;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  SELECT status INTO run_status FROM payroll_payrollrun
  WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.run_id ELSE NEW.run_id END;
  IF run_status IS DISTINCT FROM 'draft' THEN
    RAISE EXCEPTION 'A payroll changes only while it is a draft'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON payroll_payrollline
FOR EACH ROW EXECUTE FUNCTION payroll_run_part_guard();

CREATE TRIGGER payroll_entry_guard
BEFORE INSERT OR UPDATE OR DELETE ON payroll_payrollentry
FOR EACH ROW EXECUTE FUNCTION payroll_run_part_guard();

-- Items: through their line. A line already removed (with its draft payroll's figures being
-- worked out again) takes its items with it.
CREATE OR REPLACE FUNCTION payroll_item_guard() RETURNS trigger AS $$
DECLARE
  run_status text;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  SELECT r.status INTO run_status
  FROM payroll_payrollline l JOIN payroll_payrollrun r ON r.id = l.run_id
  WHERE l.id = CASE WHEN TG_OP = 'DELETE' THEN OLD.line_id ELSE NEW.line_id END;
  IF NOT FOUND AND TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  IF run_status IS DISTINCT FROM 'draft' THEN
    RAISE EXCEPTION 'A payroll changes only while it is a draft'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_item_guard
BEFORE INSERT OR UPDATE OR DELETE ON payroll_payrollitem
FOR EACH ROW EXECUTE FUNCTION payroll_item_guard();

-- Dated rates and tables in force never change.
CREATE OR REPLACE FUNCTION payroll_dated_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.effective_from <= CURRENT_DATE THEN
    RAISE EXCEPTION 'Rates in force never change; enter new ones from a later date'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_statutory_guard
BEFORE UPDATE OR DELETE ON payroll_statutoryrate
FOR EACH ROW EXECUTE FUNCTION payroll_dated_guard();

CREATE TRIGGER payroll_taxtable_guard
BEFORE UPDATE OR DELETE ON payroll_taxtable
FOR EACH ROW EXECUTE FUNCTION payroll_dated_guard();

CREATE OR REPLACE FUNCTION payroll_taxband_guard() RETURNS trigger AS $$
DECLARE
  starts date;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  SELECT effective_from INTO starts FROM payroll_taxtable
  WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.table_id ELSE NEW.table_id END;
  IF TG_OP <> 'INSERT' AND starts <= CURRENT_DATE THEN
    RAISE EXCEPTION 'An APIT table in force never changes'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_taxband_guard
BEFORE UPDATE OR DELETE ON payroll_taxband
FOR EACH ROW EXECUTE FUNCTION payroll_taxband_guard();

ALTER TABLE payroll_payrollrun
  ADD CONSTRAINT payroll_run_first CHECK (EXTRACT(DAY FROM month) = 1);
"""

BACKWARD = """
ALTER TABLE payroll_payrollrun DROP CONSTRAINT IF EXISTS payroll_run_first;
DROP TRIGGER IF EXISTS payroll_taxband_guard ON payroll_taxband;
DROP FUNCTION IF EXISTS payroll_taxband_guard();
DROP TRIGGER IF EXISTS payroll_taxtable_guard ON payroll_taxtable;
DROP TRIGGER IF EXISTS payroll_statutory_guard ON payroll_statutoryrate;
DROP FUNCTION IF EXISTS payroll_dated_guard();
DROP TRIGGER IF EXISTS payroll_item_guard ON payroll_payrollitem;
DROP FUNCTION IF EXISTS payroll_item_guard();
DROP TRIGGER IF EXISTS payroll_entry_guard ON payroll_payrollentry;
DROP TRIGGER IF EXISTS payroll_line_guard ON payroll_payrollline;
DROP FUNCTION IF EXISTS payroll_run_part_guard();
DROP TRIGGER IF EXISTS payroll_run_guard ON payroll_payrollrun;
DROP FUNCTION IF EXISTS payroll_run_guard();
"""

SEEDED = datetime(2024, 1, 1, tzinfo=UTC)  # whole seconds: test databases reload these rows

# IRD APIT Table 01 (primary employment), from 1 April 2025 (Inland Revenue (Amendment) Act
# No. 2 of 2025; the IRD's tables apply to later years until new ones are issued). Monthly:
# relief 150,000; then 6%, 18%, 24%, 30% on bands of 1,000,000 / 500,000 a year, 36% above.
# Tax = earnings x rate - constant.
TABLE_01 = [
    (Decimal("150000.00"), Decimal("0"), Decimal("0")),
    (Decimal("233333.33"), Decimal("6"), Decimal("9000")),
    (Decimal("275000.00"), Decimal("18"), Decimal("37000")),
    (Decimal("316666.67"), Decimal("24"), Decimal("53500")),
    (Decimal("358333.33"), Decimal("30"), Decimal("72500")),
    (None, Decimal("36"), Decimal("94000")),
]


def seed(apps, schema_editor):
    PayComponent = apps.get_model("payroll", "PayComponent")
    # Owner, follow-up 1: the day rate is worked out from basic + fixed allowances.
    PayComponent.objects.filter(code__in=["BASIC", "FIXED"]).update(in_day_rate=True)
    # The attendance bonus is a monthly amount in the employee's pay settings (P2B-17).
    PayComponent.objects.filter(code="ATTEND").update(basis="fixed")
    StatutoryRate = apps.get_model("payroll", "StatutoryRate")
    StatutoryRate.objects.get_or_create(
        effective_from="2024-01-01",
        defaults={
            "epf_employee": Decimal("8"),
            "epf_employer": Decimal("12"),
            "etf": Decimal("3"),
            "reason": "EPF Act: employee 8%, employer 12%; ETF Act: 3%",
            "created_at": SEEDED,
        },
    )
    TaxTable = apps.get_model("payroll", "TaxTable")
    TaxBand = apps.get_model("payroll", "TaxBand")
    table, made = TaxTable.objects.get_or_create(
        kind="primary",
        effective_from="2025-04-01",
        defaults={"reason": "IRD APIT Table 01, 2025/26 onwards", "created_at": SEEDED},
    )
    if made:
        for up_to, rate, constant in TABLE_01:
            TaxBand.objects.create(table=table, up_to=up_to, rate=rate, constant=constant)
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    director = Role.objects.filter(code="director").first()
    if director and not ApprovalRule.objects.filter(document_type="payroll").exists():
        ApprovalRule.objects.create(document_type="payroll", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="payroll", defaults={"enabled": True, "after_days": 1}
    )


ID = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")


def money():
    return models.DecimalField(decimal_places=2, max_digits=18)


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0008_pay_changes"),
        ("core", "0026_sentemail_other_attachments"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="paycomponent",
            name="in_day_rate",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="StatutoryRate",
            fields=[
                ("id", ID.clone()),
                ("effective_from", models.DateField(unique=True)),
                ("epf_employee", models.DecimalField(decimal_places=2, max_digits=5)),
                ("epf_employer", models.DecimalField(decimal_places=2, max_digits=5)),
                ("etf", models.DecimalField(decimal_places=2, max_digits=5)),
                ("reason", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={"ordering": ["-effective_from"]},
        ),
        migrations.CreateModel(
            name="TaxTable",
            fields=[
                ("id", ID.clone()),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("primary", "Table 01: primary employment"),
                            ("secondary", "Table 07: secondary employment"),
                        ],
                        max_length=10,
                    ),
                ),
                ("effective_from", models.DateField()),
                ("reason", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "ordering": ["kind", "-effective_from"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("kind", "effective_from"), name="payroll_tax_once"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="TaxBand",
            fields=[
                ("id", ID.clone()),
                (
                    "up_to",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True),
                ),
                ("rate", models.DecimalField(decimal_places=2, max_digits=5)),
                (
                    "constant",
                    models.DecimalField(decimal_places=2, default=0, max_digits=18),
                ),
                (
                    "table",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bands",
                        to="payroll.taxtable",
                    ),
                ),
            ],
            options={"ordering": ["table", "up_to"]},
        ),
        migrations.CreateModel(
            name="PayrollRun",
            fields=[
                ("id", ID.clone()),
                ("month", models.DateField()),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("awaiting", "Waiting for the Director"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        default="draft",
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("worked_out_at", models.DateTimeField(default=django.utils.timezone.now)),
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
                    "division",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="core.division",
                    ),
                ),
                (
                    "statutory",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="payroll.statutoryrate",
                    ),
                ),
            ],
            options={
                "ordering": ["-month", "division"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("status", "rejected"), _negated=True),
                        fields=("division", "month"),
                        name="payroll_run_once",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="PayrollLine",
            fields=[
                ("id", ID.clone()),
                ("days_employed", models.PositiveSmallIntegerField()),
                ("days_in_period", models.PositiveSmallIntegerField()),
                ("day_rate", money()),
                ("hourly_rate", money()),
                ("gross", money()),
                ("epf_earnings", money()),
                ("apit_earnings", money()),
                ("epf_employee", money()),
                ("epf_employer", money()),
                ("etf", money()),
                ("apit", money()),
                ("deductions", money()),
                ("net", money()),
                ("basic", money()),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="payroll.employee",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="payroll.payrollrun",
                    ),
                ),
            ],
            options={
                "ordering": ["run", "employee__number"],
                "constraints": [
                    models.UniqueConstraint(fields=("run", "employee"), name="payroll_line_once")
                ],
            },
        ),
        migrations.CreateModel(
            name="PayrollItem",
            fields=[
                ("id", ID.clone()),
                ("code", models.CharField(max_length=20)),
                ("name", models.CharField(max_length=100)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("earning", "Earning"),
                            ("deduction", "Deduction"),
                            ("employer", "Paid by the employer"),
                        ],
                        max_length=10,
                    ),
                ),
                ("amount", money()),
                ("basis", models.CharField(blank=True, max_length=300)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                (
                    "line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="payroll.payrollline",
                    ),
                ),
            ],
            options={"ordering": ["line", "sort_order", "id"]},
        ),
        migrations.CreateModel(
            name="PayrollEntry",
            fields=[
                ("id", ID.clone()),
                ("amount", money()),
                ("note", models.CharField(blank=True, max_length=200)),
                (
                    "component",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="payroll.paycomponent",
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="payroll.employee",
                    ),
                ),
                (
                    "run",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="entries",
                        to="payroll.payrollrun",
                    ),
                ),
            ],
            options={
                "ordering": ["run", "employee__number", "component__sort_order"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("run", "employee", "component"), name="payroll_entry_once"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(amount__gt=0), name="payroll_entry_amount"
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
