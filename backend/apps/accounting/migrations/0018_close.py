import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Month-end and year-end close (backlog P2-23).
# - Checklist ticks are insert-only.
# - A year-end close is never deleted; it changes only once, when the Director reopens the
#   year (the reopening fields filled in, nothing else changed).

FORWARD = """
CREATE TRIGGER accounting_monthendtick_insert_only
BEFORE UPDATE OR DELETE ON accounting_monthendtick
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();

CREATE OR REPLACE FUNCTION accounting_yearend_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A year-end close is never deleted; the Director reopens the year instead'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.reopened = false AND NEW.reopened = true
     AND NEW.year_start = OLD.year_start AND NEW.profit = OLD.profit
     AND NEW.journal_entry_id = OLD.journal_entry_id
     AND NEW.closed_by_id = OLD.closed_by_id AND NEW.closed_at = OLD.closed_at
     AND NEW.reopen_entry_id IS NOT NULL AND NEW.reopened_by_id IS NOT NULL
     AND length(trim(NEW.reopen_reason)) > 0 THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'A year-end close never changes, except when the year is reopened'
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_yearend_guard
BEFORE UPDATE OR DELETE ON accounting_yearendclose
FOR EACH ROW EXECUTE FUNCTION accounting_yearend_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS accounting_yearend_guard ON accounting_yearendclose;
DROP FUNCTION IF EXISTS accounting_yearend_guard();
DROP TRIGGER IF EXISTS accounting_monthendtick_insert_only ON accounting_monthendtick;
"""

ID = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")


def _user(**extra):
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to=settings.AUTH_USER_MODEL,
        **extra,
    )


def _entry(**extra):
    return models.OneToOneField(
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to="accounting.journalentry",
        **extra,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0017_budgets"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MonthEndTick",
            fields=[
                ("id", ID.clone()),
                ("month", models.DateField()),
                ("item", models.CharField(max_length=30)),
                ("note", models.CharField(max_length=300)),
                ("ticked_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("ticked_by", _user()),
            ],
            options={"ordering": ["month", "item", "-ticked_at"]},
        ),
        migrations.CreateModel(
            name="YearEndClose",
            fields=[
                ("id", ID.clone()),
                ("year_start", models.DateField()),
                ("profit", models.DecimalField(decimal_places=2, max_digits=18)),
                ("closed_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("reopened", models.BooleanField(default=False)),
                ("reopen_reason", models.CharField(blank=True, max_length=300)),
                ("reopened_at", models.DateTimeField(blank=True, null=True)),
                ("journal_entry", _entry()),
                ("reopen_entry", _entry(blank=True, null=True)),
                ("closed_by", _user()),
                ("reopened_by", _user(blank=True, null=True)),
            ],
            options={
                "ordering": ["-year_start", "-closed_at"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("reopened", False)),
                        fields=("year_start",),
                        name="accounting_yearend_once",
                    )
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
