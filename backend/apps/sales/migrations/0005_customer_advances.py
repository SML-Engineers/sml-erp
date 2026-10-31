import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Customer advances (backlog P15-09, spec 5.2).
# - Receipts have their own number series RC{YY}{MM}{NNNN}.
# - The Accountant's approval is enough (owner, 31 Oct 2026): the "customer_advance"
#   document type, level 2 = Accountant, in the approval matrix.
# - The database refuses deleting an advance, and changing a posted one other than its
#   set-off (Phase 2); a mistake is reversed in the journal (rules 2 and 3).

FORWARD = """
CREATE OR REPLACE FUNCTION sales_advance_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Advance % cannot be deleted', OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'awaiting_approval' AND (
       NEW.number IS DISTINCT FROM OLD.number
    OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
    OR NEW.quotation_id IS DISTINCT FROM OLD.quotation_id
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
    OR NEW.receipt_date IS DISTINCT FROM OLD.receipt_date
    OR NEW.account_id IS DISTINCT FROM OLD.account_id
    OR NEW.method IS DISTINCT FROM OLD.method
    OR NEW.reference IS DISTINCT FROM OLD.reference
    OR NEW.currency_id IS DISTINCT FROM OLD.currency_id
    OR NEW.amount IS DISTINCT FROM OLD.amount
    OR NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate
    OR NEW.amount_lkr IS DISTINCT FROM OLD.amount_lkr
    OR NEW.status IS DISTINCT FROM OLD.status
    OR NEW.journal_entry_id IS DISTINCT FROM OLD.journal_entry_id
  ) THEN
    RAISE EXCEPTION 'Advance % is % and cannot be changed', OLD.number, OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_advance_guard
BEFORE UPDATE OR DELETE ON sales_customeradvance
FOR EACH ROW EXECUTE FUNCTION sales_advance_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS sales_advance_guard ON sales_customeradvance;
DROP FUNCTION IF EXISTS sales_advance_guard();
"""

SERIES = ("customer_receipt", "Customer receipts", "RC{YY}{MM}{NNNN}", "monthly", "grow")


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
    accountant = Role.objects.filter(code="accountant").first()
    if accountant and not ApprovalRule.objects.filter(document_type="customer_advance").exists():
        ApprovalRule.objects.create(document_type="customer_advance", level=2, role=accountant)
    ApprovalReminder.objects.get_or_create(
        document_type="customer_advance", defaults={"enabled": True, "after_days": 3}
    )


def money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0004_taxes"),
        ("core", "0017_receipt_action"),
        ("masters", "0010_costing_rates"),
        ("sales", "0004_approval"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerAdvance",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("number", models.CharField(max_length=30, unique=True)),
                ("receipt_date", models.DateField()),
                (
                    "method",
                    models.CharField(
                        choices=[
                            ("transfer", "Bank transfer"),
                            ("cheque", "Cheque"),
                            ("cash", "Cash"),
                            ("card", "Card"),
                            ("qr", "QR (LankaQR)"),
                        ],
                        max_length=10,
                    ),
                ),
                ("reference", models.CharField(blank=True, max_length=50)),
                ("amount", money()),
                (
                    "exchange_rate",
                    models.DecimalField(decimal_places=6, default=1, max_digits=18),
                ),
                ("rate_date", models.DateField(blank=True, null=True)),
                ("amount_lkr", money(verbose_name="Amount (LKR)")),
                ("set_off_lkr", money(default=0, verbose_name="Set off (LKR)")),
                ("notes", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("awaiting_approval", "Awaiting approval"),
                            ("approved", "Approved and posted"),
                            ("rejected", "Rejected"),
                        ],
                        default="awaiting_approval",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="customer_advances",
                        to="masters.companyaccount",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "currency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="masters.currency",
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="advances",
                        to="masters.customer",
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
                (
                    "journal_entry",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="customer_advance",
                        to="accounting.journalentry",
                    ),
                ),
                (
                    "quotation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="advances",
                        to="sales.quotation",
                    ),
                ),
            ],
            options={
                "ordering": ["-receipt_date", "-number"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("amount__gt", 0),
                            ("amount_lkr__gt", 0),
                            ("exchange_rate__gt", 0),
                            ("set_off_lkr__gte", 0),
                            ("set_off_lkr__lte", models.F("amount_lkr")),
                        ),
                        name="sales_advance_amounts",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("status", "approved"), _negated=True),
                            ("journal_entry__isnull", False),
                            _connector="OR",
                        ),
                        name="sales_advance_posted_when_approved",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
