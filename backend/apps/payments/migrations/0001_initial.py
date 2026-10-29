import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Supplier payments and the payment lock (backlog P1-07, spec 4.6). The database refuses:
# - a payment for a voucher that is not Director Approved or Partly Paid, or whose
#   cancellation is waiting for the Director (the voucher row is locked first, so two
#   payments saved at the same moment are checked one after the other);
# - payments adding up to more than the approved amount;
# - changing or removing a payment;
# - deleting, cancelling or amending a voucher that has payments; changing a Paid voucher;
#   marking a voucher Paid when its payments do not add up to its total.

FORWARD = """
CREATE OR REPLACE FUNCTION payments_check_voucher() RETURNS trigger AS $$
DECLARE
  v_status TEXT;
  v_total NUMERIC;
  v_paid NUMERIC;
BEGIN
  SELECT status, total_amount INTO v_status, v_total
    FROM vouchers_voucher WHERE id = NEW.voucher_id FOR UPDATE;
  IF v_status IS NULL OR v_status NOT IN ('director_approved', 'partly_paid') THEN
    RAISE EXCEPTION 'Voucher % is not approved by the Director', NEW.voucher_id
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.cancelled THEN
    RAISE EXCEPTION 'A payment cannot be entered as cancelled'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF EXISTS (
    SELECT 1 FROM vouchers_vouchercancellation c
    WHERE c.voucher_id = NEW.voucher_id AND c.status = 'pending'
  ) THEN
    RAISE EXCEPTION 'A cancellation of voucher % is waiting for the Director', NEW.voucher_id
      USING ERRCODE = 'restrict_violation';
  END IF;
  SELECT COALESCE(SUM(amount), 0) INTO v_paid
    FROM payments_supplierpayment
   WHERE voucher_id = NEW.voucher_id AND NOT cancelled;
  IF v_paid + NEW.amount > v_total THEN
    RAISE EXCEPTION 'Payment exceeds the approved amount'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_payment_requires_approval
BEFORE INSERT ON payments_supplierpayment
FOR EACH ROW EXECUTE FUNCTION payments_check_voucher();

CREATE TRIGGER payments_supplierpayment_insert_only
BEFORE UPDATE OR DELETE ON payments_supplierpayment
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();

CREATE OR REPLACE FUNCTION vouchers_voucher_guard() RETURNS trigger AS $$
DECLARE
  v_paid NUMERIC;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Voucher % cannot be deleted from the database; it is marked Deleted',
      OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.number IS DISTINCT FROM OLD.number THEN
    RAISE EXCEPTION 'Voucher numbers never change (%)', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status = 'deleted' THEN
    RAISE EXCEPTION 'Voucher % is deleted and cannot change', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  SELECT COALESCE(SUM(amount), 0) INTO v_paid
    FROM payments_supplierpayment WHERE voucher_id = OLD.id AND NOT cancelled;
  IF NEW.status IN ('deleted', 'cancelled', 'amended')
     AND (OLD.status IN ('partly_paid', 'paid') OR v_paid > 0) THEN
    RAISE EXCEPTION 'Voucher % has payments and cannot be deleted or cancelled', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status = 'paid' AND NEW.status <> 'paid' THEN
    RAISE EXCEPTION 'Voucher % is paid and locked', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status = 'paid' AND v_paid <> NEW.total_amount THEN
    RAISE EXCEPTION 'Voucher % is not fully paid', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status = 'cancelled' AND NEW.status NOT IN ('cancelled', 'deleted') THEN
    RAISE EXCEPTION 'Voucher % is cancelled for good', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status IN ('director_approved', 'partly_paid', 'paid', 'amended', 'cancelled') AND (
       NEW.payee_id IS DISTINCT FROM OLD.payee_id
    OR NEW.transfer_to_id IS DISTINCT FROM OLD.transfer_to_id
    OR NEW.voucher_type_id IS DISTINCT FROM OLD.voucher_type_id
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
    OR NEW.description IS DISTINCT FROM OLD.description
    OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
  ) THEN
    RAISE EXCEPTION 'Voucher % is approved and cannot be edited; amend it instead', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

BACKWARD = """
DROP TRIGGER IF EXISTS payments_supplierpayment_insert_only ON payments_supplierpayment;
DROP TRIGGER IF EXISTS trg_payment_requires_approval ON payments_supplierpayment;
DROP FUNCTION IF EXISTS payments_check_voucher();
"""

SERIES = ("supplier_payment", "Supplier payments", "PY{YY}{MM}{NNNN}", "monthly", "grow")


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


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("vouchers", "0006_cancellation"),
        ("masters", "0008_company_account_ledger"),
        ("accounting", "0004_taxes"),
        ("core", "0014_approval_withdraw_send_down"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SupplierPayment",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("number", models.CharField(max_length=40, unique=True)),
                (
                    "method",
                    models.CharField(
                        choices=[
                            ("cheque", "Cheque"),
                            ("transfer", "Bank transfer"),
                            ("cash", "Cash"),
                            ("card", "Card"),
                            ("qr", "QR code (LankaQR)"),
                        ],
                        max_length=10,
                    ),
                ),
                ("reference", models.CharField(blank=True, max_length=50)),
                ("cheque_date", models.DateField(blank=True, null=True)),
                ("payment_date", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("notes", models.CharField(blank=True, max_length=300)),
                ("cancelled", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="supplier_payments",
                        to="masters.companyaccount",
                    ),
                ),
                (
                    "cheque",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payment",
                        to="masters.chequeleaf",
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
                    "journal_entry",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="supplier_payment",
                        to="accounting.journalentry",
                    ),
                ),
                (
                    "voucher",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payments",
                        to="vouchers.voucher",
                    ),
                ),
            ],
            options={
                "ordering": ["-payment_date", "-id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("amount__gt", 0)), name="payments_amount_positive"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("method", "cheque"), _negated=True),
                            ("cheque__isnull", False),
                            _connector="OR",
                        ),
                        name="payments_cheque_has_leaf",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(load_series, migrations.RunPython.noop),
    ]
