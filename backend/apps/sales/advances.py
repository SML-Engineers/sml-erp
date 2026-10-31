"""Customer advances (backlog P15-09, spec 5.2).

- The Cashier records money received from a customer before invoicing (the "record_receipt"
  action), in the currency of the account it went into, with the exchange rate of the
  receipt date. The receipt number comes from its own series, RC{YY}{MM}{NNNN} (rule 10).
- The Accountant approves it; that is enough (owner, 31 Oct 2026). Nobody approves a receipt
  they recorded (rule 5). On approval the journal entry is posted: Dr the bank or cash
  account, Cr Customer advances (a liability), in LKR. It balances (rule 2) and is never
  changed; a mistake is reversed (rule 3).
- A rejected receipt posts nothing.
- An advance may be against one of the customer's issued proformas (P15-08) or approved
  quotations; sales orders (P15-10) will be linked the same way. It waits for set-off
  against the tax invoice, built in Phase 2.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounting import journal
from apps.accounting.models import Account
from apps.accounting.services import AccountingError
from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, Division, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters import currencies, customers
from apps.masters.models import CompanyAccount, Customer
from apps.masters.services import MastersError, mark_used

from .models import CustomerAdvance, ProformaInvoice, Quotation
from .services import SalesError

DOC = "customer_advance"
CENT = Decimal("0.01")
Method = CustomerAdvance.Method
BANK_KINDS = (CompanyAccount.Kind.CURRENT, CompanyAccount.Kind.SAVINGS)
CASH_KINDS = (CompanyAccount.Kind.CASH, CompanyAccount.Kind.PETTY_CASH)
NEEDS_REFERENCE = (Method.TRANSFER, Method.CHEQUE, Method.CARD, Method.QR)
# Quotations an advance can be against: approved by the Director, and not lost or replaced.
QUOTATION_OPEN = (Quotation.Status.APPROVED, Quotation.Status.SENT, Quotation.Status.ACCEPTED)


def can_record(user: User) -> bool:
    return effective_access(user).can("record_receipt")


def visible(user: User) -> QuerySet[CustomerAdvance]:
    if not effective_access(user).has("payments", "view"):
        return CustomerAdvance.objects.none()
    return CustomerAdvance.objects.filter(division__in=division_scope(user))


def can_approve(user: User, advance: CustomerAdvance) -> bool:
    state = approvals.state_of(DOC, advance.pk)
    return (
        advance.status == CustomerAdvance.Status.AWAITING_APPROVAL
        and state is not None
        and approvals.why_not(user, state) is None
    )


def _money(value) -> Decimal:
    if isinstance(value, float):
        raise SalesError("The amount must be an exact number.")
    try:
        amount = Decimal(str(value or "").replace(",", "").strip())
    except InvalidOperation:
        raise SalesError("The amount must be a number.") from None
    if not amount.is_finite() or amount != amount.quantize(CENT) or amount <= 0:
        raise SalesError("The amount must be more than zero, to the cent.")
    if amount >= Decimal("1e16"):
        raise SalesError("The amount is too large.")
    return amount


def _check_account(account: CompanyAccount, method: str) -> None:
    if not account.is_active:
        raise SalesError(f"The account {account.code} is closed.")
    if method == Method.CASH and account.kind not in CASH_KINDS:
        raise SalesError("Cash is received into a cash account.")
    if method != Method.CASH and account.kind not in BANK_KINDS:
        raise SalesError("This receipt goes into a bank account.")
    if account.ledger_account is None:
        raise SalesError(
            f"The account {account.code} has no ledger account in the chart of accounts; "
            "ask the Accountant to link it."
        )


def record(
    user: User,
    *,
    customer: Customer,
    account: CompanyAccount,
    method: str,
    amount,
    receipt_date: date,
    quotation: Quotation | None = None,
    division: Division | None = None,
    reference: str = "",
    notes: str = "",
    proforma: ProformaInvoice | None = None,
) -> CustomerAdvance:
    """The Cashier records an advance; it goes to the Accountant for approval. Against an
    issued proforma (P15-08), an approved quotation, or for a division."""
    if not can_record(user):
        raise SalesError("Only the Cashier records customer receipts.")
    amount = _money(amount)
    if not isinstance(receipt_date, date) or receipt_date > timezone.localdate():
        raise SalesError("The receipt date cannot be in the future.")
    if method not in Method.values:
        raise SalesError("Choose how the money was received.")
    reference = (reference or "").strip()[:50]
    if method in NEEDS_REFERENCE and not reference:
        raise SalesError("Enter the cheque number or the transfer, card or QR reference.")
    if not isinstance(customer, Customer):
        raise SalesError("Choose the customer.")
    if not customer.is_active:
        raise SalesError(f"Customer {customer.code} is inactive.")
    if proforma is not None:
        if proforma.customer_id != customer.pk:
            raise SalesError(f"Proforma {proforma.number} is for another customer.")
        if proforma.status != ProformaInvoice.Status.ISSUED:
            raise SalesError(
                f"Proforma {proforma.number} is {proforma.get_status_display().lower()}: an "
                "advance is against an issued proforma."
            )
        quotation = proforma.quotation
    if quotation is not None:
        if quotation.customer_id != customer.pk:
            raise SalesError(f"Quotation {quotation.label} is for another customer.")
        if quotation.status not in QUOTATION_OPEN:
            raise SalesError(
                f"Quotation {quotation.label} is {quotation.get_status_display().lower()}: "
                "an advance is against an approved quotation."
            )
        division = quotation.division
    if not isinstance(division, Division):
        raise SalesError("Choose the division the advance is for.")
    if not division_scope(user).filter(pk=division.pk).exists():
        raise SalesError(f"You do not work in division {division.code}.")
    if not isinstance(account, CompanyAccount):
        raise SalesError("Choose the account the money went into.")
    _check_account(account, method)
    try:
        lookup = currencies.rate_on(account.currency, receipt_date)
    except MastersError as error:
        raise SalesError(str(error)) from None

    with audit_context("customer_advance_recorded", notes), transaction.atomic():
        try:
            number = allocate("customer_receipt", on_date=receipt_date)
        except NumberSeriesError as error:
            raise SalesError(str(error)) from None
        advance = CustomerAdvance.objects.create(
            number=number,
            customer=customer,
            quotation=quotation,
            proforma=proforma,
            division=division,
            receipt_date=receipt_date,
            account=account,
            method=method,
            reference=reference,
            currency=account.currency,
            amount=amount,
            exchange_rate=lookup.rate,
            rate_date=lookup.rate_date,
            amount_lkr=currencies.to_lkr(amount, lookup),
            notes=(notes or "").strip()[:1000],
            created_by=user,
        )
        try:
            approvals.submit(
                user,
                DOC,
                advance.pk,
                created_by=user,
                amount=advance.amount_lkr,
                division=division,
                title=f"Customer advance {number} from {customer.name}",
                link=f"/advances/{advance.pk}",
            )
        except ApprovalError as error:
            raise SalesError(str(error)) from None
        customers.mark_used(customer)
        mark_used(account)
        currencies.mark_rate_used(lookup)
        return advance


def journal_lines(advance: CustomerAdvance) -> list[journal.Line]:
    """Dr the bank or cash account, Cr Customer advances, in LKR."""
    liability = Account.objects.filter(system_role="customer_advances", is_active=True).first()
    if liability is None:
        raise SalesError(
            "The chart of accounts has no Customer advances account; ask the Accountant."
        )
    text = f"Advance {advance.number} from {advance.customer.name}"
    return [
        journal.Line(
            account=advance.account.ledger_account,
            debit=advance.amount_lkr,
            division=advance.division,
            description=text,
        ),
        journal.Line(
            account=liability,
            credit=advance.amount_lkr,
            division=advance.division,
            description=text,
        ),
    ]


def approve(user: User, advance: CustomerAdvance, comment: str = "") -> CustomerAdvance:
    """The Accountant approves: the journal entry is posted in the same transaction."""
    with transaction.atomic():
        advance = CustomerAdvance.objects.select_for_update().get(pk=advance.pk)
        if advance.status != CustomerAdvance.Status.AWAITING_APPROVAL:
            raise SalesError("The receipt is not waiting for approval.")
        try:
            state = approvals.approve(user, DOC, advance.pk, comment)
        except ApprovalError as error:
            raise SalesError(str(error)) from None
        if state.status != ApprovalState.Status.APPROVED:
            return advance
        with audit_context("customer_advance_approved", comment):
            try:
                entry = journal.post(
                    user,
                    entry_date=advance.receipt_date,
                    narration=f"Advance {advance.number} from {advance.customer.name} "
                    f"({advance.get_method_display()} {advance.reference})".strip(),
                    lines=journal_lines(advance),
                    source_type="customer_advance",
                    source_id=advance.number,
                )
            except AccountingError as error:
                raise SalesError(str(error)) from None
            advance.status = CustomerAdvance.Status.APPROVED
            advance.journal_entry = entry
            advance.approved_at = timezone.now()
            advance.save(update_fields=["status", "journal_entry", "approved_at"])
        return advance


def reject(user: User, advance: CustomerAdvance, reason: str) -> CustomerAdvance:
    """The Accountant rejects it (for example the money is not in the bank): nothing is
    posted. The reason is required."""
    with transaction.atomic():
        advance = CustomerAdvance.objects.select_for_update().get(pk=advance.pk)
        if advance.status != CustomerAdvance.Status.AWAITING_APPROVAL:
            raise SalesError("The receipt is not waiting for approval.")
        try:
            approvals.reject(user, DOC, advance.pk, reason)
        except ApprovalError as error:
            raise SalesError(str(error)) from None
        with audit_context("customer_advance_rejected", reason):
            advance.status = CustomerAdvance.Status.REJECTED
            advance.save(update_fields=["status"])
        return advance


def balance_lkr(advance: CustomerAdvance) -> Decimal:
    """What is still to be set off against invoices."""
    if advance.status != CustomerAdvance.Status.APPROVED:
        return Decimal("0.00")
    return advance.amount_lkr - advance.set_off_lkr
