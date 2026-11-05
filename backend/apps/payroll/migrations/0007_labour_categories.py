from django.db import migrations, models

# P2B-16: labour categories (owner, 5 Nov 2026).
# - Each employee is Shop and Office or Wages Board.
# - Leave types may give Wages Board staff another rule and days; one leave may be limited.
# - Short leave is paid for Shop and Office staff and unpaid for Wages Board staff (a quarter
#   of a day's pay each); the checked overtime keeps the unpaid short leaves, so the guard of
#   migration 0005 now also protects that column.
FORWARD = """
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
            NEW.nopay_minutes, NEW.nopay_days, NEW.unpaid_short_leaves, NEW.checked_by_id,
            NEW.checked_at)
        IS DISTINCT FROM
        ROW(OLD.employee_id, OLD.month, OLD.rule_id, OLD.ot_working_minutes,
            OLD.ot_sunday_minutes, OLD.ot_holiday_minutes, OLD.short_minutes,
            OLD.nopay_minutes, OLD.nopay_days, OLD.unpaid_short_leaves, OLD.checked_by_id,
            OLD.checked_at) THEN
    RAISE EXCEPTION 'Checked overtime never changes; it can only be voided'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

BACKWARD = """
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
"""

RULES = [
    ("annual_soe", "Annual leave rule (by quarter of joining)"),
    ("casual_soe", "Casual leave rule (half a day a month in the first year)"),
    ("after_joining", "None in the year of joining, then the full days"),
    ("fixed", "Same days every year"),
    ("unlimited", "No balance kept"),
]


def seed(apps, schema_editor):
    # Owner, 5 Nov 2026 (questions 8 and follow-up 6); maternity by the Shop and Office
    # Employees Act and the Maternity Benefits Ordinance as amended by Acts No. 14 and 15 of
    # 2018: 84 working days for each live birth (42 for a still birth), paid.
    LeaveType = apps.get_model("payroll", "LeaveType")
    LeaveType.objects.filter(code="ANNUAL").update(wb_rule="after_joining", wb_days=7)
    LeaveType.objects.filter(code="CASUAL", name="Casual leave").update(
        name="Casual and sick leave"
    )
    LeaveType.objects.filter(code="MATERNITY").update(max_days=84, paid=True)


class Migration(migrations.Migration):
    dependencies = [("payroll", "0006_pay_period")]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="category",
            field=models.CharField(
                choices=[("shop_office", "Shop and Office"), ("wages_board", "Wages Board")],
                default="shop_office",
                max_length=12,
            ),
        ),
        migrations.AlterField(
            model_name="leavetype",
            name="rule",
            field=models.CharField(choices=RULES, max_length=13),
        ),
        migrations.AddField(
            model_name="leavetype",
            name="wb_rule",
            field=models.CharField(blank=True, choices=RULES, max_length=13),
        ),
        migrations.AddField(
            model_name="leavetype",
            name="wb_days",
            field=models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="leavetype",
            name="max_days",
            field=models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name="workrule",
            name="short_leave_paid_wb",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="overtimecheck",
            name="unpaid_short_leaves",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
