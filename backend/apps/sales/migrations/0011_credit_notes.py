import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Credit notes (backlog P2-06).
# - Numbered CN{YY}{MM}{DD}{XX} when approved (the Admin can change the format in Settings ->
#   Number series), so drafts leave no gaps.
# - Approved through the "credit_note" document type: level 2, the Director (or a person given
#   the "approve_credit_notes" action, core migration 0022).
# - The database refuses: crediting more of an invoice line than was invoiced (amount and
#   quantity, all approved credit notes together, checked when a note is approved); changing a
#   note, its lines or taxes once sent for approval, or ever again once approved or rejected;
#   deleting anything but a draft; approving without the number and the journal entry.

SERIES = ("credit_note", "Credit notes", "CN{YY}{MM}{DD}{XX}", "daily", "grow")

FORWARD = """
CREATE OR REPLACE FUNCTION sales_cn_guard() RETURNS trigger AS $$
DECLARE
  over text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'Credit note % cannot be deleted', OLD.id
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status IN ('approved', 'rejected') THEN
    RAISE EXCEPTION 'Credit note % is % for good', COALESCE(NULLIF(OLD.number, ''), OLD.id::text),
      OLD.status USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.invoice_id IS DISTINCT FROM OLD.invoice_id
     OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id THEN
    RAISE EXCEPTION 'The invoice and author of a credit note never change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status = 'awaiting_approval' AND (
       NEW.kind IS DISTINCT FROM OLD.kind OR NEW.reason IS DISTINCT FROM OLD.reason
       OR NEW.credit_date IS DISTINCT FROM OLD.credit_date
       OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
  ) THEN
    RAISE EXCEPTION 'Credit note % has been sent for approval: it cannot be changed', OLD.id
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status = 'approved' AND (NEW.number = '' OR NEW.journal_entry_id IS NULL) THEN
    RAISE EXCEPTION 'A credit note is approved only with its number and its journal entry'
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status <> 'approved' AND NEW.number <> '' THEN
    RAISE EXCEPTION 'Only an approved credit note has a number' USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.status = 'approved' AND OLD.status <> 'approved' THEN
    SELECT string_agg(il.line_no::text, ', ') INTO over
    FROM sales_taxinvoiceline il
    WHERE il.id IN (SELECT invoice_line_id FROM sales_creditnoteline WHERE note_id = NEW.id)
      AND EXISTS (
        SELECT 1
        FROM sales_creditnoteline l
        JOIN sales_creditnote n ON n.id = l.note_id
        WHERE l.invoice_line_id = il.id AND (n.id = NEW.id OR n.status = 'approved')
        HAVING SUM(l.amount) > il.amount - il.discount OR SUM(l.quantity) > il.quantity
      );
    IF over IS NOT NULL THEN
      RAISE EXCEPTION 'Credit note % credits more than was invoiced on line %', NEW.number, over
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_cn_guard
BEFORE UPDATE OR DELETE ON sales_creditnote
FOR EACH ROW EXECUTE FUNCTION sales_cn_guard();

CREATE OR REPLACE FUNCTION sales_cn_child_guard() RETURNS trigger AS $$
DECLARE
  parent_id bigint;
  parent_status text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    parent_id := OLD.note_id;
  ELSE
    parent_id := NEW.note_id;
  END IF;
  SELECT status INTO parent_status FROM sales_creditnote WHERE id = parent_id;
  IF parent_status IS NOT NULL AND parent_status <> 'draft' THEN
    RAISE EXCEPTION 'Credit note % has been sent for approval: its lines never change',
      parent_id USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_cn_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_creditnoteline
FOR EACH ROW EXECUTE FUNCTION sales_cn_child_guard();

CREATE TRIGGER sales_cn_tax_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_creditnotetax
FOR EACH ROW EXECUTE FUNCTION sales_cn_child_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS sales_cn_tax_guard ON sales_creditnotetax;
DROP TRIGGER IF EXISTS sales_cn_line_guard ON sales_creditnoteline;
DROP FUNCTION IF EXISTS sales_cn_child_guard();
DROP TRIGGER IF EXISTS sales_cn_guard ON sales_creditnote;
DROP FUNCTION IF EXISTS sales_cn_guard();
"""


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
    if director and not ApprovalRule.objects.filter(document_type="credit_note").exists():
        ApprovalRule.objects.create(document_type="credit_note", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="credit_note", defaults={"enabled": True, "after_days": 1}
    )


def id_field():
    return (
        "id",
        models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
    )


def fk(to, related_name="+", null=False, on_delete=django.db.models.deletion.PROTECT):
    extra = {"blank": True, "null": True} if null else {}
    return models.ForeignKey(on_delete=on_delete, related_name=related_name, to=to, **extra)


def money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0010_tax_invoices"),
        ("core", "0022_credit_note_action"),
        ("accounting", "0013_line_customer"),
        ("masters", "0011_limit_no_maximum"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CreditNote",
            fields=[
                id_field(),
                ("number", models.CharField(blank=True, max_length=40)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("return", "Goods returned"),
                            ("price", "Price correction"),
                            ("other", "Other"),
                        ],
                        max_length=10,
                    ),
                ),
                ("reason", models.TextField()),
                ("credit_date", models.DateField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("awaiting_approval", "Waiting for approval"),
                            ("approved", "Approved and posted"),
                            ("rejected", "Rejected"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("subtotal", money(default=0)),
                ("tax_total", money(default=0)),
                ("total_amount", money(default=0)),
                ("amount_in_words", models.CharField(blank=True, max_length=400)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("invoice", fk("sales.taxinvoice", "credit_notes")),
                ("customer", fk("masters.customer", "credit_notes")),
                ("division", fk("core.division")),
                (
                    "journal_entry",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="credit_note",
                        to="accounting.journalentry",
                    ),
                ),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-credit_date", "-id"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("number", ""), _negated=True),
                        fields=("number",),
                        name="sales_credit_number_unique",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="CreditNoteLine",
            fields=[
                id_field(),
                ("quantity", models.DecimalField(decimal_places=3, default=0, max_digits=18)),
                ("amount", money()),
                ("tax_amount", money(default=0)),
                (
                    "note",
                    fk("sales.creditnote", "lines", on_delete=django.db.models.deletion.CASCADE),
                ),
                ("invoice_line", fk("sales.taxinvoiceline", "credits")),
            ],
            options={
                "ordering": ["note", "invoice_line__line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("note", "invoice_line"), name="sales_cn_line_once"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("amount__gt", 0), ("quantity__gte", 0)),
                        name="sales_cn_line_figures",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="CreditNoteTax",
            fields=[
                id_field(),
                ("seq", models.PositiveSmallIntegerField()),
                ("label", models.CharField(max_length=20)),
                ("rate", models.DecimalField(decimal_places=4, max_digits=7)),
                ("on_tax", models.BooleanField(default=False)),
                ("amount", money()),
                (
                    "note",
                    fk("sales.creditnote", "taxes", on_delete=django.db.models.deletion.CASCADE),
                ),
                ("component", fk("accounting.taxcomponent")),
            ],
            options={"ordering": ["note", "seq"]},
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
