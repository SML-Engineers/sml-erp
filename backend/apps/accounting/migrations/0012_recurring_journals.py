import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Recurring journals (backlog P2-02): a template makes a draft manual journal on its date;
# the draft is checked, sent and approved like any manual journal. An accrual can be set to
# reverse on the first day of the next month. Once a journal has left draft, its reversal date
# and its template never change (the manual journal guard now covers them too).

GUARD = """
CREATE OR REPLACE FUNCTION accounting_mj_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Manual journal % cannot be deleted', OLD.number
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status IN ('posted', 'rejected') THEN
    RAISE EXCEPTION 'Manual journal % is % for good', OLD.number, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.number IS DISTINCT FROM OLD.number OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
     OR NEW.recurring_id IS DISTINCT FROM OLD.recurring_id
  THEN
    RAISE EXCEPTION 'The number, author and template of manual journal % never change',
      OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'draft' AND (
       NEW.entry_date IS DISTINCT FROM OLD.entry_date
    OR NEW.narration IS DISTINCT FROM OLD.narration
    OR NEW.reverse_on IS DISTINCT FROM OLD.reverse_on
  ) THEN
    RAISE EXCEPTION 'Manual journal % has been sent for approval: it cannot be changed',
      OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status = 'posted' AND NEW.journal_entry_id IS NULL THEN
    RAISE EXCEPTION 'Manual journal % is posted only with its journal entry', OLD.number
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def fk(to, related_name="+", null=False):
    extra = {"blank": True, "null": True} if null else {}
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name=related_name, to=to, **extra
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0011_tax_rate_approval"),
        ("masters", "0011_limit_no_maximum"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RecurringJournal",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                ("narration", models.CharField(max_length=400)),
                (
                    "frequency",
                    models.CharField(
                        choices=[
                            ("monthly", "Every month"),
                            ("quarterly", "Every quarter"),
                            ("yearly", "Every year"),
                        ],
                        max_length=10,
                    ),
                ),
                ("day_of_month", models.PositiveSmallIntegerField()),
                ("start_date", models.DateField()),
                ("end_date", models.DateField(blank=True, null=True)),
                ("next_date", models.DateField()),
                ("reverse_next_month", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["name"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("day_of_month__gte", 1), ("day_of_month__lte", 28))
                        | models.Q(("day_of_month", 31)),
                        name="accounting_recurring_day",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="RecurringJournalLine",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("line_no", models.PositiveSmallIntegerField()),
                ("description", models.CharField(blank=True, max_length=500)),
                ("debit", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ("credit", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ("account", fk("accounting.account")),
                ("division", fk("core.division", null=True)),
                ("supplier", fk("masters.supplier", null=True)),
                (
                    "recurring",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="accounting.recurringjournal",
                    ),
                ),
            ],
            options={
                "ordering": ["recurring", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("recurring", "line_no"), name="accounting_recurring_line_no"
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="manualjournal",
            name="recurring",
            field=fk("accounting.recurringjournal", "journals", null=True),
        ),
        migrations.AddField(
            model_name="manualjournal",
            name="reverse_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunSQL(GUARD, migrations.RunSQL.noop),
    ]
