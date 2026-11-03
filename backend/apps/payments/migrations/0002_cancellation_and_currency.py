import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Payment follow-ups (backlog P2-11).
# - Payments carry the currency of the account paid from, what left it and the rate. Existing
#   payments were all in LKR: base currency, rate 1, paid amount = amount (their insert-only
#   guard is paused only for this one-time fill).
# - Payments stay insert-only except one change: "cancelled" set once, when the Director has
#   approved a cancellation of that payment. Nothing else on a payment ever changes.
# - A cheque leaf stays insert-only except: issued -> spoiled, once its payment is cancelled.
# - A paid voucher stays locked, except that it opens again (approved or partly paid) when a
#   cancelled payment leaves part of it unpaid.
# - Cancellation requests: decided ones never change; none is deleted.

FILL = """
SET CONSTRAINTS ALL IMMEDIATE;
ALTER TABLE payments_supplierpayment DISABLE TRIGGER payments_supplierpayment_insert_only;
UPDATE payments_supplierpayment
  SET currency_id = (SELECT id FROM masters_currency WHERE is_base ORDER BY id LIMIT 1),
      paid_amount = amount, exchange_rate = 1;
ALTER TABLE payments_supplierpayment ENABLE TRIGGER payments_supplierpayment_insert_only;
SET CONSTRAINTS ALL DEFERRED;
"""

GUARDS = """
DROP TRIGGER IF EXISTS payments_supplierpayment_insert_only ON payments_supplierpayment;

CREATE OR REPLACE FUNCTION payments_payment_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Payment % is never deleted', OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.cancelled OR NOT NEW.cancelled
     OR NEW.number IS DISTINCT FROM OLD.number
     OR NEW.voucher_id IS DISTINCT FROM OLD.voucher_id
     OR NEW.account_id IS DISTINCT FROM OLD.account_id
     OR NEW.method IS DISTINCT FROM OLD.method
     OR NEW.reference IS DISTINCT FROM OLD.reference
     OR NEW.cheque_id IS DISTINCT FROM OLD.cheque_id
     OR NEW.cheque_date IS DISTINCT FROM OLD.cheque_date
     OR NEW.payment_date IS DISTINCT FROM OLD.payment_date
     OR NEW.amount IS DISTINCT FROM OLD.amount
     OR NEW.currency_id IS DISTINCT FROM OLD.currency_id
     OR NEW.paid_amount IS DISTINCT FROM OLD.paid_amount
     OR NEW.exchange_rate IS DISTINCT FROM OLD.exchange_rate
     OR NEW.notes IS DISTINCT FROM OLD.notes
     OR NEW.journal_entry_id IS DISTINCT FROM OLD.journal_entry_id
     OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Payment % never changes; it is only cancelled, with the Director''s approval',
      OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM payments_paymentcancellation c
    WHERE c.payment_id = OLD.id AND c.status = 'approved' AND c.reversal_entry_id IS NOT NULL
  ) THEN
    RAISE EXCEPTION 'Payment % is cancelled only once the Director approves it', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payments_payment_guard
BEFORE UPDATE OR DELETE ON payments_supplierpayment
FOR EACH ROW EXECUTE FUNCTION payments_payment_guard();

DROP TRIGGER IF EXISTS masters_chequeleaf_insert_only ON masters_chequeleaf;

CREATE OR REPLACE FUNCTION masters_chequeleaf_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A used cheque number is kept for good' USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'issued' OR NEW.status <> 'spoiled'
     OR NEW.book_id IS DISTINCT FROM OLD.book_id
     OR NEW.account_id IS DISTINCT FROM OLD.account_id
     OR NEW.number IS DISTINCT FROM OLD.number
     OR NEW.used_by_id IS DISTINCT FROM OLD.used_by_id
     OR NEW.used_at IS DISTINCT FROM OLD.used_at
     OR NOT EXISTS (
       SELECT 1 FROM payments_supplierpayment p WHERE p.cheque_id = OLD.id AND p.cancelled
     ) THEN
    RAISE EXCEPTION 'Cheque % is kept as it is; an issued cheque is spoiled only when its payment is cancelled',
      OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER masters_chequeleaf_guard
BEFORE UPDATE OR DELETE ON masters_chequeleaf
FOR EACH ROW EXECUTE FUNCTION masters_chequeleaf_guard();

CREATE OR REPLACE FUNCTION payments_cancellation_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A payment cancellation request is never deleted'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status <> 'pending'
     OR NEW.payment_id IS DISTINCT FROM OLD.payment_id
     OR NEW.reason IS DISTINCT FROM OLD.reason
     OR NEW.requested_by_id IS DISTINCT FROM OLD.requested_by_id THEN
    RAISE EXCEPTION 'Payment cancellation % has been decided and never changes', OLD.id
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payments_cancellation_guard
BEFORE UPDATE OR DELETE ON payments_paymentcancellation
FOR EACH ROW EXECUTE FUNCTION payments_cancellation_guard();

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
  -- A paid voucher is locked, unless a payment on it was cancelled with the Director's
  -- approval (P2-11): it then opens to pay what is left again.
  IF OLD.status = 'paid' AND NEW.status <> 'paid' AND NOT (
       NEW.status IN ('director_approved', 'partly_paid') AND v_paid < OLD.total_amount
  ) THEN
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
DROP TRIGGER IF EXISTS payments_cancellation_guard ON payments_paymentcancellation;
DROP FUNCTION IF EXISTS payments_cancellation_guard();
DROP TRIGGER IF EXISTS masters_chequeleaf_guard ON masters_chequeleaf;
DROP FUNCTION IF EXISTS masters_chequeleaf_guard();
CREATE TRIGGER masters_chequeleaf_insert_only
BEFORE UPDATE OR DELETE ON masters_chequeleaf
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();
DROP TRIGGER IF EXISTS payments_payment_guard ON payments_supplierpayment;
DROP FUNCTION IF EXISTS payments_payment_guard();
CREATE TRIGGER payments_supplierpayment_insert_only
BEFORE UPDATE OR DELETE ON payments_supplierpayment
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();
"""


