"""Customer receipts and advance set-off (backlog P2-07, spec 5.2, 6).

Receipts
- The Cashier ("record_receipt") records money received from a customer: how (transfer,
  cheque, cash, card, QR), the reference, and how it is split across one or more of the
  customer's issued tax invoices. The split adds up to the amount, and no invoice gets more
  than is open on it: its total less approved credit notes, other receipts not rejected and
  advances set off (also a database rule). A customer who pays more has the extra recorded as
  an advance. LKR only for now (invoices in other currencies come with P2-09).
- Numbered from the receipts series RC{YY}{MM}{NNNN}, shared with advances (rule 10).
- The Accountant approves, as for advances, or a person the Admin gives "Approve customer
  receipts and advances" to and the Director confirms (owner, 3 Nov 2026); nobody approves
  their own receipt (rule 5).
  Approval posts Dr the bank or cash account, Cr Accounts receivable with the customer, per
  invoice and division. A cheque goes to Undeposited funds until it is deposited (P2-14). A
  post-dated cheque is approved but waits: a daily job posts it on its date. Rejecting
  posts nothing and frees the invoices again. Posted receipts never change (rule 3).

Advance set-off (spec 5.2: "when the tax invoice is raised, the advance is set off
automatically against it")
- Issuing an invoice sets off the approved advances of its sales order (or of the order's
  proforma or quotation), then the customer's advances on account (against no order, e.g.
  money paid over the invoices of a receipt), oldest first, up to the invoice's total
  (owner, 3 Nov 2026).
- The Accountant can also set off any approved advance of the customer against any of its
  open invoices.
- Each set-off posts Dr Customer advances, Cr Accounts receivable (the customer). The database
  keeps the advance's set-off total and refuses going past the advance or the invoice.
"""

import logging
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Case, F, Q, QuerySet, Sum, Value, When
from django.utils import timezone

from apps.accounting import journal
from apps.accounting.models import Account
from apps.accounting.services import AccountingError
from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters import currencies, customers
from apps.masters.models import CompanyAccount, Customer
from apps.masters.services import MastersError, mark_used

from . import advances
from .models import (
    AdvanceSetOff,
    CreditNote,
    CustomerAdvance,
    CustomerReceipt,
    ReceiptAllocation,
    TaxInvoice,
)
from .services import SalesError

log = logging.getLogger(__name__)

DOC = "customer_receipt"
SET_OFF = "customer_set_off"
ZERO = Decimal("0.00")
St = CustomerReceipt.Status
Method = CustomerReceipt.Method
# Cheques in Sri Lanka are valid for six months from their date.
CHEQUE_LIFE = timedelta(days=183)
OPEN_RECEIPTS = (St.AWAITING_APPROVAL, St.POST_DATED)


@dataclass
class Allocation:
    invoice: TaxInvoice
    amount: object


# --- Who may do what ---------------------------------------------------------------------


def can_record(user: User) -> bool:
    return advances.can_record(user)


def visible(user: User) -> QuerySet[CustomerReceipt]:
    """Receipts in the Supplier payments and receipts area, for invoices of the user's
    divisions."""
    if not effective_access(user).has("payments", "view"):
        return CustomerReceipt.objects.none()
    outside = ReceiptAllocation.objects.exclude(invoice__division__in=division_scope(user)).values(
        "receipt_id"
    )
    return CustomerReceipt.objects.exclude(pk__in=outside)


def can_approve(user: User, receipt: CustomerReceipt) -> bool:
    state = approvals.state_of(DOC, receipt.pk)
    return (
        receipt.status == St.AWAITING_APPROVAL
        and state is not None
        and approvals.why_not(user, state) is None
    )


def can_set_off(user: User) -> bool:
    """Setting off an advance by hand is the Accountant's (Accounting: Manage)."""
    return effective_access(user).has("accounting", "manage")


# --- What is open on an invoice ----------------------------------------------------------------


