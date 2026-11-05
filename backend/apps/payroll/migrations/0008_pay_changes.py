import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# P2B-17: employees' pay settings approved by the Director (owner, 5 Nov 2026).
# - A pay change is prepared by HR and approved by the Director ("pay_change", level 2).
# - Decided once it is approved, rejected or withdrawn: never changed again; never deleted.
# - Its lines change only while it is a draft.
# - An employee's approved settings never change; one not yet in force may be replaced.
FORWARD = """
CREATE OR REPLACE FUNCTION payroll_change_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A pay change is never deleted; withdraw it instead'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status IN ('approved', 'rejected', 'withdrawn') THEN
    RAISE EXCEPTION 'A pay change that is % never changes', OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_change_guard
BEFORE UPDATE OR DELETE ON payroll_paychange
FOR EACH ROW EXECUTE FUNCTION payroll_change_guard();

CREATE OR REPLACE FUNCTION payroll_change_line_guard() RETURNS trigger AS $$
DECLARE
  change_status text;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  SELECT status INTO change_status FROM payroll_paychange
  WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.change_id ELSE NEW.change_id END;
  IF change_status IS DISTINCT FROM 'draft' THEN
    RAISE EXCEPTION 'The amounts of a pay change change only while it is a draft'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_change_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON payroll_paychangeline
FOR EACH ROW EXECUTE FUNCTION payroll_change_line_guard();

CREATE OR REPLACE FUNCTION payroll_setting_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW IS NOT DISTINCT FROM OLD THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'An employee''s approved settings never change; approve a new change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.effective_from <= CURRENT_DATE THEN
    RAISE EXCEPTION 'Settings in force are never removed'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_setting_guard
BEFORE UPDATE OR DELETE ON payroll_employeesetting
FOR EACH ROW EXECUTE FUNCTION payroll_setting_guard();

ALTER TABLE payroll_paychange
  ADD CONSTRAINT payroll_change_first CHECK (EXTRACT(DAY FROM effective_from) = 1);
ALTER TABLE payroll_employeesetting
  ADD CONSTRAINT payroll_setting_first CHECK (EXTRACT(DAY FROM effective_from) = 1);
"""

BACKWARD = """
ALTER TABLE payroll_employeesetting DROP CONSTRAINT IF EXISTS payroll_setting_first;
ALTER TABLE payroll_paychange DROP CONSTRAINT IF EXISTS payroll_change_first;
DROP TRIGGER IF EXISTS payroll_setting_guard ON payroll_employeesetting;
DROP FUNCTION IF EXISTS payroll_setting_guard();
DROP TRIGGER IF EXISTS payroll_change_line_guard ON payroll_paychangeline;
DROP FUNCTION IF EXISTS payroll_change_line_guard();
DROP TRIGGER IF EXISTS payroll_change_guard ON payroll_paychange;
DROP FUNCTION IF EXISTS payroll_change_guard();
"""


def seed(apps, schema_editor):
    PayComponent = apps.get_model("payroll", "PayComponent")
    PayComponent.objects.filter(code__in=["FIXED", "TRAVEL", "INCENTIVE"]).update(
        is_allowance=True
    )
    # Owner, 5 Nov 2026: the attendance bonus, default LKR 1,500.
    PayComponent.objects.filter(code="ATTEND", name="Attendance allowance").update(
        name="Attendance bonus"
    )
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    director = Role.objects.filter(code="director").first()
    if director and not ApprovalRule.objects.filter(document_type="pay_change").exists():
        ApprovalRule.objects.create(document_type="pay_change", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="pay_change", defaults={"enabled": True, "after_days": 1}
    )


ID = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
APIT = [
    ("primary", "Primary employment (IRD tables)"),
    ("secondary", "Secondary employment (IRD tables)"),
]


def setting_fields():
    return [
        ("normal_day_minutes", models.PositiveSmallIntegerField(blank=True, null=True)),
        ("grace_minutes", models.PositiveSmallIntegerField(blank=True, null=True)),
        (
            "rate_working_day",
            models.DecimalField(blank=True, decimal_places=2, max_digits=4, null=True),
        ),
        ("rate_sunday", models.DecimalField(blank=True, decimal_places=2, max_digits=4, null=True)),
        (
            "rate_holiday",
            models.DecimalField(blank=True, decimal_places=2, max_digits=4, null=True),
        ),
        (
            "annual_leave_days",
            models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True),
        ),
        (
            "casual_leave_days",
            models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True),
        ),
        ("apit", models.CharField(choices=APIT, default="primary", max_length=10)),
    ]


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0007_labour_categories"),
        ("core", "0026_sentemail_other_attachments"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="paycomponent",
            name="is_allowance",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="PayChange",
            fields=[
                ("id", ID.clone()),
                *setting_fields(),
                ("effective_from", models.DateField()),
                ("is_new_employee", models.BooleanField(default=False)),
                ("has_settings", models.BooleanField(default=False)),
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
                        related_name="pay_changes",
                        to="payroll.employee",
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="PayChangeLine",
            fields=[
                ("id", ID.clone()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("epf_liable", models.BooleanField(blank=True, null=True)),
                ("apit_taxable", models.BooleanField(blank=True, null=True)),
                (
                    "change",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="payroll.paychange",
                    ),
                ),
                (
                    "component",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="payroll.paycomponent",
                    ),
                ),
            ],
            options={
                "ordering": ["component__kind", "component__sort_order", "component__code"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("change", "component"), name="payroll_change_line"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(amount__gte=0), name="payroll_change_line_amount"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="EmployeeSetting",
            fields=[
                ("id", ID.clone()),
                *setting_fields(),
                ("effective_from", models.DateField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "change",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="payroll.paychange",
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="settings",
                        to="payroll.employee",
                    ),
                ),
            ],
            options={
                "ordering": ["employee", "-effective_from"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("employee", "effective_from"), name="payroll_setting_once"
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="payrate",
            name="epf_liable",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payrate",
            name="apit_taxable",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="payrate",
            name="change",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="payroll.paychange",
            ),
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
