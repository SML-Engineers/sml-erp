import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Customer receipts and advance set-off (backlog P2-07).
# - Receipts share the RC{YY}{MM}{NNNN} series with customer advances ("customer_receipt").
# - Approved through the "customer_receipt" document type: level 2, the Accountant (like
#   advances: the Accountant's approval is enough).
# - The database refuses: deleting a receipt or changing what was recorded; status moves other
#   than awaiting approval -> post-dated / posted / rejected and post-dated -> posted; a posted
#   receipt without its journal entry; changing or deleting allocations and set-offs; paying an
#   invoice that is not issued or is another customer's; allocating or setting off more than
#   is open on an invoice (its total less approved credit notes, receipts not rejected and
#   set-offs); setting off more than is left of an advance (the advance's set-off total is
#   kept here, and its check constraint refuses going over).

FORWARD = """
CREATE OR REPLACE FUNCTION sales_invoice_open(invoice bigint) RETURNS numeric AS $$
  SELECT i.total_amount
    - COALESCE((SELECT SUM(n.total_amount) FROM sales_creditnote n
                WHERE n.invoice_id = i.id AND n.status = 'approved'), 0)
    - COALESCE((SELECT SUM(a.amount) FROM sales_receiptallocation a
                JOIN sales_customerreceipt r ON r.id = a.receipt_id
                WHERE a.invoice_id = i.id AND r.status <> 'rejected'), 0)
    - COALESCE((SELECT SUM(s.amount) FROM sales_advancesetoff s
                WHERE s.invoice_id = i.id), 0)
  FROM sales_taxinvoice i WHERE i.id = $1;
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION sales_receipt_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Receipt % cannot be deleted', OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.number IS DISTINCT FROM OLD.number
     OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
     OR NEW.receipt_date IS DISTINCT FROM OLD.receipt_date
     OR NEW.method IS DISTINCT FROM OLD.method
     OR NEW.account_id IS DISTINCT FROM OLD.account_id
     OR NEW.reference IS DISTINCT FROM OLD.reference
     OR NEW.cheque_date IS DISTINCT FROM OLD.cheque_date
     OR NEW.cheque_bank IS DISTINCT FROM OLD.cheque_bank
     OR NEW.amount IS DISTINCT FROM OLD.amount
     OR NEW.notes IS DISTINCT FROM OLD.notes
     OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Receipt % cannot be changed once recorded', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status IN ('posted', 'rejected') THEN
    RAISE EXCEPTION 'Receipt % is % for good', OLD.number, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
       (OLD.status = 'awaiting_approval' AND NEW.status IN ('post_dated', 'posted', 'rejected'))
    OR (OLD.status = 'post_dated' AND NEW.status = 'posted')
  ) THEN
    RAISE EXCEPTION 'Receipt % cannot go from % to %', OLD.number, OLD.status, NEW.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF (NEW.status = 'posted') <> (NEW.journal_entry_id IS NOT NULL) THEN
    RAISE EXCEPTION 'A receipt has a journal entry exactly when it is posted'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_receipt_guard
BEFORE UPDATE OR DELETE ON sales_customerreceipt
FOR EACH ROW EXECUTE FUNCTION sales_receipt_guard();

CREATE OR REPLACE FUNCTION sales_allocation_guard() RETURNS trigger AS $$
DECLARE
  rec record;
  inv record;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'What a receipt paid never changes' USING ERRCODE = 'restrict_violation';
  END IF;
  SELECT number, status, customer_id INTO rec FROM sales_customerreceipt WHERE id = NEW.receipt_id;
  IF rec.status <> 'awaiting_approval' THEN
    RAISE EXCEPTION 'Receipt % has been decided: nothing is added to it', rec.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  SELECT number, status, customer_id INTO inv FROM sales_taxinvoice
    WHERE id = NEW.invoice_id FOR UPDATE;
  IF inv.status <> 'issued' OR inv.customer_id <> rec.customer_id THEN
    RAISE EXCEPTION 'A receipt pays only issued invoices of its own customer'
      USING ERRCODE = 'check_violation';
  END IF;
  IF sales_invoice_open(NEW.invoice_id) < NEW.amount THEN
    RAISE EXCEPTION 'Receipt % pays more than is open on invoice %', rec.number, inv.number
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_allocation_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_receiptallocation
FOR EACH ROW EXECUTE FUNCTION sales_allocation_guard();

CREATE OR REPLACE FUNCTION sales_set_off_guard() RETURNS trigger AS $$
DECLARE
  adv record;
  inv record;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'An advance set-off never changes' USING ERRCODE = 'restrict_violation';
  END IF;
  SELECT number, status, customer_id INTO adv FROM sales_customeradvance
    WHERE id = NEW.advance_id FOR UPDATE;
  SELECT number, status, customer_id INTO inv FROM sales_taxinvoice
    WHERE id = NEW.invoice_id FOR UPDATE;
  IF adv.status <> 'approved' OR inv.status <> 'issued' OR inv.customer_id <> adv.customer_id THEN
    RAISE EXCEPTION 'An approved advance is set off only against an issued invoice of its customer'
      USING ERRCODE = 'check_violation';
  END IF;
  IF sales_invoice_open(NEW.invoice_id) < NEW.amount THEN
    RAISE EXCEPTION 'Advance % sets off more than is open on invoice %', adv.number, inv.number
      USING ERRCODE = 'check_violation';
  END IF;
  -- The advance's check constraint refuses setting off more than it holds.
  UPDATE sales_customeradvance SET set_off_lkr = set_off_lkr + NEW.amount
    WHERE id = NEW.advance_id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_set_off_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_advancesetoff
FOR EACH ROW EXECUTE FUNCTION sales_set_off_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS sales_set_off_guard ON sales_advancesetoff;
DROP FUNCTION IF EXISTS sales_set_off_guard();
DROP TRIGGER IF EXISTS sales_allocation_guard ON sales_receiptallocation;
DROP FUNCTION IF EXISTS sales_allocation_guard();
DROP TRIGGER IF EXISTS sales_receipt_guard ON sales_customerreceipt;
DROP FUNCTION IF EXISTS sales_receipt_guard();
DROP FUNCTION IF EXISTS sales_invoice_open(bigint);
"""


