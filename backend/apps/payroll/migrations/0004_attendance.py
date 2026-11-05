import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# P2B-04: attendance from the Excel sheet. Days of a month HR has confirmed for the
# employee's division never change: no new day, no change, no removal (database).
FORWARD = """
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

CREATE TRIGGER payroll_attendance_guard
BEFORE INSERT OR UPDATE OR DELETE ON payroll_attendanceday
FOR EACH ROW EXECUTE FUNCTION payroll_attendance_guard();

CREATE TRIGGER payroll_attendanceimport_insert_only
BEFORE UPDATE OR DELETE ON payroll_attendanceimport
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();

ALTER TABLE payroll_attendancemonth
  ADD CONSTRAINT payroll_attmonth_first CHECK (EXTRACT(DAY FROM month) = 1);
"""

BACKWARD = """
ALTER TABLE payroll_attendancemonth DROP CONSTRAINT IF EXISTS payroll_attmonth_first;
DROP TRIGGER IF EXISTS payroll_attendanceimport_insert_only ON payroll_attendanceimport;
DROP TRIGGER IF EXISTS payroll_attendance_guard ON payroll_attendanceday;
DROP FUNCTION IF EXISTS payroll_attendance_guard();
"""


def _id():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


def _fk(to, related_name="+", **extra):
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name=related_name, to=to, **extra
    )


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0003_holidays_leave"),
        ("core", "0026_sentemail_other_attachments"),
        ("masters", "0011_limit_no_maximum"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AttendanceImport",
            fields=[
                ("id", _id()),
                ("file_name", models.CharField(max_length=200)),
                ("sha256", models.CharField(max_length=64)),
                ("rows", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", _fk(settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="AttendanceMonth",
            fields=[
                ("id", _id()),
                ("month", models.DateField()),
                ("confirmed", models.BooleanField(default=False)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("confirmed_by", _fk(settings.AUTH_USER_MODEL, blank=True, null=True)),
                ("division", _fk("core.division")),
            ],
            options={
                "ordering": ["-month", "division"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("month", "division"), name="payroll_attmonth_once"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="AttendanceDay",
            fields=[
                ("id", _id()),
                ("date", models.DateField()),
                ("time_in", models.TimeField(blank=True, null=True)),
                ("time_out", models.TimeField(blank=True, null=True)),
                ("remarks", models.CharField(blank=True, max_length=200)),
                ("worked_minutes", models.PositiveIntegerField(default=0)),
                ("late_minutes", models.PositiveIntegerField(default=0)),
                ("early_minutes", models.PositiveIntegerField(default=0)),
                ("employee", _fk("payroll.employee", "attendance")),
                ("leave_type", _fk("payroll.leavetype", blank=True, null=True)),
                ("shift", _fk("masters.shift", blank=True, null=True)),
                ("source", _fk("payroll.attendanceimport", "days")),
            ],
            options={
                "ordering": ["employee", "date"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("employee", "date"), name="payroll_attendance_once"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(time_in__isnull=True, time_out__isnull=True)
                        | models.Q(time_in__isnull=False, time_out__isnull=False),
                        name="payroll_attendance_times",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
