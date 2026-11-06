import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# P2B-12: the phone punch clock.
# - Punches are insert-only (never changed or deleted).
# - Punch sites are never deleted (rule 9); deactivated instead.
SQL = """
CREATE TRIGGER payroll_punch_insert_only
BEFORE UPDATE OR DELETE ON payroll_punch
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();

CREATE OR REPLACE FUNCTION payroll_punchsite_guard() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'A punch site is never deleted; deactivate it instead'
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_punchsite_guard
BEFORE DELETE ON payroll_punchsite
FOR EACH ROW EXECUTE FUNCTION payroll_punchsite_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS payroll_punchsite_guard ON payroll_punchsite;
DROP FUNCTION IF EXISTS payroll_punchsite_guard();
DROP TRIGGER IF EXISTS payroll_punch_insert_only ON payroll_punch;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0012_staff_credits"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="phone_clock",
            field=models.CharField(
                choices=[
                    ("off", "Not used"),
                    ("anywhere", "From anywhere"),
                    ("sites", "Only at a site"),
                ],
                default="off",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="location_consent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="attendanceimport",
            name="kind",
            field=models.CharField(
                choices=[("sheet", "Excel sheet"), ("punches", "Phone punches")],
                default="sheet",
                max_length=10,
            ),
        ),
        migrations.CreateModel(
            name="PunchSite",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=100, unique=True)),
                ("latitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("longitude", models.DecimalField(decimal_places=6, max_digits=9)),
                ("radius_m", models.PositiveIntegerField(default=200)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            latitude__gte=-90,
                            latitude__lte=90,
                            longitude__gte=-180,
                            longitude__lte=180,
                        ),
                        name="payroll_punchsite_point",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(radius_m__gte=20, radius_m__lte=5000),
                        name="payroll_punchsite_radius",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Punch",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("kind", models.CharField(choices=[("in", "In"), ("out", "Out")], max_length=3)),
                ("at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "latitude",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
                ),
                (
                    "longitude",
                    models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True),
                ),
                ("accuracy_m", models.PositiveIntegerField(blank=True, null=True)),
                ("distance_m", models.PositiveIntegerField(blank=True, null=True)),
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
                        related_name="punches",
                        to="payroll.employee",
                    ),
                ),
                (
                    "site",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="punches",
                        to="payroll.punchsite",
                    ),
                ),
            ],
            options={
                "ordering": ["employee", "at"],
                "indexes": [models.Index(fields=["employee", "at"], name="payroll_punch_at")],
            },
        ),
        migrations.RunSQL(SQL, BACKWARD),
    ]