def seed(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    accountant = Role.objects.filter(code="accountant").first()
    if accountant and not ApprovalRule.objects.filter(document_type="customer_receipt").exists():
        ApprovalRule.objects.create(document_type="customer_receipt", level=2, role=accountant)
    ApprovalReminder.objects.get_or_create(
        document_type="customer_receipt", defaults={"enabled": True, "after_days": 1}
    )


def id_field():
    return (
        "id",
        models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
    )


def fk(to, related_name="+", null=False):
    extra = {"blank": True, "null": True} if null else {}
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name=related_name, to=to, **extra
    )


def money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


METHODS = [
    ("transfer", "Bank transfer"),
    ("cheque", "Cheque"),
    ("cash", "Cash"),
    ("card", "Card"),
    ("qr", "QR (LankaQR)"),
]


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0011_credit_notes"),
        ("accounting", "0013_line_customer"),
        ("masters", "0011_limit_no_maximum"),
        ("core", "0022_credit_note_action"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerReceipt",
            fields=[
                id_field(),
                ("number", models.CharField(max_length=30, unique=True)),
                ("receipt_date", models.DateField()),
                ("method", models.CharField(choices=METHODS, max_length=10)),
                ("reference", models.CharField(blank=True, max_length=50)),
                ("cheque_date", models.DateField(blank=True, null=True)),
                ("cheque_bank", models.CharField(blank=True, max_length=100)),
                ("amount", money()),
                ("notes", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("awaiting_approval", "Awaiting approval"),
                            ("post_dated", "Approved, cheque not yet due"),
                            ("posted", "Approved and posted"),
                            ("rejected", "Rejected"),
                        ],
                        default="awaiting_approval",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                ("customer", fk("masters.customer", "receipts")),
                ("account", fk("masters.companyaccount", "customer_receipts", null=True)),
                (
                    "journal_entry",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="customer_receipt",
                        to="accounting.journalentry",
                    ),
                ),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
                ("approved_by", fk(settings.AUTH_USER_MODEL, null=True)),
            ],
            options={
                "ordering": ["-receipt_date", "-number"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(amount__gt=0), name="sales_receipt_amount"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(method="cheque", cheque_date__isnull=False)
                        | (~models.Q(method="cheque") & models.Q(account__isnull=False)),
                        name="sales_receipt_account_or_cheque",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(status="posted")
                        | models.Q(journal_entry__isnull=False),
                        name="sales_receipt_posted_has_entry",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ReceiptAllocation",
            fields=[
                id_field(),
                ("amount", money()),
                ("receipt", fk("sales.customerreceipt", "allocations")),
                ("invoice", fk("sales.taxinvoice", "receipt_allocations")),
            ],
            options={
                "ordering": ["receipt", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("receipt", "invoice"), name="sales_allocation_once"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(amount__gt=0), name="sales_allocation_amount"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="AdvanceSetOff",
            fields=[
                id_field(),
                ("amount", money()),
                ("set_off_date", models.DateField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("advance", fk("sales.customeradvance", "set_offs")),
                ("invoice", fk("sales.taxinvoice", "set_offs")),
                ("journal_entry", fk("accounting.journalentry", "advance_set_offs")),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["set_off_date", "id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(amount__gt=0), name="sales_set_off_amount"
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
