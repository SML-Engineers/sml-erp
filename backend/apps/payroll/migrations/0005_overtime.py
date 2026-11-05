from decimal import Decimal

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# P2B-05: working-time and overtime rules, and checked overtime.
# - A rule is never changed (rule 11); one whose month has not come may be withdrawn.
# - A checked month is never changed or removed; reopening attendance only voids it.
FORWARD = """
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

CREATE TRIGGER payroll_workrule_guard
BEFORE UPDATE OR DELETE ON payroll_workrule
FOR EACH ROW EXECUTE FUNCTION payroll_workrule_guard();

ALTER TABLE payroll_workrule
  ADD CONSTRAINT payroll_workrule_first CHECK (EXTRACT(DAY FROM effective_from) = 1);

CREATE OR REPLACE FUNCTION payroll_otcheck_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Checked overtime is never removed'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.voided OR NOT NEW.voided
     OR ROW(NEW.employee_id, NEW.month, NEW.rule_id, NEW.ot_working_minutes,
            NEW.ot_sunday_minutes, NEW.ot_holiday_minutes, NEW.short_minutes,
            NEW.nopay_minutes, NEW.nopay_days, NEW.checked_by_id, NEW.checked_at)
        IS DISTINCT FROM
        ROW(OLD.employee_id, OLD.month, OLD.rule_id, OLD.ot_working_minutes,
            OLD.ot_sunday_minutes, OLD.ot_holiday_minutes, OLD.short_minutes,
            OLD.nopay_minutes, OLD.nopay_days, OLD.checked_by_id, OLD.checked_at) THEN
    RAISE EXCEPTION 'Checked overtime never changes; it can only be voided'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_otcheck_guard
BEFORE UPDATE OR DELETE ON payroll_overtimecheck
FOR EACH ROW EXECUTE FUNCTION payroll_otcheck_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS payroll_otcheck_guard ON payroll_overtimecheck;
DROP FUNCTION IF EXISTS payroll_otcheck_guard();
ALTER TABLE payroll_workrule DROP CONSTRAINT IF EXISTS payroll_workrule_first;
DROP TRIGGER IF EXISTS payroll_workrule_guard ON payroll_workrule;
DROP FUNCTION IF EXISTS payroll_workrule_guard();
"""


def seed(apps, schema_editor):
    # Backlog question 5 not answered: the plan's default for every division.
    Division = apps.get_model("core", "Division")
    WorkRule = apps.get_model("payroll", "WorkRule")
    for division in Division.objects.all():
        WorkRule.objects.get_or_create(
            division=division,
            effective_from="2024-01-01",
            defaults={"reason": "Default (backlog question 5); confirm with the Accountant"},
        )


def _id():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


def _fk(to, related_name="+", **extra):
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name=related_name, to=to, **extra
    )


def _rate(value):
    return models.DecimalField(decimal_places=2, default=Decimal(value), max_digits=4)


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0004_attendance"),
        ("core", "0026_sentemail_other_attachments"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkRule",
            fields=[
                ("id", _id()),
                ("effective_from", models.DateField()),
                ("normal_day_minutes", models.PositiveSmallIntegerField(default=480)),
                ("grace_minutes", models.PositiveSmallIntegerField(default=10)),
                ("short_leaves_per_month", models.PositiveSmallIntegerField(default=2)),
                ("short_leave_minutes", models.PositiveSmallIntegerField(default=90)),
                ("ot_min_minutes", models.PositiveSmallIntegerField(default=30)),
                ("ot_step_minutes", models.PositiveSmallIntegerField(default=15)),
                ("rate_working_day", _rate("1.50")),
                ("rate_sunday", _rate("2.00")),
                ("rate_holiday", _rate("2.00")),
                ("hourly_divisor", models.PositiveSmallIntegerField(default=240)),
                ("reason", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", _fk(settings.AUTH_USER_MODEL, blank=True, null=True)),
                ("division", _fk("core.division")),
            ],
            options={
                "ordering": ["division", "-effective_from"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("division", "effective_from"), name="payroll_workrule_once"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            normal_day_minutes__gt=0,
                            ot_step_minutes__gt=0,
                            hourly_divisor__gt=0,
                            rate_working_day__gte=1,
                            rate_sunday__gte=1,
                            rate_holiday__gte=1,
                        ),
                        name="payroll_workrule_values",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="OvertimeCheck",
            fields=[
                ("id", _id()),
                ("month", models.DateField()),
                ("ot_working_minutes", models.PositiveIntegerField()),
                ("ot_sunday_minutes", models.PositiveIntegerField()),
                ("ot_holiday_minutes", models.PositiveIntegerField()),
                ("short_minutes", models.PositiveIntegerField()),
                ("nopay_minutes", models.PositiveIntegerField()),
                ("nopay_days", models.DecimalField(decimal_places=1, max_digits=4)),
                ("checked_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("voided", models.BooleanField(default=False)),
                ("checked_by", _fk(settings.AUTH_USER_MODEL)),
                ("employee", _fk("payroll.employee")),
                ("rule", _fk("payroll.workrule")),
            ],
            options={
                "ordering": ["-month", "employee"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(voided=False),
                        fields=("employee", "month"),
                        name="payroll_otcheck_once",
                    )
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
