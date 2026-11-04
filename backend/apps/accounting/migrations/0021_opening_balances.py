import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Opening balances from QuickBooks (backlog P2-28): approved by the Director ("opening_balances",
# seeded with its reminder). A document sent for approval and its lines never change; only a
# draft is deleted.

FORWARD = """
CREATE OR REPLACE FUNCTION accounting_opening_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Opening balances that were sent for approval are never deleted'
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status IN ('posted', 'rejected') THEN
    RAISE EXCEPTION 'Opening balances that are % never change', OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_opening_guard
BEFORE UPDATE OR DELETE ON accounting_openingbalance
FOR EACH ROW EXECUTE FUNCTION accounting_opening_guard();

CREATE OR REPLACE FUNCTION accounting_opening_line_guard() RETURNS trigger AS $$
DECLARE
  doc_status text;
BEGIN
  SELECT status INTO doc_status FROM accounting_openingbalance
    WHERE id = COALESCE(NEW.opening_id, OLD.opening_id);
  IF doc_status IS NOT NULL AND doc_status <> 'draft' THEN
    RAISE EXCEPTION 'The lines of opening balances change only while they are a draft'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_opening_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON accounting_openingbalanceline
FOR EACH ROW EXECUTE FUNCTION accounting_opening_line_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS accounting_opening_line_guard ON accounting_openingbalanceline;
DROP FUNCTION IF EXISTS accounting_opening_line_guard();
DROP TRIGGER IF EXISTS accounting_opening_guard ON accounting_openingbalance;
DROP FUNCTION IF EXISTS accounting_opening_guard();
"""


def seed(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    director = Role.objects.filter(code="director").first()
    if director and not ApprovalRule.objects.filter(document_type="opening_balances").exists():
        ApprovalRule.objects.create(document_type="opening_balances", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="opening_balances", defaults={"enabled": True, "after_days": 1}
    )


ID = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")


def _fk(to, **extra):
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name="+", to=to, **extra
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0020_saved_reports"),
        ("masters", "0011_limit_no_maximum"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OpeningBalance",
            fields=[
                ("id", ID.clone()),
                ("as_at", models.DateField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("awaiting_approval", "Waiting for the Director"),
                            ("posted", "Approved and posted"),
                            ("rejected", "Rejected"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("report", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "journal_entry",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="accounting.journalentry",
                    ),
                ),
                ("created_by", _fk(settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("status", "posted")),
                        fields=("status",),
                        name="accounting_opening_posted_once",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="OpeningBalanceLine",
            fields=[
                ("id", ID.clone()),
                ("line_no", models.PositiveIntegerField()),
                ("description", models.CharField(blank=True, max_length=300)),
                ("debit", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ("credit", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                (
                    "opening",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="accounting.openingbalance",
                    ),
                ),
                ("account", _fk("accounting.account")),
                ("customer", _fk("masters.customer", blank=True, null=True)),
                ("supplier", _fk("masters.supplier", blank=True, null=True)),
            ],
            options={"ordering": ["opening", "line_no"]},
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
