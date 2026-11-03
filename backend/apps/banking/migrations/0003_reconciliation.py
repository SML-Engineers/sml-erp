import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Bank reconciliation (backlog P2-16). Statement lines are matched to journal entries; a
# reconciled month is locked: its matches and statement lines can no longer be added, removed
# or changed (database guard), and a reconciliation itself never changes.

FORWARD = """
CREATE OR REPLACE FUNCTION banking_locked(p_account bigint, p_day date) RETURNS boolean AS $$
  SELECT EXISTS (
    SELECT 1 FROM banking_bankreconciliation r
    WHERE r.account_id = p_account AND r.period_end >= p_day
  );
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION banking_match_guard() RETURNS trigger AS $$
DECLARE
  l record;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION 'A statement match never changes; remove it and match again'
      USING ERRCODE = 'restrict_violation';
  END IF;
  SELECT account_id, date INTO l FROM banking_bankstatementline
    WHERE id = COALESCE(NEW.line_id, OLD.line_id);
  IF banking_locked(l.account_id, l.date) THEN
    RAISE EXCEPTION 'The bank account is reconciled to % or later; its matches are locked', l.date
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER banking_match_guard
BEFORE INSERT OR UPDATE OR DELETE ON banking_statementmatch
FOR EACH ROW EXECUTE FUNCTION banking_match_guard();

CREATE OR REPLACE FUNCTION banking_line_lock() RETURNS trigger AS $$
BEGIN
  IF banking_locked(OLD.account_id, OLD.date) THEN
    RAISE EXCEPTION 'The bank account is reconciled to % or later; its statement stays', OLD.date
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER banking_line_lock
BEFORE DELETE ON banking_bankstatementline
FOR EACH ROW EXECUTE FUNCTION banking_line_lock();

CREATE TRIGGER banking_reconciliation_insert_only
BEFORE UPDATE OR DELETE ON banking_bankreconciliation
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS banking_reconciliation_insert_only ON banking_bankreconciliation;
DROP TRIGGER IF EXISTS banking_line_lock ON banking_bankstatementline;
DROP FUNCTION IF EXISTS banking_line_lock();
DROP TRIGGER IF EXISTS banking_match_guard ON banking_statementmatch;
DROP FUNCTION IF EXISTS banking_match_guard();
DROP FUNCTION IF EXISTS banking_locked(bigint, date);
"""

ID = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")


def fk(to, null=False, related_name="+"):
    return models.ForeignKey(
        blank=null,
        null=null,
        on_delete=django.db.models.deletion.PROTECT,
        related_name=related_name,
        to=to,
    )


def money():
    return models.DecimalField(decimal_places=2, max_digits=18)


class Migration(migrations.Migration):
    dependencies = [
        ("banking", "0002_bank_statements"),
        ("accounting", "0014_zero_rated_code"),
        ("core", "0025_credit_terms_action"),
        ("masters", "0011_limit_no_maximum"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StatementMatch",
            fields=[
                ("id", ID.clone()),
                ("posted", models.BooleanField(default=False)),
                ("matched_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "line",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="match",
                        to="banking.bankstatementline",
                    ),
                ),
                (
                    "entry",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="statement_match",
                        to="accounting.journalentry",
                    ),
                ),
                ("matched_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["line"]},
        ),
        migrations.CreateModel(
            name="BankRule",
            fields=[
                ("id", ID.clone()),
                ("text", models.CharField(max_length=100)),
                (
                    "direction",
                    models.CharField(
                        choices=[
                            ("any", "Money in or out"),
                            ("out", "Money out"),
                            ("in", "Money in"),
                        ],
                        default="any",
                        max_length=3,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("account", fk("masters.companyaccount", null=True, related_name="bank_rules")),
                ("ledger", fk("accounting.account")),
                ("division", fk("core.division", null=True)),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["text"]},
        ),
        migrations.CreateModel(
            name="BankReconciliation",
            fields=[
                ("id", ID.clone()),
                ("period_end", models.DateField()),
                ("bank_balance", money()),
                ("book_balance", money()),
                ("unpresented", money()),
                ("note", models.TextField(blank=True)),
                ("done_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("account", fk("masters.companyaccount", related_name="reconciliations")),
                ("done_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-period_end", "-id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("account", "period_end"), name="banking_reconciliation_once"
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
