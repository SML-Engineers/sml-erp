"""Cheque register, deposits and returned cheques (backlog P2-14).

- The register lists our cheques (issued, cleared, spoiled) and the customers' cheques
  (awaiting approval, post-dated, in hand, deposited, cleared, returned).
- A deposit slip takes customers' cheques in hand (their receipts posted to Undeposited funds)
  to one of the company's LKR bank accounts: Dr the bank, Cr Undeposited funds, per cheque.
- A cheque is marked cleared once the bank shows it paid or credited (by hand now; the bank
  reconciliation, P2-16, will do it from the statement).
- A customer's cheque that comes back unpaid is returned with a reason: the receipt's entry is
  posted in reverse (Dr Accounts receivable with the customer per invoice), with the bank it
  was deposited in credited instead of Undeposited funds; the invoices it paid are open again.
  A cheque returned before it was deposited simply leaves Undeposited funds.
- Transfers between the company's own accounts are Internal Transfer vouchers (spec 4.1),
  approved like any voucher and paid by the Cashier.

The Cashier or the Accountant does all of this.
"""

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounting import journal
from apps.accounting.models import Account
from apps.accounting.services import AccountingError
from apps.core.access import division_scope, effective_access, sees_all_divisions
from apps.core.audit import audit_context
from apps.core.models import User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters.models import ChequeLeaf, CompanyAccount
from apps.masters.services import mark_used
from apps.sales.models import CustomerReceipt

from .models import ChequeClearance, Deposit, DepositLine

RS = CustomerReceipt.Status
BANK_KINDS = (CompanyAccount.Kind.CURRENT, CompanyAccount.Kind.SAVINGS)
ZERO = Decimal("0")


class BankingError(Exception):
    pass


def can_handle(user: User) -> bool:
    access = effective_access(user)
    return access.has("payments", "enter") or access.has("banking", "enter")


def can_view(user: User) -> bool:
    access = effective_access(user)
    return access.has("payments", "view") or access.has("banking", "view")


def _handler(user: User) -> None:
    if not can_handle(user):
        raise BankingError("Only the Cashier or the Accountant handles cheques and deposits.")


def _day(value, what: str) -> date:
    if not isinstance(value, date):
        raise BankingError(f"Give the {what}.")
    if value > timezone.localdate():
        raise BankingError(f"The {what} cannot be in the future.")
    return value


def _undeposited() -> Account:
    account = Account.objects.filter(system_role="undeposited_funds", is_active=True).first()
    if account is None:
        raise BankingError("The chart of accounts has no Undeposited funds account.")
    return account


# --- The register ------------------------------------------------------------------------


def issued(user: User) -> QuerySet[ChequeLeaf]:
    """Our cheques, with the payment they were written for."""
    if not can_view(user):
        return ChequeLeaf.objects.none()
    return ChequeLeaf.objects.select_related(
        "account", "book", "payment__voucher__payee", "payment__voucher__division", "clearance"
    ).filter(account__kind=CompanyAccount.Kind.CURRENT)


def issued_status(leaf: ChequeLeaf) -> str:
    if leaf.status == ChequeLeaf.Status.SPOILED:
        return "spoiled"
    if getattr(leaf, "clearance", None) is not None:
        return "cleared"
    return "issued"


def received(user: User) -> QuerySet[CustomerReceipt]:
    """The customers' cheques of my divisions' invoices (all, while I see every division)."""
    if not can_view(user):
        return CustomerReceipt.objects.none()
    rows = CustomerReceipt.objects.filter(method=CustomerReceipt.Method.CHEQUE).exclude(
        status=RS.REJECTED
    )
    if not sees_all_divisions(user):
        rows = rows.filter(allocations__invoice__division__in=division_scope(user)).distinct()
    return rows.select_related(
        "customer", "currency", "deposit_line__deposit", "deposit_line__clearance", "return_entry"
    )


def received_status(receipt: CustomerReceipt) -> str:
    if receipt.status != RS.POSTED:
        return receipt.status  # awaiting_approval, post_dated, returned
    line = getattr(receipt, "deposit_line", None)
    if line is None:
        return "in_hand"
    if getattr(line, "clearance", None) is not None:
        return "cleared"
    return "deposited"


