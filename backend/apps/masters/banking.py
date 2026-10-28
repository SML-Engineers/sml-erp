"""Company bank and cash accounts, cheque books and division defaults (backlog P0-14).

The Accountant (Banking: Manage) keeps the accounts. A cheque number is used once, ever:
issued on a payment (P1-07) or recorded as spoiled, and kept for good.
"""

import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, User

from .models import ChequeBook, ChequeLeaf, CompanyAccount, Currency, DivisionBankDefault
from .services import MastersError, is_in_use, normalise_code

ACCOUNT_NUMBER = re.compile(r"^[A-Z0-9][A-Z0-9 -]{3,33}$")
MAX_BOOK_LEAVES = 1000


def _manage(user: User) -> None:
    if not effective_access(user).has("banking", "manage"):
        raise MastersError("Only the Accountant can change bank and cash accounts.")


def _money(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        raise MastersError("The petty cash float must be an amount.") from None
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise MastersError("The petty cash float must be more than zero, to the cent.")
    return amount


def _clean(values: dict, kind: str) -> dict:
    cleaned = {}
    for field in ("name", "bank_name", "branch"):
        if field in values:
            cleaned[field] = (values[field] or "").strip()
    if "name" in cleaned and not cleaned["name"]:
        raise MastersError("The account name is required.")
    if "account_number" in values:
        number = (values["account_number"] or "").strip().upper()
        if number and not ACCOUNT_NUMBER.match(number):
            raise MastersError(
                "The account number must be 4 to 34 letters, digits, spaces or dashes."
            )
        cleaned["account_number"] = number
    if "currency" in values:
        currency = Currency.objects.filter(
            code=(values["currency"] or "").upper(), is_active=True
        ).first()
        if currency is None:
            raise MastersError("Choose an active currency.")
        cleaned["currency"] = currency
    if "division" in values:
        code = (values["division"] or "").strip().upper()
        cleaned["division"] = Division.objects.filter(code=code).first() if code else None
        if code and cleaned["division"] is None:
            raise MastersError(f"Unknown division {code}.")
    if "custodian" in values:
        cleaned["custodian"] = (
            User.objects.filter(pk=values["custodian"], is_active=True).first()
            if values["custodian"]
            else None
        )
        if values["custodian"] and cleaned["custodian"] is None:
            raise MastersError("The custodian must be an active user.")
    if "float_amount" in values:
        cleaned["float_amount"] = _money(values["float_amount"])
    if "ledger_account" in values:
        cleaned["ledger_account"] = _ledger(values["ledger_account"])
    return cleaned


def _ledger(account_id):
    """The account's ledger in the chart of accounts: an active Bank-type account."""
    from apps.accounting.models import Account

    if account_id in (None, ""):
        return None
    ledger = Account.objects.filter(pk=account_id).first()
    if ledger is None or ledger.account_type != "bank" or not ledger.is_active:
        raise MastersError("The ledger account must be an active account of type Bank.")
    return ledger


def _check_kind(account: CompanyAccount) -> None:
    if account.is_bank:
        if not account.bank_name or not account.account_number:
            raise MastersError("A bank account needs the bank name and the account number.")
        if account.custodian_id or account.float_amount is not None:
            raise MastersError("Only petty cash has a custodian and a float.")
    else:
        account.bank_name = account.branch = account.account_number = ""
        if account.kind == CompanyAccount.Kind.PETTY_CASH:
            if account.custodian_id is None or account.float_amount is None:
                raise MastersError("Petty cash needs a custodian and its float amount.")
    dup = CompanyAccount.objects.filter(
        bank_name__iexact=account.bank_name, account_number=account.account_number
    ).exclude(pk=account.pk)
    if account.account_number and dup.exists():
        raise MastersError("That bank account is already in the list.")
    if account.ledger_account_id:
        other = (
            CompanyAccount.objects.filter(ledger_account_id=account.ledger_account_id)
            .exclude(pk=account.pk)
            .first()
        )
        if other:
            raise MastersError(f"That ledger account already belongs to {other.code}.")


def create_account(user: User, *, code, kind, reason="", **values) -> CompanyAccount:
    _manage(user)
    if kind not in CompanyAccount.Kind.values:
        raise MastersError("Choose the kind of account.")
    code = normalise_code(code, "account")
    cleaned = _clean(values, kind)
    if not cleaned.get("name"):
        raise MastersError("The account name is required.")
    with audit_context("company_account_created", reason), transaction.atomic():
        if CompanyAccount.objects.filter(code=code).exists():
            raise MastersError(f"The account code {code} is already used.")
        cleaned.setdefault("currency", Currency.objects.get(is_base=True))
        account = CompanyAccount(code=code, kind=kind, **cleaned)
        _check_kind(account)
        account.save()
        return account


def update_account(user: User, account: CompanyAccount, values: dict, reason: str = ""):
    _manage(user)
    with transaction.atomic():
        account = CompanyAccount.objects.select_for_update().get(pk=account.pk)
        used = is_in_use(account)
        event = "company_account_changed"
        if "code" in values:
            code = normalise_code(values["code"], "account")
            if code != account.code:
                if used:
                    raise MastersError("This account has been used, so its code cannot change.")
                if CompanyAccount.objects.filter(code=code).exclude(pk=account.pk).exists():
                    raise MastersError(f"The account code {code} is already used.")
                account.code = code
        cleaned = _clean(values, account.kind)
        if used and any(
            k in cleaned and cleaned[k] != getattr(account, k)
            for k in ("account_number", "bank_name", "currency")
        ):
            raise MastersError(
                "This account has been used, so its bank, number and currency cannot change."
            )
        if (
            used
            and account.ledger_account_id
            and "ledger_account" in cleaned
            and cleaned["ledger_account"] != account.ledger_account
        ):
            raise MastersError("This account has been used, so its ledger account cannot change.")
        for key, value in cleaned.items():
            setattr(account, key, value)
        if "is_active" in values and bool(values["is_active"]) != account.is_active:
            if not values["is_active"]:
                if not (reason or "").strip():
                    raise MastersError("Give a reason for closing the account.")
                if account.default_for.exists():
                    raise MastersError(
                        "This account is a division's default; choose another default first."
                    )
                event = "company_account_closed"
            else:
                event = "company_account_reopened"
            account.is_active = bool(values["is_active"])
        _check_kind(account)
        with audit_context(event, reason):
            account.save()
        return account


def set_division_default(user: User, division: Division, account: CompanyAccount | None):
    _manage(user)
    with audit_context("division_bank_default_set"), transaction.atomic():
        if account is None:
            DivisionBankDefault.objects.filter(division=division).delete()
            return None
        if not account.is_bank or not account.is_active:
            raise MastersError("A division's default must be an open bank account.")
        default, _ = DivisionBankDefault.objects.update_or_create(
            division=division, defaults={"account": account}
        )
        return default


# --- Cheque books -----------------------------------------------------------------------


def add_cheque_book(user: User, account: CompanyAccount, *, first, last, digits=6, reason=""):
    _manage(user)
    if account.kind != CompanyAccount.Kind.CURRENT or not account.is_active:
        raise MastersError("Cheque books belong to open bank current accounts.")
    try:
        first, last, digits = int(first), int(last), int(digits)
    except (TypeError, ValueError):
        raise MastersError("Cheque numbers must be whole numbers.") from None
    if first < 1 or last < first:
        raise MastersError("The last cheque number must not be below the first.")
    if last - first + 1 > MAX_BOOK_LEAVES:
        raise MastersError(f"A cheque book can have at most {MAX_BOOK_LEAVES} leaves.")
    if not 1 <= digits <= 12 or len(str(last)) > digits:
        raise MastersError("The number of digits does not fit the cheque numbers.")
    with audit_context("cheque_book_added", reason), transaction.atomic():
        CompanyAccount.objects.select_for_update().get(pk=account.pk)
        overlap = ChequeBook.objects.filter(
            account=account, first_number__lte=last, last_number__gte=first
        )
        if overlap.exists():
            raise MastersError("These numbers overlap a cheque book already entered.")
        return ChequeBook.objects.create(
            account=account, first_number=first, last_number=last, digits=digits, created_by=user
        )


def format_cheque(book: ChequeBook, number: int) -> str:
    return str(number).zfill(book.digits)


def book_summary(book: ChequeBook) -> dict:
    used = book.leaves.count()
    total = book.last_number - book.first_number + 1
    return {"leaves": total, "used": used, "left": total - used, "next": next_in_book(book)}


def next_in_book(book: ChequeBook) -> int | None:
    used = set(book.leaves.values_list("number", flat=True))
    for number in range(book.first_number, book.last_number + 1):
        if number not in used:
            return number
    return None


def next_cheque(account: CompanyAccount) -> tuple[ChequeBook, int] | None:
    """The next unused leaf, from the oldest active book."""
    for book in account.cheque_books.filter(is_active=True).order_by("first_number"):
        number = next_in_book(book)
        if number is not None:
            return book, number
    return None


def _book_for(account: CompanyAccount, number: int) -> ChequeBook:
    book = account.cheque_books.filter(
        first_number__lte=number, last_number__gte=number, is_active=True
    ).first()
    if book is None:
        raise MastersError(f"Cheque {number} is not in an active cheque book of {account.code}.")
    return book


def use_cheque(
    user: User, account: CompanyAccount, number: int, *, status, reason=""
) -> ChequeLeaf:
    """Record a cheque number as issued (by the payment, P1-07) or spoiled. Each number
    can be used once only, ever."""
    can_pay = effective_access(user).can("record_payment")
    if not (can_pay or effective_access(user).has("banking", "manage")):
        raise MastersError("Only the Cashier or the Accountant can use cheque numbers.")
    if status not in ChequeLeaf.Status.values:
        raise MastersError("Unknown cheque status.")
    if status == ChequeLeaf.Status.SPOILED and not (reason or "").strip():
        raise MastersError("Give a reason for spoiling the cheque.")
    with audit_context(f"cheque_{status}", reason), transaction.atomic():
        CompanyAccount.objects.select_for_update().get(pk=account.pk)
        book = _book_for(account, int(number))
        if ChequeLeaf.objects.filter(account=account, number=number).exists():
            raise MastersError(f"Cheque {format_cheque(book, number)} has already been used.")
        return ChequeLeaf.objects.create(
            book=book, account=account, number=number, status=status, reason=reason, used_by=user
        )


def close_book(user: User, book: ChequeBook, reason: str) -> ChequeBook:
    _manage(user)
    if not (reason or "").strip():
        raise MastersError("Give a reason for closing the cheque book.")
    with audit_context("cheque_book_closed", reason), transaction.atomic():
        book = ChequeBook.objects.select_for_update().get(pk=book.pk)
        book.is_active = False
        book.save()
        return book


def search_accounts(rows, text: str):
    text = (text or "").strip()
    return rows.filter(Q(name__icontains=text) | Q(code__iexact=text)) if text else rows