def settlement(invoices) -> dict[int, dict]:
    """Per issued invoice: credited (approved credit notes), received (posted receipts),
    pending (receipts awaiting approval or post-dated cheques), set off (advances) and what is
    still open."""
    rows = {
        i.pk: {
            "total": i.total_amount,
            "credited": ZERO,
            "received": ZERO,
            "pending": ZERO,
            "set_off": ZERO,
        }
        for i in invoices
    }
    keys = list(rows)
    for r in (
        CreditNote.objects.filter(invoice__in=keys, status=CreditNote.Status.APPROVED)
        .values("invoice")
        .annotate(total=Sum("total_amount"))
    ):
        rows[r["invoice"]]["credited"] = r["total"]
    for r in (
        ReceiptAllocation.objects.filter(invoice__in=keys)
        .exclude(receipt__status=St.REJECTED)
        .values("invoice", "receipt__status")
        .annotate(total=Sum("amount"))
    ):
        key = "received" if r["receipt__status"] == St.POSTED else "pending"
        rows[r["invoice"]][key] += r["total"]
    for r in (
        AdvanceSetOff.objects.filter(invoice__in=keys)
        .values("invoice")
        .annotate(total=Sum("amount"))
    ):
        rows[r["invoice"]]["set_off"] = r["total"]
    for row in rows.values():
        row["open"] = (
            row["total"] - row["credited"] - row["received"] - row["pending"] - row["set_off"]
        )
    return rows


def open_amount(invoice: TaxInvoice) -> Decimal:
    if invoice.status != TaxInvoice.Status.ISSUED:
        return ZERO
    return settlement([invoice])[invoice.pk]["open"]


def to_lkr(amount: Decimal, exchange_rate: Decimal) -> Decimal:
    return (Decimal(amount) * exchange_rate).quantize(Decimal("0.01"), ROUND_HALF_UP)


def lkr_left(invoice: TaxInvoice) -> Decimal:
    """What is still on the receivable for the invoice in LKR: its LKR total less what
    approved credit notes, receipts not rejected and set-offs took off at its rate."""
    taken = (
        CreditNote.objects.filter(invoice=invoice, status=CreditNote.Status.APPROVED).aggregate(
            t=Sum("total_lkr")
        )["t"]
        or ZERO
    )
    taken += (
        ReceiptAllocation.objects.filter(invoice=invoice)
        .exclude(receipt__status=St.REJECTED)
        .aggregate(t=Sum("carrying_lkr"))["t"]
        or ZERO
    )
    taken += (
        AdvanceSetOff.objects.filter(invoice=invoice).aggregate(t=Sum("carrying_lkr"))["t"] or ZERO
    )
    return invoice.total_lkr - taken


def carrying(invoice: TaxInvoice, amount: Decimal, open_now: Decimal) -> Decimal:
    """The LKR to take off the receivable for `amount` of the invoice's currency: at the
    invoice's rate, or, when it clears what is open, exactly what is left in LKR, so a
    settled invoice leaves no cents behind (P2-09)."""
    if amount == open_now:
        return lkr_left(invoice)
    return to_lkr(amount, invoice.exchange_rate)


def exchange_line(difference: Decimal, division, text: str) -> journal.Line | None:
    """A realised exchange difference: a gain is credited, a loss debited (P2-09)."""
    if not difference:
        return None
    if difference > 0:
        account = _system_account("exchange_gain", "Exchange gain")
        return journal.Line(account=account, credit=difference, division=division, description=text)
    account = _system_account("exchange_loss", "Exchange loss")
    return journal.Line(account=account, debit=-difference, division=division, description=text)


def open_invoices(user: User, customer: Customer | None = None) -> list[tuple[TaxInvoice, dict]]:
    """Issued invoices of the user's divisions with something still open, oldest first."""
    rows = TaxInvoice.objects.filter(
        status=TaxInvoice.Status.ISSUED, division__in=division_scope(user)
    ).select_related("customer", "division", "currency")
    if customer is not None:
        rows = rows.filter(customer=customer)
    rows = list(rows.order_by("invoice_date", "id"))
    figures = settlement(rows)
    return [(i, figures[i.pk]) for i in rows if figures[i.pk]["open"] > 0]


# --- Recording -------------------------------------------------------------------------------


def _check_account(account, method: str, currency) -> None:
    if not isinstance(account, CompanyAccount):
        raise SalesError("Choose the account the money went into.")
    advances._check_account(account, method)
    if account.currency_id != currency.pk:
        raise SalesError(
            f"The invoices are in {currency.code}: the money goes into a {currency.code} "
            f"account, not {account.code} ({account.currency.code})."
        )


