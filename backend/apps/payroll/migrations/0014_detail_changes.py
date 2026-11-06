import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# P2B-20: employees ask to change their own details; HR decides.
# - Never deleted; once decided (approved, rejected, withdrawn) never changed.
SQL = """
CREATE OR REPLACE FUNCTION payroll_detailchange_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A request to change details is never deleted'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status <> 'waiting' THEN
    RAISE EXCEPTION 'A request to change details that is % never changes', OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.wanted IS DISTINCT FROM OLD.wanted OR NEW.before IS DISTINCT FROM OLD.before
     OR NEW.employee_id <> OLD.employee_id OR NEW.created_by_id <> OLD.created_by_id THEN
    RAISE EXCEPTION 'A request to change details is decided, never edited'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payroll_detailchange_guard
BEFORE UPDATE OR DELETE ON payroll_detailchange
FOR EACH ROW EXECUTE FUNCTION payroll_detailchange_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS payroll_detailchange_guard ON payroll_detailchange;
DROP FUNCTION IF EXISTS payroll_detailchange_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0013_punch_clock"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DetailChange",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("wanted", models.JSONField()),
                ("before", models.JSONField()),
                ("note", models.CharField(blank=True, max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("waiting", "Waiting for HR"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("withdrawn", "Withdrawn"),
                        ],
                        default="waiting",
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.CharField(blank=True, max_length=200)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "decided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="detail_changes",
                        to="payroll.employee",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.RunSQL(SQL, BACKWARD),
    ]
