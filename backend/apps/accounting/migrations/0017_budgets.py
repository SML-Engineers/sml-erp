import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Budgets (backlog P2-22): a financial year's budget by account, division and month, approved
# by the Director ("budget" approval type, seeded here with its reminder).
# - A budget's lines change only while it is a draft.
# - A budget that is not a draft is never deleted; an approved one never changes, except to be
#   marked replaced when a later version is approved; a rejected or replaced one never changes.

FORWARD = """
CREATE OR REPLACE FUNCTION accounting_budget_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Budget % version % is % and is never deleted',
        OLD.year_start, OLD.version, OLD.status USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status = 'approved' AND NEW.status = 'replaced'
     AND NEW.year_start = OLD.year_start AND NEW.version = OLD.version
     AND NEW.notes IS NOT DISTINCT FROM OLD.notes
     AND NEW.approved_at IS NOT DISTINCT FROM OLD.approved_at THEN
    RETURN NEW;
  END IF;
  IF OLD.status IN ('approved', 'rejected', 'replaced') THEN
    RAISE EXCEPTION 'Budget % version % is % and never changes',
      OLD.year_start, OLD.version, OLD.status USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_budget_guard
BEFORE UPDATE OR DELETE ON accounting_budget
FOR EACH ROW EXECUTE FUNCTION accounting_budget_guard();

CREATE OR REPLACE FUNCTION accounting_budget_line_guard() RETURNS trigger AS $$
DECLARE
  budget_status text;
BEGIN
  SELECT status INTO budget_status FROM accounting_budget
    WHERE id = COALESCE(NEW.budget_id, OLD.budget_id);
  IF budget_status IS NOT NULL AND budget_status <> 'draft' THEN
    RAISE EXCEPTION 'The lines of a budget change only while it is a draft'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_budget_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON accounting_budgetline
FOR EACH ROW EXECUTE FUNCTION accounting_budget_line_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS accounting_budget_line_guard ON accounting_budgetline;
DROP FUNCTION IF EXISTS accounting_budget_line_guard();
DROP TRIGGER IF EXISTS accounting_budget_guard ON accounting_budget;
DROP FUNCTION IF EXISTS accounting_budget_guard();
"""


def seed(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    director = Role.objects.filter(code="director").first()
    if director and not ApprovalRule.objects.filter(document_type="budget").exists():
        ApprovalRule.objects.create(document_type="budget", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="budget", defaults={"enabled": True, "after_days": 2}
    )


ID = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0016_revaluation"),
        ("core", "0025_credit_terms_action"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Budget",
            fields=[
                ("id", ID.clone()),
                ("year_start", models.DateField()),
                ("version", models.PositiveSmallIntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("awaiting_approval", "Awaiting approval"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                            ("replaced", "Replaced by a later version"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("notes", models.CharField(blank=True, max_length=500)),
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
            ],
            options={
                "ordering": ["-year_start", "-version"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("year_start", "version"), name="accounting_budget_version_once"
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("status", "approved")),
                        fields=("year_start",),
                        name="accounting_budget_one_approved",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("status__in", ["draft", "awaiting_approval"])),
                        fields=("year_start",),
                        name="accounting_budget_one_open",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="BudgetLine",
            fields=[
                ("id", ID.clone()),
                ("month", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                (
                    "budget",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="accounting.budget",
                    ),
                ),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="accounting.account",
                    ),
                ),
                (
                    "division",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="core.division",
                    ),
                ),
            ],
            options={
                "ordering": ["budget", "account", "division", "month"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("budget", "account", "division", "month"),
                        name="accounting_budgetline_once",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("amount", 0), _negated=True),
                        name="accounting_budgetline_not_zero",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