def record(
    user: User,
    *,
    customer: Customer,
    method: str,
    amount,
    receipt_date: date,
    allocations: list[Allocation],
    account: CompanyAccount | None = None,
    reference: str = "",
    cheque_date: date | None = None,
    cheque_bank: str = "",
    notes: str = "",
) -> CustomerReceipt:
    """The Cashier records a receipt split across the customer's invoices; it goes to the
    Accountant for approval."""
    if not can_record(user):
        raise SalesError("Only the Cashier records customer receipts.")
    amount = advances._money(amount)
    today = timezone.localdate()
    if not isinstance(receipt_date, date) or receipt_date > today:
        raise SalesError("The receipt date cannot be in the future.")
    if method not in Method.values:
        raise SalesError("Choose how the money was received.")
    reference = (reference or "").strip()[:50]
    if method in advances.NEEDS_REFERENCE and not reference:
        raise SalesError("Enter the cheque number or the transfer, card or QR reference.")
    if not isinstance(customer, Customer):
        raise SalesError("Choose the customer.")
    if method == Method.CHEQUE:
        account = None  # waits in Undeposited funds until it is deposited (P2-14)
        cheque_date = cheque_date or receipt_date
        if not isinstance(cheque_date, date):
            raise SalesError("Enter the date on the cheque.")
        if cheque_date > receipt_date + CHEQUE_LIFE:
            raise SalesError("A cheque dated more than six months ahead is not accepted.")
        if cheque_date < receipt_date - CHEQUE_LIFE:
            raise SalesError("The cheque is more than six months old: the bank will not pay it.")
        cheque_bank = (cheque_bank or "").strip()[:100]
    else:
        cheque_date, cheque_bank = None, ""
    if not allocations:
        raise SalesError("Choose the invoices this money pays.")
    scope = division_scope(user)
    given: dict[int, Decimal] = OrderedDict()
    for part in allocations:
        invoice = part.invoice
        if not isinstance(invoice, TaxInvoice):
            raise SalesError("Choose the invoices this money pays.")
        if invoice.pk in given:
            raise SalesError(f"Invoice {invoice.number} is chosen twice.")
        given[invoice.pk] = advances._money(part.amount)
    if sum(given.values(), ZERO) != amount:
        raise SalesError(
            f"The amounts paid on the invoices add up to {sum(given.values(), ZERO):,.2f}, "
            f"not the {amount:,.2f} received. Record any extra as an advance."
        )

    with audit_context("customer_receipt_recorded", notes), transaction.atomic():
        invoices = {
            i.pk: i
            for i in TaxInvoice.objects.select_for_update()
            .filter(pk__in=list(given))
            .order_by("pk")
        }
        figures = settlement(invoices.values())
        currency = invoices[next(iter(given))].currency
        if any(i.currency_id != currency.pk for i in invoices.values()):
            raise SalesError("One receipt pays invoices of one currency: record one per currency.")
        if method != Method.CHEQUE:
            _check_account(account, method, currency)
        try:
            lookup = currencies.rate_on(currency, receipt_date)
        except MastersError as error:
            raise SalesError(str(error)) from None
        for pk, paid in given.items():
            invoice = invoices[pk]
            if invoice.customer_id != customer.pk:
                raise SalesError(f"Invoice {invoice.number} is for another customer.")
            if invoice.status != TaxInvoice.Status.ISSUED:
                raise SalesError("Only issued invoices are paid.")
            if not scope.filter(pk=invoice.division_id).exists():
                raise SalesError(f"You do not work in division {invoice.division.code}.")
            left = figures[pk]["open"]
            if paid > left:
                raise SalesError(
                    f"Invoice {invoice.number} has only {max(left, ZERO):,.2f} open; "
                    f"{paid:,.2f} cannot be paid on it."
                )
        try:
            number = allocate("customer_receipt", on_date=receipt_date)
        except NumberSeriesError as error:
            raise SalesError(str(error)) from None
        receipt = CustomerReceipt.objects.create(
            number=number,
            customer=customer,
            receipt_date=receipt_date,
            method=method,
            account=account,
            reference=reference,
            cheque_date=cheque_date,
            cheque_bank=cheque_bank,
            currency=currency,
            exchange_rate=lookup.rate,
            rate_date=lookup.rate_date,
            amount=amount,
            amount_lkr=currencies.to_lkr(amount, lookup),
            notes=(notes or "").strip()[:1000],
            created_by=user,
        )
        for pk, paid in given.items():
            invoice = invoices[pk]
            ReceiptAllocation.objects.create(
                receipt=receipt,
                invoice=invoice,
                amount=paid,
                carrying_lkr=carrying(invoice, paid, figures[pk]["open"]),
            )
        currencies.mark_rate_used(lookup)
        first = invoices[next(iter(given))]
        try:
            approvals.submit(
                user,
                DOC,
                receipt.pk,
                created_by=user,
                amount=amount,
                division=first.division,
                title=f"Customer receipt {number} from {customer.name}",
                link=f"/receipts/{receipt.pk}",
            )
        except ApprovalError as error:
            raise SalesError(str(error)) from None
        customers.mark_used(customer)
        if account is not None:
            mark_used(account)
        return receipt