def in_hand() -> QuerySet[CustomerReceipt]:
    """Customers' cheques posted to Undeposited funds and not yet deposited."""
    return (
        CustomerReceipt.objects.filter(
            method=CustomerReceipt.Method.CHEQUE, status=RS.POSTED, deposit_line__isnull=True
        )
        .select_related("customer", "journal_entry")
        .order_by("cheque_date", "number")
    )


# --- Deposits ----------------------------------------------------------------------------


def deposit(
    user: User,
    *,
    account: CompanyAccount,
    deposit_date,
    receipts: list[CustomerReceipt],
    slip_no: str = "",
) -> Deposit:
    """Take customers' cheques in hand to an LKR bank account."""
    _handler(user)
    deposit_date = _day(deposit_date, "deposit date")
    if not isinstance(account, CompanyAccount) or not account.is_active:
        raise BankingError("Choose an active bank account.")
    if account.kind not in BANK_KINDS or not account.currency.is_base:
        raise BankingError("Cheques are deposited into one of the company's LKR bank accounts.")
    if account.ledger_account is None:
        raise BankingError(f"The account {account.code} has no ledger account; ask the Accountant.")
    if not receipts:
        raise BankingError("Choose the cheques to deposit.")
    if len({r.pk for r in receipts}) != len(receipts):
        raise BankingError("A cheque appears twice on the slip.")
    with audit_context("deposit_made"), transaction.atomic():
        found = list(
            CustomerReceipt.objects.select_for_update()
            .filter(pk__in=[r.pk for r in receipts])
            .select_related("customer", "journal_entry")
            .order_by("number")
        )
        waiting = set(in_hand().filter(pk__in=[r.pk for r in found]).values_list("pk", flat=True))
        for r in found:
            if r.pk not in waiting:
                raise BankingError(f"Receipt {r.number} is not a cheque waiting to be deposited.")
            if r.cheque_date and r.cheque_date > deposit_date:
                raise BankingError(
                    f"The cheque of receipt {r.number} is dated {r.cheque_date:%d/%m/%Y}; it "
                    "cannot be deposited before then."
                )
            if r.journal_entry.entry_date > deposit_date:
                raise BankingError(f"Receipt {r.number} was posted after the deposit date.")
        total = sum((r.amount_lkr for r in found), ZERO)
        try:
            number = allocate("deposit", on_date=deposit_date)
        except NumberSeriesError as error:
            raise BankingError(str(error)) from None
        undeposited = _undeposited()
        lines = [journal.Line(account=account.ledger_account, debit=total, description=number)]
        lines += [
            journal.Line(
                account=undeposited,
                credit=r.amount_lkr,
                description=f"{r.number} {r.customer.name} cheque {r.reference}".strip(),
            )
            for r in found
        ]
        try:
            entry = journal.post(
                user,
                entry_date=deposit_date,
                narration=f"Deposit {number} of {len(found)} cheque(s) into {account.code}",
                lines=lines,
                source_type="deposit",
                source_id=number,
            )
        except AccountingError as error:
            raise BankingError(str(error)) from None
        made = Deposit.objects.create(
            number=number,
            account=account,
            deposit_date=deposit_date,
            slip_no=(slip_no or "").strip()[:50],
            total=total,
            journal_entry=entry,
            created_by=user,
        )
        for r in found:
            DepositLine.objects.create(deposit=made, receipt=r, amount=r.amount_lkr)
        mark_used(account)
        return made


def deposits(user: User) -> QuerySet[Deposit]:
    if not can_view(user):
        return Deposit.objects.none()
    return Deposit.objects.select_related("account", "journal_entry", "created_by")


# --- Cleared ----------------------------------------------------------------------------


