"""Petty cash, the imprest way (backlog P2-17, spec 6).

- A petty cash account (Settings → Bank and cash accounts, kind "Petty cash") has a custodian
  and a float, the amount it is topped up to.
- The custodian records each small expense with its slip (a photo or PDF): who was paid, what
  for, how much, and the account it should go to if known. Nothing is posted then. What has
  been spent and not yet paid back can never be more than the float.
- The Clerk makes a Petty Cash voucher from the expenses not yet paid back: one line per
  expense, its slip attached, its account filled in for the Accountant to check. It follows
  the three approvals like every voucher; paying it (in cash or by cheque to the custodian)
  posts the expenses (Dr each expense, Cr the bank or cash it was paid from) and the float is
  whole again. If the voucher is rejected, deleted or cancelled, the expenses can go on the
  next one.
"""

import hashlib
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounting.models import Account
from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters.models import CompanyAccount, Supplier
from apps.vouchers import services as vouchers
from apps.vouchers.models import Voucher, VoucherAttachment, VoucherLine, VoucherType
from apps.vouchers.services import LineInput, VoucherError

from .models import PettyExpense
from .services import BankingError

ZERO = Decimal("0")
CENT = Decimal("0.01")
FREED = (Voucher.Status.DELETED, Voucher.Status.REJECTED, Voucher.Status.CANCELLED)
FILE_TYPES = {b"%PDF-": "application/pdf", b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png"}
MAX_BYTES = 20 * 1024 * 1024
NOT_TO_CODE = ("accounts_receivable", "accounts_payable", "bank")


def is_custodian(user: User, account: CompanyAccount) -> bool:
    return account.custodian_id == user.pk


def can_keep(user: User, account: CompanyAccount) -> bool:
    """The custodian records the expenses; the Accountant may too."""
    return is_custodian(user, account) or effective_access(user).has("banking", "enter")


def floats(user: User) -> QuerySet[CompanyAccount]:
    rows = CompanyAccount.objects.filter(kind=CompanyAccount.Kind.PETTY_CASH, is_active=True)
    access = effective_access(user)
    if access.has("banking", "view") or access.has("vouchers", "enter"):
        return rows
    return rows.filter(custodian=user)


def _current(voucher: Voucher | None) -> Voucher | None:
    """The voucher that now carries the expense: an amended voucher's latest revision."""
    while voucher is not None and voucher.status == Voucher.Status.AMENDED:
        latest = voucher.revisions.order_by("-revision", "-id").first()
        if latest is None:
            break
        voucher = latest
    return voucher


def status(expense: PettyExpense) -> str:
    voucher = _current(expense.voucher)
    if voucher is None or voucher.status in FREED:
        return "open"
    if voucher.status == Voucher.Status.PAID:
        return "paid_back"
    return "on_voucher"


def figures(account: CompanyAccount) -> dict:
    """The float, what has been spent and not yet paid back, and the cash that should be in
    the box."""
    spent = ZERO
    waiting = ZERO
    for expense in account.petty_expenses.select_related("voucher"):
        state = status(expense)
        if state != "paid_back":
            spent += expense.amount
        if state == "open":
            waiting += expense.amount
    float_amount = account.float_amount or ZERO
    return {
        "float": float_amount,
        "spent": spent,
        "not_on_voucher": waiting,
        "cash_in_hand": float_amount - spent,
    }


def _money(value) -> Decimal:
    if isinstance(value, float):
        raise BankingError("Amounts must be exact decimals.")
    try:
        amount = Decimal(str(value or "").replace(",", "").strip())
    except InvalidOperation:
        raise BankingError("The amount is not a number.") from None
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(CENT):
        raise BankingError("The amount must be more than zero, to the cent.")
    return amount


def _slip(uploaded) -> tuple[bytes, str, str]:
    if uploaded is None:
        raise BankingError("Attach the slip (a photo or PDF).")
    if uploaded.size > MAX_BYTES:
        raise BankingError("The slip is larger than 20 MB.")
    content = uploaded.read()
    kind = next((t for head, t in FILE_TYPES.items() if content.startswith(head)), None)
    if kind is None:
        raise BankingError("The slip must be a PDF, JPG or PNG.")
    uploaded.seek(0)
    return content, kind, hashlib.sha256(content).hexdigest()


def record(
    user: User,
    account: CompanyAccount,
    *,
    expense_date: date,
    paid_to: str,
    description: str,
    amount,
    slip,
    ledger: Account | None = None,
    division: Division | None = None,
) -> PettyExpense:
    if not isinstance(account, CompanyAccount) or account.kind != CompanyAccount.Kind.PETTY_CASH:
        raise BankingError("Choose a petty cash account.")
    if not account.is_active:
        raise BankingError(f"The petty cash account {account.code} is closed.")
    if not can_keep(user, account):
        raise BankingError("Only the custodian of this petty cash records its expenses.")
    if not account.float_amount:
        raise BankingError(f"{account.code} has no float set; ask the Accountant.")
    if not isinstance(expense_date, date) or expense_date > timezone.localdate():
        raise BankingError("Give the date of the expense (not in the future).")
    paid_to = (paid_to or "").strip()[:150]
    description = (description or "").strip()[:500]
    if not paid_to or not description:
        raise BankingError("Say who was paid and what for.")
    amount = _money(amount)
    if ledger is not None and (not ledger.is_active or ledger.account_type in NOT_TO_CODE):
        raise BankingError(f"{ledger.name} cannot be the account of a petty cash expense.")
    content, kind, digest = _slip(slip)
    with audit_context("petty_expense_recorded"), transaction.atomic():
        CompanyAccount.objects.select_for_update().filter(pk=account.pk).first()
        left = figures(account)["cash_in_hand"]
        if amount > left:
            raise BankingError(
                f"Only {left:,.2f} of the float of {account.float_amount:,.2f} is left; ask "
                "for the petty cash to be topped up first."
            )
        try:
            number = allocate("petty_expense", on_date=expense_date)
        except NumberSeriesError as error:
            raise BankingError(str(error)) from None
        extension = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}[kind]
        expense = PettyExpense(
            number=number,
            account=account,
            expense_date=expense_date,
            paid_to=paid_to,
            description=description,
            amount=amount,
            ledger=ledger,
            division=division or account.division,
            slip_name=(getattr(slip, "name", "") or f"slip{extension}")[-200:],
            slip_type=kind,
            slip_size=len(content),
            slip_sha256=digest,
            created_by=user,
        )
        expense.slip.save(f"{number}-{digest[:12]}{extension}", slip, save=False)
        expense.save()
        return expense


