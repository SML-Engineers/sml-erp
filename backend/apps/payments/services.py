"""Supplier payments and the payment lock (spec 4.6, backlog P1-07).

The rule is enforced three times: the Cashier's screen only offers approved vouchers, this
service checks status, remaining balance and role, and a database trigger refuses any payment
row that breaks it (also when two payments are saved at the same moment).

Each payment posts its journal entry in the same transaction: Dr the accounts the voucher was
coded to (by division; recoverable VAT to its tax account), Cr the bank or cash account paid
from. A part payment takes its share of each, so the voucher's coding is covered exactly once
it is fully paid.

Foreign currency (P2-11): a voucher whose lines all pay supplier invoices in one foreign
currency may be paid from an account in that currency, at the rate of the payment date. The
payment covers the voucher in proportion (in LKR at the invoices' rates, as the payable was
booked); the bank is credited with the LKR value at the payment's rate, and the difference is
an exchange gain or loss (IAS 21). Cancelling a payment is in cancellations.py.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import QuerySet, Sum
from django.utils import timezone

from apps.accounting import journal, taxes
from apps.accounting.models import Account, TaxComponent
from apps.accounting.services import AccountingError
from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters import banking, currencies
from apps.masters.models import ChequeLeaf, CompanyAccount, Currency
from apps.masters.services import MastersError, mark_used
from apps.vouchers.models import Voucher, VoucherCancellation, VoucherType

from .models import SupplierPayment

CENT = Decimal("0.01")
PAYABLE = (Voucher.Status.DIRECTOR_APPROVED, Voucher.Status.PARTLY_PAID)
Method = SupplierPayment.Method

# How each voucher type may be paid (owner, 29 Oct 2026: cheque, transfer, cash, card, QR).
METHODS_FOR_TYPE = {
    VoucherType.Method.CHEQUE: [Method.CHEQUE],
    VoucherType.Method.TRANSFER: [Method.TRANSFER, Method.CARD, Method.QR],
    VoucherType.Method.CHEQUE_OR_TRANSFER: [Method.CHEQUE, Method.TRANSFER, Method.CARD, Method.QR],
    VoucherType.Method.CASH: [Method.CASH],
    VoucherType.Method.INTERNAL: [Method.TRANSFER, Method.CHEQUE, Method.CASH],
    VoucherType.Method.ANY: list(Method),
}
NEEDS_REFERENCE = (Method.TRANSFER, Method.CARD, Method.QR)
BANK_KINDS = (CompanyAccount.Kind.CURRENT, CompanyAccount.Kind.SAVINGS)
CASH_KINDS = (CompanyAccount.Kind.CASH, CompanyAccount.Kind.PETTY_CASH)


class PaymentError(Exception):
    pass


# --- What has been paid ------------------------------------------------------------------


def paid_on(voucher: Voucher) -> Decimal:
    total = voucher.payments.filter(cancelled=False).aggregate(total=Sum("amount"))["total"]
    return total or Decimal("0.00")


def remaining(voucher: Voucher) -> Decimal:
    return voucher.total_amount - paid_on(voucher)


def foreign_basis(voucher: Voucher) -> tuple[Currency | None, Decimal | None]:
    """The foreign currency a voucher may be paid in, and its total in that currency: only
    when every line pays a supplier invoice in that one currency (P2-11)."""
    lines = list(voucher.lines.select_related("supplier_invoice__currency"))
    invoices = [line.supplier_invoice for line in lines]
    if not lines or any(i is None for i in invoices):
        return None, None
    found = {i.currency_id for i in invoices}
    currency = invoices[0].currency
    if len(found) != 1 or currency.is_base:
        return None, None
    total = Decimal("0")
    for line, invoice in zip(lines, invoices, strict=True):
        if not invoice.total_lkr:
            return None, None
        total += (line.total * invoice.total_amount / invoice.total_lkr).quantize(
            CENT, ROUND_HALF_UP
        )
    return currency, total


def foreign_left(voucher: Voucher, foreign_total: Decimal) -> Decimal:
    """What is left to pay in the foreign currency: the LKR left, in proportion."""
    left = remaining(voucher)
    if left == voucher.total_amount:
        return foreign_total
    return (left * foreign_total / voucher.total_amount).quantize(CENT, ROUND_HALF_UP)


def methods_for(voucher: Voucher) -> list[str]:
    return [str(m) for m in METHODS_FOR_TYPE.get(voucher.voucher_type.payment_method, list(Method))]


def why_not_payable(voucher: Voucher) -> str | None:
    if voucher.status not in PAYABLE:
        return (
            f"Voucher {voucher.number} is {voucher.get_status_display().lower()}; only a "
            "voucher approved by the Director can be paid."
        )
    if voucher.cancellations.filter(status=VoucherCancellation.Status.PENDING).exists():
        return f"A cancellation of voucher {voucher.number} is waiting for the Director."
    return None


def to_pay(user: User) -> QuerySet[Voucher]:
    """The Cashier's list: Director-approved vouchers not yet fully paid."""
    return (
        Voucher.objects.filter(status__in=PAYABLE, division__in=division_scope(user))
        .exclude(cancellations__status=VoucherCancellation.Status.PENDING)
        .select_related("voucher_type", "division", "payee", "transfer_to")
        .order_by("voucher_date", "id")
    )


