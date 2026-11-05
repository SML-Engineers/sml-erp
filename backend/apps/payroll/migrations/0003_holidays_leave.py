import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# P2B-03: holidays, leave types, leave granted and leave taken.
# - A holiday that has passed is never removed or changed; a holiday's date never changes.
# - A leave type is never deleted and its code never changes.
# - Leave granted is insert-only: a correction is another adjustment.
# - Leave taken is never deleted; its employee, type, dates and days never change (only its
#   status moves on: approved, rejected or cancelled).
FORWARD = """
CREATE OR REPLACE FUNCTION payroll_holiday_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.date <= CURRENT_DATE THEN
      RAISE EXCEPTION 'The holiday on % has passed and is kept', OLD.date
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF NEW.date IS DISTINCT FROM OLD.date OR OLD.date <= CURRENT_DATE THEN
    RAISE EXCEPTION 'A holiday''s date never changes, and a past holiday is kept as it was'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_holiday_guard
BEFORE UPDATE OR DELETE ON payroll_holiday
FOR EACH ROW EXECUTE FUNCTION payroll_holiday_guard();

CREATE OR REPLACE FUNCTION payroll_leavetype_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Leave type % is never deleted; deactivate it instead', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.code IS DISTINCT FROM OLD.code THEN
    RAISE EXCEPTION 'A leave type''s code never changes (%)', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_leavetype_guard
BEFORE UPDATE OR DELETE ON payroll_leavetype
FOR EACH ROW EXECUTE FUNCTION payroll_leavetype_guard();

CREATE TRIGGER payroll_leavegrant_insert_only
BEFORE UPDATE OR DELETE ON payroll_leavegrant
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();

CREATE OR REPLACE FUNCTION payroll_leave_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Leave is never deleted; cancel it instead'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.employee_id IS DISTINCT FROM OLD.employee_id
     OR NEW.leave_type_id IS DISTINCT FROM OLD.leave_type_id
     OR NEW.start IS DISTINCT FROM OLD.start
     OR NEW."end" IS DISTINCT FROM OLD."end"
     OR NEW.half_day IS DISTINCT FROM OLD.half_day
     OR NEW.days IS DISTINCT FROM OLD.days THEN
    RAISE EXCEPTION 'Recorded leave never changes; cancel it and record it again'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_leave_guard
BEFORE UPDATE OR DELETE ON payroll_leave
FOR EACH ROW EXECUTE FUNCTION payroll_leave_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS payroll_leave_guard ON payroll_leave;
DROP FUNCTION IF EXISTS payroll_leave_guard();
DROP TRIGGER IF EXISTS payroll_leavegrant_insert_only ON payroll_leavegrant;
DROP TRIGGER IF EXISTS payroll_leavetype_guard ON payroll_leavetype;
DROP FUNCTION IF EXISTS payroll_leavetype_guard();
DROP TRIGGER IF EXISTS payroll_holiday_guard ON payroll_holiday;
DROP FUNCTION IF EXISTS payroll_holiday_guard();
"""

# Defaults (backlog question 8): the Shop and Office Employees Act rules, no carry-forward.
# HR changes days and adds types (e.g. the Wages Board's) on the Holidays and leave page.
LEAVE_TYPES = [
    # code, name, rule, days, paid
    ("ANNUAL", "Annual leave", "annual_soe", 14, True),
    ("CASUAL", "Casual leave", "casual_soe", 7, True),
    ("MATERNITY", "Maternity leave", "unlimited", 0, True),
    ("NOPAY", "No-pay leave", "unlimited", 0, False),
]


def seed(apps, schema_editor):
    LeaveType = apps.get_model("payroll", "LeaveType")
    for code, name, rule, days, paid in LEAVE_TYPES:
        LeaveType.objects.get_or_create(
            code=code, defaults={"name": name, "rule": rule, "days": days, "paid": paid}
        )


def _user(**extra):
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to=settings.AUTH_USER_MODEL,
        **extra,
    )


def _id():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


def _fk(to, related_name="+"):
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name=related_name, to=to
    )


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0002_pay_structure"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Holiday",
            fields=[
                ("id", _id()),
                ("date", models.DateField(unique=True)),
                ("name", models.CharField(max_length=100)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("public", "Public holiday"),
                            ("bank", "Bank holiday"),
                            ("mercantile", "Mercantile holiday"),
                            ("poya", "Full moon Poya day"),
                            ("company", "Company holiday"),
                        ],
                        max_length=12,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", _user()),
            ],
            options={"ordering": ["date"]},
        ),
        migrations.CreateModel(
            name="LeaveType",
            fields=[
                ("id", _id()),
                ("code", models.CharField(max_length=12, unique=True)),
                ("name", models.CharField(max_length=100)),
                (
                    "rule",
                    models.CharField(
                        choices=[
                            ("annual_soe", "Annual leave rule (by quarter of joining)"),
                            (
                                "casual_soe",
                                "Casual leave rule (half a day a month in the first year)",
                            ),
                            ("fixed", "Same days every year"),
                            ("unlimited", "No balance kept"),
                        ],
                        max_length=12,
                    ),
                ),
                ("days", models.DecimalField(decimal_places=1, default=0, max_digits=5)),
                ("paid", models.BooleanField(default=True)),
                (
                    "carry_forward_max",
                    models.DecimalField(decimal_places=1, default=0, max_digits=5),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "ordering": ["code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(days__gte=0, carry_forward_max__gte=0),
                        name="payroll_leavetype_days",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="LeaveGrant",
            fields=[
                ("id", _id()),
                ("year", models.PositiveSmallIntegerField()),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("entitlement", "Entitlement"),
                            ("carried", "Carried forward"),
                            ("adjustment", "Adjustment"),
                        ],
                        max_length=12,
                    ),
                ),
                ("days", models.DecimalField(decimal_places=1, max_digits=5)),
                ("reason", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", _user()),
                ("employee", _fk("payroll.employee", "leave_grants")),
                ("leave_type", _fk("payroll.leavetype")),
            ],
            options={
                "ordering": ["employee", "year", "leave_type", "created_at"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=~models.Q(kind="adjustment"),
                        fields=("employee", "leave_type", "year", "kind"),
                        name="payroll_leavegrant_once",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Leave",
            fields=[
                ("id", _id()),
                ("start", models.DateField()),
                ("end", models.DateField()),
                ("half_day", models.BooleanField(default=False)),
                ("days", models.DecimalField(decimal_places=1, max_digits=5)),
                ("reason", models.CharField(blank=True, max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("applied", "Applied for"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("cancelled", "Cancelled"),
                        ],
                        max_length=10,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("hr", "Recorded by HR"),
                            ("applied", "Applied for by the employee"),
                            ("attendance", "From attendance"),
                        ],
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.CharField(blank=True, max_length=200)),
                ("created_by", _user()),
                ("decided_by", _user(blank=True, null=True)),
                ("employee", _fk("payroll.employee", "leaves")),
                ("leave_type", _fk("payroll.leavetype")),
            ],
            options={
                "ordering": ["-start", "employee"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(end__gte=models.F("start")),
                        name="payroll_leave_dates",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(half_day=False) | models.Q(end=models.F("start")),
                        name="payroll_leave_half_day",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(days__gt=0), name="payroll_leave_days"
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