def remove(user: User, expense: PettyExpense) -> None:
    if not can_keep(user, expense.account):
        raise BankingError("Only the custodian of this petty cash removes its expenses.")
    if status(expense) != "open" or expense.voucher_id:
        raise BankingError(f"{expense.number} has been on a voucher and stays.")
    with audit_context("petty_expense_removed"):
        expense.delete()


def replenish(
    user: User,
    account: CompanyAccount,
    *,
    payee: Supplier,
    division: Division | None = None,
    expenses: list[PettyExpense] | None = None,
) -> Voucher:
    """A draft Petty Cash voucher for the expenses not yet paid back (all of them, or those
    chosen), for the Clerk to check and submit."""
    if not effective_access(user).has("vouchers", "enter"):
        raise BankingError("Only the Clerk makes the petty cash voucher.")
    voucher_type = VoucherType.objects.filter(code="PCH", is_active=True).first()
    if voucher_type is None:
        raise BankingError("The Petty Cash voucher type is switched off.")
    division = division or account.division
    if division is None:
        raise BankingError("Choose the division of the voucher.")
    with audit_context("petty_cash_replenished"), transaction.atomic():
        rows = (
            PettyExpense.objects.select_for_update(of=("self",))
            .filter(account=account)
            .select_related("voucher", "ledger", "division")
            .order_by("expense_date", "id")
        )
        if expenses is not None:
            rows = rows.filter(pk__in=[e.pk for e in expenses])
        chosen = [e for e in rows if status(e) == "open"]
        if not chosen:
            raise BankingError("There are no petty cash expenses waiting to be paid back.")
        try:
            voucher = vouchers.save(
                user,
                None,
                voucher_type=voucher_type,
                division=division,
                payee=payee,
                description=f"Petty cash {account.code}: top-up of {len(chosen)} expense(s)",
                lines=[
                    LineInput(
                        amount=e.amount,
                        invoice_no=e.number,
                        invoice_date=e.expense_date,
                        description=f"{e.paid_to}: {e.description}"[:500],
                    )
                    for e in chosen
                ],
            )
        except VoucherError as error:
            raise BankingError(str(error)) from None
        for n, e in enumerate(chosen, start=1):
            if e.ledger_id or e.division_id:
                VoucherLine.objects.filter(voucher=voucher, line_no=n).update(
                    account_id=e.ledger_id, division_id=e.division_id or voucher.division_id
                )
            VoucherAttachment.objects.create(
                voucher=voucher,
                file=e.slip.name,
                file_name=f"{e.number} {e.slip_name}"[:200],
                content_type=e.slip_type,
                size=e.slip_size,
                sha256=e.slip_sha256,
                uploaded_by=user,
            )
            e.voucher = voucher
            e.save(update_fields=["voucher"])
        return voucher