# --- Approval and posting ----------------------------------------------------------------------


def _system_account(role: str, name: str) -> Account:
    account = Account.objects.filter(system_role=role, is_active=True).first()
    if account is None:
        raise SalesError(f"The chart of accounts has no {name} account; ask the Accountant.")
    return account


def journal_lines(receipt: CustomerReceipt) -> list[journal.Line]:
    """Dr the bank or cash account (Undeposited funds for a cheque) per division with the LKR
    value at the receipt's rate, Cr Accounts receivable with the customer per invoice with
    what it carried at the invoice's rate; the difference is a realised exchange gain or
    loss per division (P2-09). In LKR both are the same and there is no difference."""
    if receipt.method == Method.CHEQUE:
        into = _system_account("undeposited_funds", "Undeposited funds")
    else:
        into = receipt.account.ledger_account
        if into is None:
            raise SalesError(
                f"The account {receipt.account.code} has no ledger account; ask the Accountant."
            )
    receivable = _system_account("accounts_receivable", "Accounts receivable")
    text = f"Receipt {receipt.number} from {receipt.customer.name}"
    parts = list(receipt.allocations.select_related("invoice__division").order_by("id"))
    # The LKR received, split over the invoices at the receipt's rate; the last takes the cents.
    banked = [to_lkr(part.amount, receipt.exchange_rate) for part in parts]
    banked[-1] += receipt.amount_lkr - sum(banked, ZERO)
    by_division: OrderedDict = OrderedDict()
    for part, lkr in zip(parts, banked, strict=True):
        division = part.invoice.division
        into_total, carried = by_division.get(division, (ZERO, ZERO))
        by_division[division] = (into_total + lkr, carried + part.carrying_lkr)
    lines = [
        journal.Line(account=into, debit=total, division=division, description=text)
        for division, (total, _) in by_division.items()
        if total
    ]
    lines += [
        journal.Line(
            account=receivable,
            credit=part.carrying_lkr,
            division=part.invoice.division,
            customer=receipt.customer,
            description=f"{text}: invoice {part.invoice.number}",
        )
        for part in parts
        if part.carrying_lkr
    ]
    for division, (total, carried) in by_division.items():
        line = exchange_line(total - carried, division, f"{text}: exchange difference")
        if line is not None:
            lines.append(line)
    return lines


def _entry_date(receipt: CustomerReceipt) -> date:
    if receipt.method == Method.CHEQUE and receipt.cheque_date > receipt.receipt_date:
        return receipt.cheque_date
    return receipt.receipt_date


def _post(user: User, receipt: CustomerReceipt) -> CustomerReceipt:
    """Posts the entry (inside the caller's transaction, on a locked receipt)."""
    method = receipt.get_method_display()
    try:
        entry = journal.post(
            user,
            entry_date=_entry_date(receipt),
            narration=f"Receipt {receipt.number} from {receipt.customer.name} "
            f"({method} {receipt.reference})".strip(),
            lines=journal_lines(receipt),
            source_type=DOC,
            source_id=receipt.number,
        )
    except AccountingError as error:
        raise SalesError(str(error)) from None
    receipt.status = St.POSTED
    receipt.journal_entry = entry
    receipt.posted_at = timezone.now()
    receipt.save(update_fields=["status", "journal_entry", "posted_at"])
    return receipt


