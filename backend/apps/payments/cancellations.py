"""Cancelling a supplier payment (backlog P2-11; spec 3: posted entries are corrected by
reversing entries).

- The Cashier or the Accountant asks, with the reason (a spoiled or wrongly written cheque, a
  cheque never sent, a failed transfer). One request at a time per payment.
- The Director approves every cancellation through the approval engine
  ("payment_cancellation"); nobody approves their own request (rule 5).
- Approval, in one transaction: the reversing entry of the payment (dated like it when its
  month is open, otherwise today), the payment marked cancelled, its cheque leaf marked spoiled
  (that number is never used again), and the voucher open to pay again (approved, or partly
  paid if other payments remain). The database allows these changes only with an approved
  request, and nothing else on the payment ever changes.
- Refused when the voucher paid an advance that has since been set off against a supplier's
  invoice: undo the set-off first (the Accountant, with a journal).
- A rejected request changes nothing; the reason is kept.
"""

from django.db import transaction
from django.utils import timezone

from apps.accounting import journal
from apps.accounting.services import AccountingError
from apps.core import approvals
from apps.core.access import effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User
from apps.masters.models import ChequeLeaf
from apps.vouchers.models import Voucher

from . import services
from .models import PaymentCancellation, SupplierPayment
from .services import PaymentError

DOC = "payment_cancellation"
St = PaymentCancellation.Status


def can_request(user: User) -> bool:
    access = effective_access(user)
    return access.can("record_payment") or access.has("accounting", "enter")


def can_decide(user: User, request: PaymentCancellation) -> bool:
    state = approvals.state_of(DOC, request.pk)
    return (
        request.status == St.PENDING
        and state is not None
        and approvals.why_not(user, state) is None
    )


def pending(payment: SupplierPayment) -> PaymentCancellation | None:
    return payment.cancellations.filter(status=St.PENDING).first()


def request(user: User, payment: SupplierPayment, reason: str) -> PaymentCancellation:
    if not can_request(user):
        raise PaymentError("The Cashier or the Accountant asks to cancel a payment.")
    reason = (reason or "").strip()
    if not reason:
        raise PaymentError("Give the reason for cancelling the payment.")
    with audit_context("payment_cancellation_requested", reason), transaction.atomic():
        payment = SupplierPayment.objects.select_for_update().get(pk=payment.pk)
        if payment.cancelled:
            raise PaymentError(f"Payment {payment.number} is already cancelled.")
        if pending(payment) is not None:
            raise PaymentError(f"A cancellation of payment {payment.number} is already waiting.")
        set_off = payment.voucher.lines.filter(
            advance_order__isnull=False, set_offs__isnull=False
        ).exists()
        if set_off:
            raise PaymentError(
                f"Voucher {payment.voucher.number} paid an advance that has been set off against "
                "a supplier's invoice; that set-off is undone first."
            )
        made = PaymentCancellation.objects.create(
            payment=payment, reason=reason[:2000], requested_by=user
        )
        try:
            approvals.submit(
                user,
                DOC,
                made.pk,
                created_by=user,
                amount=payment.amount,
                division=payment.voucher.division,
                title=f"Cancel payment {payment.number} of voucher {payment.voucher.number}",
                link=f"/vouchers/{payment.voucher_id}",
                comment=reason[:500],
            )
        except ApprovalError as error:
            raise PaymentError(str(error)) from None
        return made


def approve(user: User, cancellation: PaymentCancellation, comment: str = ""):
    """The Director approves: the payment is reversed and the voucher opens again."""
    with transaction.atomic():
        cancellation = PaymentCancellation.objects.select_for_update().get(pk=cancellation.pk)
        if cancellation.status != St.PENDING:
            raise PaymentError("The cancellation is not waiting for approval.")
        try:
            state = approvals.approve(user, DOC, cancellation.pk, comment)
        except ApprovalError as error:
            raise PaymentError(str(error)) from None
        if state.status != ApprovalState.Status.APPROVED:
            return cancellation
        with audit_context("supplier_payment_cancelled", cancellation.reason):
            payment = SupplierPayment.objects.select_for_update().get(pk=cancellation.payment_id)
            voucher = Voucher.objects.select_for_update().get(pk=payment.voucher_id)
            try:
                reversal = journal.reverse(
                    user,
                    payment.journal_entry,
                    reason=f"payment {payment.number} cancelled: {cancellation.reason}"[:400],
                )
            except AccountingError as error:
                raise PaymentError(str(error)) from None
            cancellation.status = St.APPROVED
            cancellation.decided_by = user
            cancellation.decided_at = timezone.now()
            cancellation.reversal_entry = reversal
            cancellation.save()
            payment.cancelled = True
            payment.save(update_fields=["cancelled"])
            if payment.cheque_id:
                leaf = ChequeLeaf.objects.select_for_update().get(pk=payment.cheque_id)
                leaf.status = ChequeLeaf.Status.SPOILED
                leaf.reason = (
                    f"{leaf.reason}; payment {payment.number} cancelled: {cancellation.reason}"
                ).strip("; ")[:2000]
                leaf.save(update_fields=["status", "reason"])
            still_paid = services.paid_on(voucher)
            voucher.status = (
                Voucher.Status.PARTLY_PAID if still_paid > 0 else Voucher.Status.DIRECTOR_APPROVED
            )
            voucher.save(update_fields=["status", "updated_at"])
        return cancellation


def reject(user: User, cancellation: PaymentCancellation, reason: str):
    with transaction.atomic():
        cancellation = PaymentCancellation.objects.select_for_update().get(pk=cancellation.pk)
        if cancellation.status != St.PENDING:
            raise PaymentError("The cancellation is not waiting for approval.")
        try:
            approvals.reject(user, DOC, cancellation.pk, reason)
        except ApprovalError as error:
            raise PaymentError(str(error)) from None
        with audit_context("payment_cancellation_rejected", reason):
            cancellation.status = St.REJECTED
            cancellation.decided_by = user
            cancellation.decided_at = timezone.now()
            cancellation.save()
        return cancellation
