from django.db import migrations, models

# Withholding tax on payments (backlog P2-12).
# - A payment records the WHT kept back from the payee and the number of the certificate
#   given for it (series "wht_certificate", WHT{YY}{MM}{NNNN}). Both never change (guard).
# - The WHT of an approved voucher is frozen with its total.
# - The payment lock is unchanged: payments still count the voucher amount they settle, WHT
#   included, and never more than the approved total.

FORWARD = r"""
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
     OR NEW.wht_amount IS DISTINCT FROM OLD.wht_amount
     OR NEW.wht_certificate IS DISTINCT FROM OLD.wht_certificate
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
    OR NEW.wht_total IS DISTINCT FROM OLD.wht_total
  ) THEN
    RAISE EXCEPTION 'Voucher % is approved and cannot be edited; amend it instead', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

BACKWARD = r"""
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

SERIES = ("wht_certificate", "WHT certificates", "WHT{YY}{MM}{NNNN}", "monthly", "grow")


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
    dependencies = [
        ("payments", "0002_cancellation_and_currency"),
        ("vouchers", "0011_withholding_tax"),
    ]

    operations = [
        migrations.AddField(
            model_name="supplierpayment",
            name="wht_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AddField(
            model_name="supplierpayment",
            name="wht_certificate",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddConstraint(
            model_name="supplierpayment",
            constraint=models.CheckConstraint(
                condition=models.Q(wht_amount__gte=0)
                & models.Q(wht_amount__lt=models.F("amount")),
                name="payments_wht_amount",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplierpayment",
            constraint=models.CheckConstraint(
                condition=models.Q(wht_amount=0) | ~models.Q(wht_certificate=""),
                name="payments_wht_certificate",
            ),
        ),
        migrations.AddConstraint(
            model_name="supplierpayment",
            constraint=models.UniqueConstraint(
                condition=~models.Q(wht_certificate=""),
                fields=("wht_certificate",),
                name="payments_wht_certificate_unique",
            ),
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(load_series, migrations.RunPython.noop),
    ]