def clear_issued(user: User, leaf: ChequeLeaf, cleared_on) -> ChequeClearance:
    _handler(user)
    cleared_on = _day(cleared_on, "date it cleared")
    with audit_context("cheque_cleared"), transaction.atomic():
        leaf = ChequeLeaf.objects.select_for_update().get(pk=leaf.pk)
        payment = getattr(leaf, "payment", None)
        if leaf.status != ChequeLeaf.Status.ISSUED or payment is None or payment.cancelled:
            raise BankingError(f"Cheque {leaf.number} is not an issued cheque of a payment.")
        if ChequeClearance.objects.filter(leaf=leaf).exists():
            raise BankingError(f"Cheque {leaf.number} is already marked cleared.")
        if cleared_on < payment.payment_date:
            raise BankingError("A cheque clears on or after the payment date.")
        return ChequeClearance.objects.create(leaf=leaf, cleared_on=cleared_on, created_by=user)


def clear_received(user: User, receipt: CustomerReceipt, cleared_on) -> ChequeClearance:
    _handler(user)
    cleared_on = _day(cleared_on, "date it cleared")
    with audit_context("cheque_cleared"), transaction.atomic():
        receipt = CustomerReceipt.objects.select_for_update().get(pk=receipt.pk)
        line = DepositLine.objects.filter(receipt=receipt).select_related("deposit").first()
        if receipt.status != RS.POSTED or line is None:
            raise BankingError(f"The cheque of receipt {receipt.number} has not been deposited.")
        if ChequeClearance.objects.filter(deposit_line=line).exists():
            raise BankingError(f"The cheque of receipt {receipt.number} is already cleared.")
        if cleared_on < line.deposit.deposit_date:
            raise BankingError("A cheque clears on or after the day it was deposited.")
        return ChequeClearance.objects.create(
            deposit_line=line, cleared_on=cleared_on, created_by=user
        )


# --- Returned cheques ---------------------------------------------------------------------


def return_cheque(user: User, receipt: CustomerReceipt, *, returned_on, reason: str):
    """The customer's cheque came back unpaid: reverse its receipt."""
    _handler(user)
    returned_on = _day(returned_on, "date it was returned")
    reason = (reason or "").strip()
    if not reason:
        raise BankingError("Give the reason the bank returned the cheque.")
    with audit_context("cheque_returned", reason), transaction.atomic():
        receipt = (
            CustomerReceipt.objects.select_for_update()
            .select_related("customer", "journal_entry")
            .get(pk=receipt.pk)
        )
        if receipt.method != CustomerReceipt.Method.CHEQUE or receipt.status != RS.POSTED:
            raise BankingError(f"Receipt {receipt.number} is not a posted cheque receipt.")
        line = DepositLine.objects.filter(receipt=receipt).select_related("deposit").first()
        if line is not None and ChequeClearance.objects.filter(deposit_line=line).exists():
            raise BankingError(
                f"The cheque of receipt {receipt.number} has cleared; a cleared cheque is not "
                "returned. Record a refund or a journal instead."
            )
        start = line.deposit.deposit_date if line else receipt.journal_entry.entry_date
        if returned_on < start:
            raise BankingError("A cheque is returned on or after the day it was deposited.")
        undeposited = _undeposited()
        bank = line.deposit.account.ledger_account if line else None
        text = f"Cheque returned: receipt {receipt.number} from {receipt.customer.name}"
        lines = []
        for old in receipt.journal_entry.lines.select_related("account", "division"):
            account = old.account
            if bank is not None and account.pk == undeposited.pk:
                account = bank  # the money had gone into the bank; it comes out of it
            lines.append(
                journal.Line(
                    account=account,
                    debit=old.credit,
                    credit=old.debit,
                    division=old.division,
                    supplier=old.supplier,
                    customer=old.customer,
                    description=text,
                )
            )
        try:
            entry = journal.post(
                user,
                entry_date=returned_on,
                narration=f"{text}: {reason}",
                lines=lines,
                source_type="cheque_return",
                source_id=receipt.number,
            )
        except AccountingError as error:
            raise BankingError(str(error)) from None
        receipt.status = RS.RETURNED
        receipt.returned_on = returned_on
        receipt.return_reason = reason[:2000]
        receipt.return_entry = entry
        receipt.save(update_fields=["status", "returned_on", "return_reason", "return_entry"])
        return receipt
