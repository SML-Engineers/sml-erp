from datetime import UTC, datetime

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# P2B-15: the pay period (owner, 5 Nov 2026: the 21st to the 20th, paid on the last day of
# the month). Pay month M starts on the rule's day of the month before M (1 = the calendar
# month) and ends the day before pay month M+1 starts (apps/payroll/periods.py).
# - Confirmed attendance is frozen per pay month, no longer per calendar month.
# - A work rule is in force from the first day of its pay month.
# - A pay period rule never changes; it is withdrawn only while neither its pay month nor the
#   one before it is confirmed anywhere.
FORWARD = """
CREATE OR REPLACE FUNCTION payroll_period_start(m date) RETURNS date AS $$
  SELECT CASE WHEN s.d = 1 THEN date_trunc('month', m)::date
              ELSE (date_trunc('month', m) - interval '1 month')::date + (s.d - 1) END
  FROM (SELECT COALESCE((
          SELECT r.start_day FROM payroll_payperiodrule r
          WHERE r.effective_from <= date_trunc('month', m)::date
          ORDER BY r.effective_from DESC LIMIT 1), 1)::int AS d) s;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION payroll_pay_month(p_day date) RETURNS date AS $$
  SELECT CASE
    WHEN p_day >= payroll_period_start((date_trunc('month', p_day) + interval '1 month')::date)
      THEN (date_trunc('month', p_day) + interval '1 month')::date
    ELSE date_trunc('month', p_day)::date END;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION payroll_attendance_guard() RETURNS trigger AS $$
DECLARE
  row_employee bigint;
  row_date date;
BEGIN
  IF TG_OP = 'DELETE' THEN
    row_employee := OLD.employee_id; row_date := OLD.date;
  ELSE
    row_employee := NEW.employee_id; row_date := NEW.date;
  END IF;
  IF EXISTS (
    SELECT 1 FROM payroll_attendancemonth m
    JOIN payroll_employee e ON e.division_id = m.division_id
    WHERE e.id = row_employee AND m.confirmed
      AND m.month = payroll_pay_month(row_date)
  ) OR (TG_OP = 'UPDATE' AND EXISTS (
    SELECT 1 FROM payroll_attendancemonth m
    JOIN payroll_employee e ON e.division_id = m.division_id
    WHERE e.id = OLD.employee_id AND m.confirmed
      AND m.month = payroll_pay_month(OLD.date)
  )) THEN
    RAISE EXCEPTION 'Attendance for pay month % is confirmed and never changes; reopen it first',
      to_char(payroll_pay_month(row_date), 'YYYY-MM') USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION payroll_workrule_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW IS NOT DISTINCT FROM OLD THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'A work rule never changes; enter a new rule from a later month'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF payroll_period_start(OLD.effective_from) <= CURRENT_DATE THEN
    RAISE EXCEPTION 'A work rule in force is never withdrawn'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION payroll_payperiod_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW IS NOT DISTINCT FROM OLD THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'A pay period rule never changes; enter a new rule from a later pay month'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF EXISTS (
    SELECT 1 FROM payroll_attendancemonth m
    WHERE m.confirmed AND m.month >= (OLD.effective_from - interval '1 month')::date
  ) THEN
    RAISE EXCEPTION 'Attendance under this pay period rule is confirmed; it is never withdrawn'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_payperiod_guard
BEFORE UPDATE OR DELETE ON payroll_payperiodrule
FOR EACH ROW EXECUTE FUNCTION payroll_payperiod_guard();

ALTER TABLE payroll_payperiodrule
  ADD CONSTRAINT payroll_payperiod_first CHECK (EXTRACT(DAY FROM effective_from) = 1);
"""

# Back to the calendar month of migrations 0004 and 0005.
BACKWARD = """
ALTER TABLE payroll_payperiodrule DROP CONSTRAINT IF EXISTS payroll_payperiod_first;
DROP TRIGGER IF EXISTS payroll_payperiod_guard ON payroll_payperiodrule;
DROP FUNCTION IF EXISTS payroll_payperiod_guard();

CREATE OR REPLACE FUNCTION payroll_workrule_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW IS NOT DISTINCT FROM OLD THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'A work rule never changes; enter a new rule from a later month'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.effective_from <= CURRENT_DATE THEN
    RAISE EXCEPTION 'A work rule in force is never withdrawn'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION payroll_attendance_guard() RETURNS trigger AS $$
DECLARE
  row_employee bigint;
  row_date date;
BEGIN
  IF TG_OP = 'DELETE' THEN
    row_employee := OLD.employee_id; row_date := OLD.date;
  ELSE
    row_employee := NEW.employee_id; row_date := NEW.date;
  END IF;
  IF EXISTS (
    SELECT 1 FROM payroll_attendancemonth m
    JOIN payroll_employee e ON e.division_id = m.division_id
    WHERE e.id = row_employee AND m.confirmed
      AND m.month = date_trunc('month', row_date)::date
  ) OR (TG_OP = 'UPDATE' AND EXISTS (
    SELECT 1 FROM payroll_attendancemonth m
    JOIN payroll_employee e ON e.division_id = m.division_id
    WHERE e.id = OLD.employee_id AND m.confirmed
      AND m.month = date_trunc('month', OLD.date)::date
  )) THEN
    RAISE EXCEPTION 'Attendance for % is confirmed and never changes; reopen the month first',
      to_char(row_date, 'YYYY-MM') USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP FUNCTION IF EXISTS payroll_pay_month(date);
DROP FUNCTION IF EXISTS payroll_period_start(date);
"""


def seed(apps, schema_editor):
    PayPeriodRule = apps.get_model("payroll", "PayPeriodRule")
    PayPeriodRule.objects.get_or_create(
        effective_from="2024-01-01",
        defaults={
            "start_day": 21,
            "reason": "Owner, 5 Nov 2026: the 21st to the 20th, paid on the last day of the month",
            # A whole-second time: test databases reload this row and must find it equal.
            "created_at": datetime(2024, 1, 1, tzinfo=UTC),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0005_overtime"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PayPeriodRule",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("effective_from", models.DateField(unique=True)),
                ("start_day", models.PositiveSmallIntegerField(default=21)),
                ("reason", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
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
            ],
            options={
                "ordering": ["-effective_from"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(start_day__gte=1, start_day__lte=28),
                        name="payroll_payperiod_day",
                    )
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
