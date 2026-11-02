import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Manual journals (backlog P2-01, spec 6 and 4.6).
# - Numbered MJ{YY}{MM}{DD}{XX}; approved through the "manual_journal" document type (the
#   Director, level 2), then posted as an ordinary journal entry.
# - Once sent for approval a journal never changes (its lines and files neither); posted and
#   rejected journals stay that way for good; only a draft is deleted.
# - The payment lock reaches the ledger itself: an entry that debits accounts payable and
#   credits a bank or cash account is refused unless it is a supplier payment, so a supplier
#   is never paid around the voucher and its Director approval (spec 4.6).

SERIES = ("manual_journal", "Manual journals", "MJ{YY}{MM}{DD}{XX}", "daily", "grow")


def seed(apps, schema_editor):
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
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    director = Role.objects.filter(code="director").first()
    if director and not ApprovalRule.objects.filter(document_type="manual_journal").exists():
        ApprovalRule.objects.create(document_type="manual_journal", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="manual_journal", defaults={"enabled": True, "after_days": 2}
    )


FORWARD = """
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
  THEN
    RAISE EXCEPTION 'The number and author of manual journal % never change', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'draft' AND (
       NEW.entry_date IS DISTINCT FROM OLD.entry_date
    OR NEW.narration IS DISTINCT FROM OLD.narration
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

CREATE TRIGGER accounting_mj_guard
BEFORE UPDATE OR DELETE ON accounting_manualjournal
FOR EACH ROW EXECUTE FUNCTION accounting_mj_guard();

-- Lines and files change only while their journal is a draft.
CREATE OR REPLACE FUNCTION accounting_mj_child_guard() RETURNS trigger AS $$
DECLARE
  parent_id bigint;
  parent_status text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    parent_id := OLD.journal_id;
  ELSE
    parent_id := NEW.journal_id;
  END IF;
  SELECT status INTO parent_status FROM accounting_manualjournal WHERE id = parent_id;
  IF parent_status IS NOT NULL AND parent_status <> 'draft' THEN
    RAISE EXCEPTION 'Manual journal % has been sent for approval: it cannot be changed',
      parent_id USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_mj_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON accounting_manualjournalline
FOR EACH ROW EXECUTE FUNCTION accounting_mj_child_guard();

CREATE TRIGGER accounting_mj_attachment_guard
BEFORE INSERT OR UPDATE OR DELETE ON accounting_manualjournalattachment
FOR EACH ROW EXECUTE FUNCTION accounting_mj_child_guard();

-- The payment lock in the ledger (spec 4.6).
CREATE OR REPLACE FUNCTION accounting_payment_lock() RETURNS trigger AS $$
DECLARE
  source text;
BEGIN
  SELECT e.source_type INTO source FROM accounting_journalentry e WHERE e.id = NEW.entry_id;
  IF source = 'supplier_payment' THEN
    RETURN NULL;
  END IF;
  IF EXISTS (
       SELECT 1 FROM accounting_journalline l
       JOIN accounting_account a ON a.id = l.account_id
       WHERE l.entry_id = NEW.entry_id AND l.debit > 0 AND a.account_type = 'accounts_payable'
     )
     AND EXISTS (
       SELECT 1 FROM accounting_journalline l
       JOIN accounting_account a ON a.id = l.account_id
       WHERE l.entry_id = NEW.entry_id AND l.credit > 0 AND a.account_type = 'bank'
     )
  THEN
    RAISE EXCEPTION 'Journal entry % pays a supplier from a bank or cash account: suppliers are paid only through an approved voucher',
      NEW.entry_id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER accounting_journalline_payment_lock
AFTER INSERT ON accounting_journalline
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION accounting_payment_lock();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS accounting_journalline_payment_lock ON accounting_journalline;
DROP FUNCTION IF EXISTS accounting_payment_lock();
DROP TRIGGER IF EXISTS accounting_mj_attachment_guard ON accounting_manualjournalattachment;
DROP TRIGGER IF EXISTS accounting_mj_line_guard ON accounting_manualjournalline;
DROP FUNCTION IF EXISTS accounting_mj_child_guard();
DROP TRIGGER IF EXISTS accounting_mj_guard ON accounting_manualjournal;
DROP FUNCTION IF EXISTS accounting_mj_guard();
"""


def id_field():
    return (
        "id",
        models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
    )


def money():
    return models.DecimalField(decimal_places=2, default=0, max_digits=18)


def fk(to, related_name="+", null=False):
    extra = {"blank": True, "null": True} if null else {}
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name=related_name, to=to, **extra
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0007_supplier_advances_role"),
        ("core", "0019_purchasing_roles"),
        ("masters", "0010_costing_rates"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ManualJournal",
            fields=[
                id_field(),
                ("number", models.CharField(max_length=30, unique=True)),
                ("entry_date", models.DateField()),
                ("narration", models.CharField(max_length=500)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("awaiting_approval", "Waiting for approval"),
                            ("posted", "Approved and posted"),
                            ("rejected", "Rejected"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "journal_entry",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="manual_journal",
                        to="accounting.journalentry",
                    ),
                ),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-entry_date", "-number"]},
        ),
        migrations.CreateModel(
            name="ManualJournalLine",
            fields=[
                id_field(),
                ("line_no", models.PositiveSmallIntegerField()),
                ("description", models.CharField(blank=True, max_length=500)),
                ("debit", money()),
                ("credit", money()),
                ("account", fk("accounting.account")),
                ("division", fk("core.division", null=True)),
                ("supplier", fk("masters.supplier", null=True)),
                (
                    "journal",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="accounting.manualjournal",
                    ),
                ),
            ],
            options={
                "ordering": ["journal", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("journal", "line_no"), name="accounting_mj_line_no"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("debit__gte", 0), ("credit__gte", 0)),
                        name="accounting_mj_line_not_negative",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ManualJournalAttachment",
            fields=[
                id_field(),
                ("file", models.FileField(upload_to="journals/%Y/%m/")),
                ("file_name", models.CharField(max_length=200)),
                ("content_type", models.CharField(max_length=100)),
                ("size", models.PositiveIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("uploaded_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("journal", fk("accounting.manualjournal", "attachments")),
                ("uploaded_by", fk(settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