def visible(user: User) -> QuerySet[SupplierPayment]:
    if not effective_access(user).has("payments", "view"):
        return SupplierPayment.objects.none()
    return SupplierPayment.objects.filter(voucher__division__in=division_scope(user))


# --- The journal entry -------------------------------------------------------------------


@dataclass
class Piece:
    account: Account
    division: Division | None
    amount: Decimal


def share(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split `total` in proportion to `weights`, to the cent, the parts adding up exactly
    (largest remainder)."""
    whole = sum(weights, Decimal("0"))
    if whole == 0:
        return [Decimal("0.00") for _ in weights]
    raw = [total * w / whole for w in weights]
    parts = [r.quantize(CENT, ROUND_DOWN) for r in raw]
    left = int(((total - sum(parts, Decimal("0"))) / CENT).to_integral_value())
    order = sorted(range(len(raw)), key=lambda i: (raw[i] - parts[i], -i), reverse=True)
    for i in order[:left]:
        parts[i] += CENT
    return parts


def _recoverable_tax(line, on: date) -> list[tuple[Account, Decimal]]:
    """The parts of a line's tax that go to a tax account (e.g. VAT receivable) instead of
    the cost: only when the tax code's components have a purchase account and add up to the
    tax on the line. Anything else stays part of the cost."""
    if line.tax_code is None or line.tax_amount <= 0:
        return []
    try:
        result = taxes.calculate(line.tax_code, line.amount, on)
    except Exception:  # noqa: BLE001 - no rate on that date: the tax stays in the cost
        return []
    if result.tax != line.tax_amount:
        return []
    return [
        (part.component.purchase_account, part.amount)
        for part in result.lines
        if part.amount > 0
        and part.component.purchase_account_id
        and part.component.kind == TaxComponent.Kind.CHARGED
    ]


def cost_pieces(voucher: Voucher) -> list[Piece]:
    """What the voucher pays for, by account and division, adding up to its total."""
    pieces: list[Piece] = []
    lines = voucher.lines.select_related("account", "division", "tax_code").prefetch_related(
        "splits__division"
    )
    for line in lines:
        if line.account is None:
            raise PaymentError(f"Line {line.line_no} of {voucher.number} has no account.")
        tax_parts = _recoverable_tax(line, line.invoice_date or voucher.voucher_date)
        cost = line.amount + line.tax_amount - sum((a for _, a in tax_parts), Decimal("0"))
        splits = list(line.splits.all())
        if splits:
            for split, part in zip(splits, share(cost, [s.amount for s in splits]), strict=True):
                pieces.append(Piece(line.account, split.division, part))
        else:
            pieces.append(Piece(line.account, line.division or voucher.division, cost))
        pieces += [Piece(account, None, amount) for account, amount in tax_parts]
    total = sum((p.amount for p in pieces), Decimal("0"))
    if total != voucher.total_amount:
        raise PaymentError(f"The coding of {voucher.number} does not add up to its total.")
    return [p for p in pieces if p.amount]


def journal_lines(voucher: Voucher, before: Decimal, amount: Decimal, bank: Account, payee):
    """This payment's share of each piece: what the payments so far plus this one cover,
    less what the payments so far covered."""
    pieces = cost_pieces(voucher)
    weights = [p.amount for p in pieces]
    upto_before = share(before, weights)
    upto_after = share(before + amount, weights)
    lines = []
    for piece, was, now in zip(pieces, upto_before, upto_after, strict=True):
        part = now - was
        if part == 0:
            continue
        lines.append(
            journal.Line(
                account=piece.account,
                debit=part if part > 0 else Decimal("0"),
                credit=-part if part < 0 else Decimal("0"),
                division=piece.division,
                supplier=payee,
                description=voucher.number,
            )
        )
    lines.append(
        journal.Line(account=bank, credit=amount, supplier=payee, description=voucher.number)
    )
    return lines


# --- Recording a payment -------------------------------------------------------------------


def _money(value) -> Decimal:
    if isinstance(value, float):
        raise PaymentError("Amounts must be exact decimals, not floating point.")
    try:
        amount = Decimal(str(value or "").replace(",", ""))
    except InvalidOperation:
        raise PaymentError("The amount is not a number.") from None
    if not amount.is_finite() or amount != amount.quantize(CENT) or amount <= 0:
        raise PaymentError("The amount must be more than zero, to the cent.")
    return amount


def _check_account(voucher: Voucher, account: CompanyAccount, method: str) -> Account:
    if not account.is_active:
        raise PaymentError(f"The account {account.code} is closed.")
    if method == Method.CASH and account.kind not in CASH_KINDS:
        raise PaymentError("A cash payment is made from a cash or petty cash account.")
    if method != Method.CASH and account.kind not in BANK_KINDS:
        raise PaymentError("This payment is made from a bank account.")
    if method == Method.CHEQUE and account.kind != CompanyAccount.Kind.CURRENT:
        raise PaymentError("Cheques are written on a bank current account.")
    if voucher.transfer_to_id == account.pk:
        raise PaymentError("An internal transfer is paid from a different account.")
    if account.ledger_account is None:
        raise PaymentError(
            f"The account {account.code} has no ledger account in the chart of accounts; "
            "ask the Accountant to link it."
        )
    return account.ledger_account


def record(
    user: User,
    voucher: Voucher,
    *,
    account: CompanyAccount,
    method: str,
    amount,
    payment_date: date,
    reference: str = "",
    cheque_number=None,
    cheque_date: date | None = None,
    notes: str = "",
) -> SupplierPayment:
    """Pay all or part of a Director-approved voucher (spec 4.4, Cashier)."""
    if not effective_access(user).can("record_payment"):
        raise PaymentError("Only the Cashier records supplier payments.")
    amount = _money(amount)
    if payment_date > timezone.localdate():
        raise PaymentError("The payment date cannot be in the future.")
    reference = (reference or "").strip()[:50]
    with audit_context("supplier_payment_recorded", notes), transaction.atomic():
        voucher = Voucher.objects.select_for_update().get(pk=voucher.pk)
        if not division_scope(user).filter(pk=voucher.division_id).exists():
            raise PaymentError(f"You do not work in division {voucher.division.code}.")
        refusal = why_not_payable(voucher)
        if refusal:
            raise PaymentError(refusal)
        before = paid_on(voucher)
        left = voucher.total_amount - before
        paid_amount, rate, covered = amount, Decimal("1"), amount
        lookup = None
        if not account.currency.is_base:
            currency, foreign_total = foreign_basis(voucher)
            if currency is None or currency.pk != account.currency_id:
                raise PaymentError(
                    f"Voucher {voucher.number} is paid from an LKR account: only a voucher that "
                    f"pays supplier invoices in {account.currency.code} is paid in "
                    f"{account.currency.code}."
                )
            still = foreign_left(voucher, foreign_total)
            if amount > still:
                raise PaymentError(
                    f"Only {currency.code} {still:,.2f} of voucher {voucher.number} is left to pay."
                )
            covered = (
                left
                if amount == still
                else min(left, (amount * voucher.total_amount / foreign_total).quantize(CENT))
            )
            try:
                lookup = currencies.rate_on(currency, payment_date)
            except MastersError as error:
                raise PaymentError(str(error)) from None
            rate = lookup.rate
        if covered > left:
            raise PaymentError(
                f"Only {left:,.2f} of voucher {voucher.number} is left to pay "
                f"(approved {voucher.total_amount:,.2f})."
            )
        if method not in methods_for(voucher):
            raise PaymentError(
                f"A {voucher.voucher_type.name} voucher is not paid by "
                f"{SupplierPayment.Method(method).label.lower()}."
            )
        bank = _check_account(voucher, account, method)
        leaf = None
        if method == Method.CHEQUE:
            if cheque_number in (None, ""):
                upcoming = banking.next_cheque(account)
                if upcoming is None:
                    raise PaymentError(f"{account.code} has no cheque leaves left; add a book.")
                cheque_number = upcoming[1]
            try:
                number = int(str(cheque_number).strip())
            except ValueError:
                raise PaymentError("The cheque number must be a whole number.") from None
            try:
                leaf = banking.use_cheque(
                    user,
                    account,
                    number,
                    status=ChequeLeaf.Status.ISSUED,
                    reason=f"Payment of voucher {voucher.number}",
                )
            except MastersError as error:
                raise PaymentError(str(error)) from None
            reference = banking.format_cheque(leaf.book, leaf.number)
        elif method in NEEDS_REFERENCE and not reference:
            raise PaymentError("Enter the transfer, card or QR transaction reference.")
        try:
            payment_no = allocate("supplier_payment", on_date=payment_date)
        except NumberSeriesError as error:
            raise PaymentError(str(error)) from None
        payee = voucher.payee
        to = payee.name if payee else (voucher.transfer_to.code if voucher.transfer_to else "")
        try:
            entry = journal.post(
                user,
                entry_date=payment_date,
                narration=f"Payment {payment_no} of voucher {voucher.number} to {to} "
                f"({SupplierPayment.Method(method).label} {reference})".strip(),
                lines=_with_exchange(
                    journal_lines(voucher, before, covered, bank, payee),
                    currencies.to_lkr(paid_amount, lookup) if lookup else covered,
                    covered,
                    voucher,
                ),
                source_type="supplier_payment",
                source_id=payment_no,
            )
        except AccountingError as error:
            raise PaymentError(str(error)) from None
        payment = SupplierPayment.objects.create(
            number=payment_no,
            voucher=voucher,
            account=account,
            method=method,
            reference=reference,
            cheque=leaf,
            cheque_date=cheque_date if method == Method.CHEQUE else None,
            payment_date=payment_date,
            amount=covered,
            currency=account.currency,
            paid_amount=paid_amount,
            exchange_rate=rate,
            notes=(notes or "").strip()[:300],
            journal_entry=entry,
            created_by=user,
        )
        voucher.status = (
            Voucher.Status.PAID
            if before + covered == voucher.total_amount
            else Voucher.Status.PARTLY_PAID
        )
        voucher.save(update_fields=["status", "updated_at"])
        mark_used(account)
        if lookup is not None:
            currencies.mark_rate_used(lookup)
        return payment


def _system(role: str, name: str) -> Account:
    account = Account.objects.filter(system_role=role, is_active=True).first()
    if account is None:
        raise PaymentError(f"The chart of accounts has no {name} account; ask the Accountant.")
    return account


def _with_exchange(lines, banked: Decimal, covered: Decimal, voucher: Voucher):
    """The bank line carries what left the bank in LKR; the difference from what the payment
    covers is a realised exchange loss (more left the bank) or gain (P2-11)."""
    if banked == covered:
        return lines
    bank_line = lines[-1]
    bank_line.credit = banked
    difference = banked - covered
    text = f"{voucher.number}: exchange difference"
    if difference > 0:
        lines.append(
            journal.Line(
                account=_system("exchange_loss", "Exchange loss"),
                debit=difference,
                division=voucher.division,
                description=text,
            )
        )
    else:
        lines.append(
            journal.Line(
                account=_system("exchange_gain", "Exchange gain"),
                credit=-difference,
                division=voucher.division,
                description=text,
            )
        )
    return lines


def suggested_account(voucher: Voucher) -> CompanyAccount | None:
    """The division's default bank account (P0-14), if it has one."""
    default = getattr(voucher.division, "bank_default", None)
    return default.account if default and default.account.is_active else None
