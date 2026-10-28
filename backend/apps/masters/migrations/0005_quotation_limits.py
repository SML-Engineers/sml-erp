import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Quotation approval limits (backlog P0-12, spec 3A.3). The database refuses to change or
# delete a confirmed limit, and only lets a pending one move to confirmed, rejected or
# withdrawn.
FORWARD = """
CREATE OR REPLACE FUNCTION masters_quotationlimit_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Quotation limits are kept for good; they cannot be deleted'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'pending' THEN
    RAISE EXCEPTION 'A % quotation limit cannot be changed', OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.division_id IS DISTINCT FROM OLD.division_id
     OR NEW.min_margin_pct IS DISTINCT FROM OLD.min_margin_pct
     OR NEW.director_above_lkr IS DISTINCT FROM OLD.director_above_lkr
     OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id THEN
    RAISE EXCEPTION 'A quotation limit waiting for the Director cannot be edited; withdraw it and enter a new one'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER masters_quotationlimit_guard
BEFORE UPDATE OR DELETE ON masters_quotationlimit
FOR EACH ROW EXECUTE FUNCTION masters_quotationlimit_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS masters_quotationlimit_guard ON masters_quotationlimit;
DROP FUNCTION IF EXISTS masters_quotationlimit_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0004_currencies"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="QuotationLimit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("effective_from", models.DateField()),
                (
                    "min_margin_pct",
                    models.DecimalField(
                        decimal_places=2, max_digits=5, verbose_name="Minimum margin %"
                    ),
                ),
                (
                    "director_above_lkr",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=18,
                        verbose_name="Director approves above (LKR)",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Waiting for the Director"),
                            ("confirmed", "Confirmed"),
                            ("rejected", "Rejected"),
                            ("withdrawn", "Withdrawn"),
                        ],
                        default="pending",
                        max_length=10,
                    ),
                ),
                ("reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.TextField(blank=True)),
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
                    "division",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="quotation_limits",
                        to="core.division",
                    ),
                ),
            ],
            options={
                "ordering": ["division__code", "-effective_from", "-created_at"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("min_margin_pct__gte", 0), ("min_margin_pct__lt", 100)),
                        name="masters_limit_margin_range",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("director_above_lkr__gt", 0)),
                        name="masters_limit_value_positive",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("status", "confirmed")),
                        fields=("division", "effective_from"),
                        name="masters_limit_one_confirmed_per_day",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("status", "pending")),
                        fields=("division",),
                        name="masters_limit_one_pending",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