def approve(user: User, receipt: CustomerReceipt, comment: str = "") -> CustomerReceipt:
    """The Accountant approves: posted at once, or on the cheque's date if it is post-dated."""
    with transaction.atomic():
        receipt = CustomerReceipt.objects.select_for_update().get(pk=receipt.pk)
        if receipt.status != St.AWAITING_APPROVAL:
            raise SalesError("The receipt is not waiting for approval.")
        try:
            state = approvals.approve(user, DOC, receipt.pk, comment)
        except ApprovalError as error:
            raise SalesError(str(error)) from None
        if state.status != ApprovalState.Status.APPROVED:
            return receipt
        with audit_context("customer_receipt_approved", comment):
            receipt.approved_by = user
            receipt.approved_at = timezone.now()
            if _entry_date(receipt) > timezone.localdate():
                receipt.status = St.POST_DATED
                receipt.save(update_fields=["status", "approved_by", "approved_at"])
                return receipt
            receipt.save(update_fields=["approved_by", "approved_at"])
            return _post(user, receipt)


def reject(user: User, receipt: CustomerReceipt, reason: str) -> CustomerReceipt:
    """The Accountant rejects it (for example the money is not in the bank): nothing is
    posted and the invoices are open again. The reason is required."""
    with transaction.atomic():
        receipt = CustomerReceipt.objects.select_for_update().get(pk=receipt.pk)
        if receipt.status != St.AWAITING_APPROVAL:
            raise SalesError("The receipt is not waiting for approval.")
        try:
            approvals.reject(user, DOC, receipt.pk, reason)
        except ApprovalError as error:
            raise SalesError(str(error)) from None
        with audit_context("customer_receipt_rejected", reason):
            receipt.status = St.REJECTED
            receipt.save(update_fields=["status"])
        return receipt


def post_due(today: date | None = None) -> int:
    """Daily: post-dated cheques whose date has come are posted, in the name of the
    Accountant who approved them. Returns how many were posted."""
    today = today or timezone.localdate()
    done = 0
    for pk in CustomerReceipt.objects.filter(
        status=St.POST_DATED, cheque_date__lte=today
    ).values_list("pk", flat=True):
        try:
            with audit_context("customer_receipt_cheque_due"), transaction.atomic():
                receipt = CustomerReceipt.objects.select_for_update().get(pk=pk)
                if receipt.status != St.POST_DATED:
                    continue
                _post(receipt.approved_by, receipt)
                done += 1
        except SalesError:
            log.exception("Post-dated cheque receipt %s could not be posted", pk)
    return done


# --- Advance set-off -----------------------------------------------------------------------------


def _set_off(
    user: User, advance: CustomerAdvance, invoice: TaxInvoice, amount: Decimal, on_date: date
) -> AdvanceSetOff:
    """Posts Dr Customer advances (in LKR at the advance's rate), Cr Accounts receivable (at
    the invoice's rate), any difference to exchange gain or loss (P2-09). Inside the caller's
    transaction; the database checks the advance and the invoice."""
    liability = _system_account("customer_advances", "Customer advances")
    receivable = _system_account("accounts_receivable", "Accounts receivable")
    text = f"Advance {advance.number} set off against invoice {invoice.number}"
    if amount == advances.balance(advance):
        held = advance.amount_lkr - advance.set_off_lkr  # all that is left, to the cent
    else:
        held = to_lkr(amount, advance.exchange_rate)
    carried = carrying(invoice, amount, open_amount(invoice))
    lines = [
        journal.Line(account=liability, debit=held, division=advance.division, description=text),
        journal.Line(
            account=receivable,
            credit=carried,
            division=invoice.division,
            customer=invoice.customer,
            description=text,
        ),
    ]
    difference = exchange_line(held - carried, invoice.division, f"{text}: exchange difference")
    if difference is not None:
        lines.append(difference)
    try:
        entry = journal.post(
            user,
            entry_date=on_date,
            narration=f"{text} ({invoice.customer.name})",
            lines=lines,
            source_type=SET_OFF,
            source_id=invoice.number,
        )
    except AccountingError as error:
        raise SalesError(str(error)) from None
    return AdvanceSetOff.objects.create(
        advance=advance,
        invoice=invoice,
        amount=amount,
        amount_lkr=held,
        carrying_lkr=carried,
        set_off_date=on_date,
        journal_entry=entry,
        created_by=user,
    )


