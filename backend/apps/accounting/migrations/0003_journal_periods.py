import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Journal and accounting periods (backlog P0-16, spec 3). The database itself refuses:
# - a journal entry whose debits and credits differ, or with fewer than two lines (checked
#   when the saving transaction commits, so an entry and its lines are saved together);
# - changing or deleting a posted entry or line (rule 3: corrections are reversing entries);
# - posting into a closed month;
# - a line on an inactive or merged account, or an income or expense line with no division;
# - changing the type of an account with entries in a closed month (guard v2).

PNL_TYPES = "'income','other_income','cost_of_goods_sold','expense','other_expense'"

FORWARD = f"""
CREATE TRIGGER accounting_journalentry_insert_only
BEFORE UPDATE OR DELETE ON accounting_journalentry
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();

CREATE TRIGGER accounting_journalline_insert_only
BEFORE UPDATE OR DELETE ON accounting_journalline
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();

CREATE OR REPLACE FUNCTION accounting_entry_balanced() RETURNS trigger AS $$
DECLARE
  entry_id bigint;
  lines integer;
  debits numeric;
  credits numeric;
BEGIN
  entry_id := CASE WHEN TG_TABLE_NAME = 'accounting_journalentry' THEN NEW.id ELSE NEW.entry_id END;
  SELECT count(*), coalesce(sum(debit), 0), coalesce(sum(credit), 0)
    INTO lines, debits, credits
    FROM accounting_journalline WHERE accounting_journalline.entry_id = entry_id;
  IF lines < 2 THEN
    RAISE EXCEPTION 'Journal entry % needs at least two lines', entry_id
      USING ERRCODE = 'check_violation';
  END IF;
  IF debits <> credits THEN
    RAISE EXCEPTION 'Journal entry % does not balance: debits % and credits %',
      entry_id, debits, credits USING ERRCODE = 'check_violation';
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER accounting_journalentry_balanced
AFTER INSERT ON accounting_journalentry
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting_entry_balanced();

CREATE CONSTRAINT TRIGGER accounting_journalline_balanced
AFTER INSERT ON accounting_journalline
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting_entry_balanced();

CREATE OR REPLACE FUNCTION accounting_entry_open_period() RETURNS trigger AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM accounting_accountingperiod
    WHERE month = date_trunc('month', NEW.entry_date)::date AND is_closed
  ) THEN
    RAISE EXCEPTION 'The period % is closed: nothing can be posted into it',
      to_char(NEW.entry_date, 'YYYY-MM') USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_journalentry_open_period
BEFORE INSERT ON accounting_journalentry
FOR EACH ROW EXECUTE FUNCTION accounting_entry_open_period();

CREATE OR REPLACE FUNCTION accounting_line_check() RETURNS trigger AS $$
DECLARE
  acc accounting_account%ROWTYPE;
BEGIN
  SELECT * INTO acc FROM accounting_account WHERE id = NEW.account_id;
  IF NOT acc.is_active OR acc.merged_into_id IS NOT NULL THEN
    RAISE EXCEPTION 'Account % is inactive or merged: nothing can be posted to it', acc.name
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF acc.account_type IN ({PNL_TYPES}) AND NEW.division_id IS NULL THEN
    RAISE EXCEPTION 'A line on income or expense account % needs a division', acc.name
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_journalline_check
BEFORE INSERT ON accounting_journalline
FOR EACH ROW EXECUTE FUNCTION accounting_line_check();

CREATE OR REPLACE FUNCTION accounting_account_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.first_used_at IS NOT NULL THEN
      RAISE EXCEPTION 'Account % has been used: it cannot be deleted, only made inactive',
        OLD.name USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.system_role <> '' THEN
      RAISE EXCEPTION 'Account % is needed by the system and cannot be deleted', OLD.name
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.first_used_at IS NOT NULL THEN
    IF NEW.first_used_at IS DISTINCT FROM OLD.first_used_at THEN
      RAISE EXCEPTION 'Account %: the date it was first used cannot change', OLD.name
        USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.number <> '' AND NEW.number IS DISTINCT FROM OLD.number THEN
      RAISE EXCEPTION 'Account % has been used: its number cannot change', OLD.number
        USING ERRCODE = 'restrict_violation';
    END IF;
  END IF;
  IF NEW.system_role IS DISTINCT FROM OLD.system_role THEN
    RAISE EXCEPTION 'The system role of account % cannot change', OLD.name
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.system_role <> '' AND (NOT NEW.is_active OR NEW.account_type <> OLD.account_type) THEN
    RAISE EXCEPTION 'Account % is needed by the system: it stays active and keeps its type',
      OLD.name USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.merged_into_id IS NOT NULL AND (
      NEW.merged_into_id IS DISTINCT FROM OLD.merged_into_id
      OR NEW.merged_at IS DISTINCT FROM OLD.merged_at
      OR NEW.is_active) THEN
    RAISE EXCEPTION 'Account % was merged; a merge cannot be undone', OLD.name
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.account_type <> OLD.account_type AND EXISTS (
      SELECT 1 FROM accounting_journalline l
      JOIN accounting_journalentry e ON e.id = l.entry_id
      JOIN accounting_accountingperiod p
        ON p.month = date_trunc('month', e.entry_date)::date AND p.is_closed
      WHERE l.account_id = OLD.id) THEN
    RAISE EXCEPTION 'Account % has entries in a closed period: its type cannot change',
      OLD.name USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

BACKWARD = """
DROP TRIGGER IF EXISTS accounting_journalline_check ON accounting_journalline;
DROP FUNCTION IF EXISTS accounting_line_check();
DROP TRIGGER IF EXISTS accounting_journalentry_open_period ON accounting_journalentry;
DROP FUNCTION IF EXISTS accounting_entry_open_period();
DROP TRIGGER IF EXISTS accounting_journalline_balanced ON accounting_journalline;
DROP TRIGGER IF EXISTS accounting_journalentry_balanced ON accounting_journalentry;
DROP FUNCTION IF EXISTS accounting_entry_balanced();
DROP TRIGGER IF EXISTS accounting_journalline_insert_only ON accounting_journalline;
DROP TRIGGER IF EXISTS accounting_journalentry_insert_only ON accounting_journalentry;
"""

# Journal entry numbers: JV, year, month and a running number that restarts each month.
SERIES = ("journal", "Journal entries", "JV{YY}{MM}{NNNN}", "monthly", "grow")


def load_series(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    document_type, name, number_format, reset, when_full = SERIES
    NumberSeries.objects.get_or_create(
        document_type=document_type,
        defaults={
            "name": name,
            "format": number_format,
            "reset_period": reset,
            "when_full": when_full,
        },
    )


def big_id():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0002_starter_chart"),
        ("core", "0010_invoice_numbering"),
        ("masters", "0008_company_account_ledger"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountingPeriod",
            fields=[
                ("id", big_id()),
                ("month", models.DateField(unique=True)),
                ("is_closed", models.BooleanField(default=False)),
                ("changed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["month"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("month__day", 1)),
                        name="accounting_period_first_of_month",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="JournalEntry",
            fields=[
                ("id", big_id()),
                ("number", models.CharField(max_length=40, unique=True)),
                ("entry_date", models.DateField()),
                ("source_type", models.CharField(max_length=30)),
                ("source_id", models.CharField(blank=True, max_length=40)),
                ("narration", models.CharField(max_length=500)),
                ("posted_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "posted_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "reversal_of",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reversed_by",
                        to="accounting.journalentry",
                    ),
                ),
            ],
            options={
                "ordering": ["-entry_date", "-id"],
                "verbose_name_plural": "journal entries",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("reversal_of", models.F("id")), _negated=True),
                        name="accounting_entry_not_own_reversal",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="JournalLine",
            fields=[
                ("id", big_id()),
                ("line_no", models.PositiveSmallIntegerField()),
                ("description", models.CharField(blank=True, max_length=500)),
                ("debit", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ("credit", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="journal_lines",
                        to="accounting.account",
                    ),
                ),
                (
                    "division",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="journal_lines",
                        to="core.division",
                    ),
                ),
                (
                    "entry",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lines",
                        to="accounting.journalentry",
                    ),
                ),
                (
                    "supplier",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="journal_lines",
                        to="masters.supplier",
                    ),
                ),
            ],
            options={
                "ordering": ["entry", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("entry", "line_no"), name="accounting_line_unique_no"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("debit__gt", 0), ("credit", 0)),
                            models.Q(("debit", 0), ("credit__gt", 0)),
                            _connector="OR",
                        ),
                        name="accounting_line_one_side_positive",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(load_series, migrations.RunPython.noop),
    ]