def seed(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    director = Role.objects.filter(code="director").first()
    if director and not ApprovalRule.objects.filter(document_type="payment_cancellation").exists():
        ApprovalRule.objects.create(document_type="payment_cancellation", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="payment_cancellation", defaults={"enabled": True, "after_days": 1}
    )


def currency(null):
    return models.ForeignKey(
        null=null,
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to="masters.currency",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0001_initial"),
        ("masters", "0011_limit_no_maximum"),
        ("accounting", "0014_zero_rated_code"),
        ("core", "0025_credit_terms_action"),
        ("vouchers", "0010_advance_payments"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField("supplierpayment", "currency", currency(null=True)),
        migrations.AddField(
            "supplierpayment",
            "paid_amount",
            models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AddField(
            "supplierpayment",
            "exchange_rate",
            models.DecimalField(decimal_places=6, default=1, max_digits=18),
        ),
        migrations.CreateModel(
            name="PaymentCancellation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("reason", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Waiting for the Director"),
                            ("approved", "Approved: payment cancelled"),
                            ("rejected", "Rejected"),
                        ],
                        default="pending",
                        max_length=10,
                    ),
                ),
                ("requested_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                (
                    "payment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="cancellations",
                        to="payments.supplierpayment",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "decided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "reversal_entry",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payment_cancellation",
                        to="accounting.journalentry",
                    ),
                ),
            ],
            options={
                "ordering": ["-requested_at", "-id"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(status__in=["pending", "approved"]),
                        fields=("payment",),
                        name="payments_one_open_cancellation",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(status="approved")
                        | models.Q(reversal_entry__isnull=False),
                        name="payments_cancellation_reversed",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FILL, migrations.RunSQL.noop),
        migrations.AlterField("supplierpayment", "currency", currency(null=False)),
        migrations.RunSQL(GUARDS, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