def advances_for(invoice: TaxInvoice) -> QuerySet[CustomerAdvance]:
    """Approved advances, not fully set off, to take off this invoice: first those paid for
    its order (against the order itself, or before it existed against its proforma or
    quotation), then the customer's money on account, against no order (for example what was
    paid over the invoices of a receipt; owner, 3 Nov 2026: set off against the next or any
    future invoice). Oldest first in each group."""
    order = invoice.order
    match = Q(sales_order=order)
    if order.proforma_id:
        match |= Q(sales_order__isnull=True, proforma_id=order.proforma_id)
    if order.quotation_id:
        match |= Q(sales_order__isnull=True, quotation_id=order.quotation_id)
    on_account = Q(sales_order__isnull=True, proforma__isnull=True, quotation__isnull=True)
    return (
        CustomerAdvance.objects.filter(
            match | on_account,
            customer_id=invoice.customer_id,
            currency_id=invoice.currency_id,
            status=CustomerAdvance.Status.APPROVED,
            set_off_lkr__lt=F("amount_lkr"),
        )
        .annotate(group=Case(When(match, then=Value(0)), default=Value(1)))
        .order_by("group", "receipt_date", "pk")
    )


def set_off_advances(user: User, invoice: TaxInvoice) -> list[AdvanceSetOff]:
    """When an invoice is issued: its order's advances, then the customer's money on account,
    are set off against it, oldest first, up to what is open on it. Runs inside the issuing
    transaction."""
    done = []
    left = open_amount(invoice)
    for advance in advances_for(invoice).select_for_update():
        if left <= 0:
            break
        amount = min(advances.balance(advance), left)
        if amount <= 0:
            continue
        with audit_context("customer_advance_set_off"):
            on_date = max(invoice.invoice_date, advance.receipt_date)
            done.append(_set_off(user, advance, invoice, amount, on_date))
        left -= amount
    return done


def set_off(user: User, advance: CustomerAdvance, invoice: TaxInvoice, amount) -> AdvanceSetOff:
    """The Accountant sets off an approved advance against an open invoice of the same
    customer, dated today."""
    if not can_set_off(user):
        raise SalesError("Only the Accountant sets off advances against invoices.")
    amount = advances._money(amount)
    scope = division_scope(user)
    with audit_context("customer_advance_set_off"), transaction.atomic():
        advance = CustomerAdvance.objects.select_for_update().get(pk=advance.pk)
        invoice = TaxInvoice.objects.select_for_update().get(pk=invoice.pk)
        if advance.status != CustomerAdvance.Status.APPROVED:
            raise SalesError(f"Advance {advance.number} is not approved.")
        if invoice.status != TaxInvoice.Status.ISSUED:
            raise SalesError("An advance is set off only against an issued invoice.")
        if invoice.customer_id != advance.customer_id:
            raise SalesError(f"Invoice {invoice.number} is for another customer.")
        for division in (advance.division_id, invoice.division_id):
            if not scope.filter(pk=division).exists():
                raise SalesError("The advance or the invoice is of a division you do not work in.")
        left = advances.balance(advance)
        if advance.currency_id != invoice.currency_id:
            raise SalesError(
                f"Advance {advance.number} is in {advance.currency.code} and invoice "
                f"{invoice.number} in {invoice.currency.code}: they are not set off."
            )
        if amount > left:
            raise SalesError(f"Advance {advance.number} has only {left:,.2f} left to set off.")
        open_now = open_amount(invoice)
        if amount > open_now:
            raise SalesError(f"Invoice {invoice.number} has only {max(open_now, ZERO):,.2f} open.")
        today = timezone.localdate()
        return _set_off(user, advance, invoice, amount, max(today, advance.receipt_date))
