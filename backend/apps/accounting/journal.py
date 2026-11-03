"""The journal (the ledger) and accounting periods (spec 3, backlog P0-16).

`post()` is the only way anything reaches the ledger. Other services (vouchers, payments,
invoices…) call it inside their own saving transaction with the lines they want posted.
The rules, also enforced by the database (migration 0003):

- total debits equal total credits, in exact decimals (rules 1 and 2);
- posted entries are never changed or deleted; `reverse()` posts the mirror entry (rule 3);
- nothing is posted into a closed month;
- every income and expense line carries a division (spec 3.1);
- lines go only to active accounts that have not been merged.

Months are closed and reopened by the Director (the "close_period" action).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.core.organisation import mark_division_used

from . import services
from .catalogue import PROFIT_AND_LOSS, TYPES, section_of
from .models import Account, AccountingPeriod, JournalEntry, JournalLine
from .services import AccountingError

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("9999999999999999.99")  # NUMERIC(18,2)
MAX_LINES = 500


@dataclass
class Line:
    account: Account
    debit: Decimal | str | int = Decimal("0")
    credit: Decimal | str | int = Decimal("0")
    division: Division | None = None
    supplier: object = None  # apps.masters.models.Supplier
    description: str = ""
    customer: object = None  # apps.masters.models.Customer, on receivables lines (P2-05)


def _amount(value, where: str) -> Decimal:
    if isinstance(value, float):
        raise AccountingError(f"{where}: amounts must be exact decimals, not floating point.")
    try:
        amount = Decimal(str(value if value not in (None, "") else "0").replace(",", ""))
    except InvalidOperation:
        raise AccountingError(f"{where}: the amount is not a number.") from None
    if not amount.is_finite() or amount < 0:
        raise AccountingError(f"{where}: amounts cannot be negative.")
    if amount != amount.quantize(CENT):
        raise AccountingError(f"{where}: amounts are to the cent (two decimals).")
    if amount > MAX_AMOUNT:
        raise AccountingError(f"{where}: the amount is too large.")
    return amount.quantize(CENT)


def month_of(day: date) -> date:
    return day.replace(day=1)


def is_closed(day: date) -> bool:
    return AccountingPeriod.objects.filter(month=month_of(day), is_closed=True).exists()


def _lock_period(day: date) -> AccountingPeriod:
    """Lock the month's row while posting, so it cannot be closed half-way through."""
    month = month_of(day)
    try:
        with transaction.atomic():
            AccountingPeriod.objects.get_or_create(month=month)
    except IntegrityError:
        pass  # created at the same moment by another posting
    return AccountingPeriod.objects.select_for_update().get(month=month)


def _check_lines(lines: list[Line]) -> list[tuple[Line, Decimal, Decimal]]:
    if len(lines) < 2:
        raise AccountingError("A journal entry needs at least two lines.")
    if len(lines) > MAX_LINES:
        raise AccountingError(f"A journal entry can have at most {MAX_LINES} lines.")
    checked = []
    for number, line in enumerate(lines, start=1):
        where = f"Line {number}"
        debit, credit = _amount(line.debit, where), _amount(line.credit, where)
        if (debit > 0) == (credit > 0):
            raise AccountingError(f"{where}: enter either a debit or a credit, more than zero.")
        account = line.account
        if account.merged_into_id:
            raise AccountingError(
                f"{where}: {account.name} was merged into {account.merged_into.name}; "
                "post to that account."
            )
        if not account.is_active:
            raise AccountingError(f"{where}: {account.name} is inactive.")
        if section_of(account.account_type) == PROFIT_AND_LOSS and line.division is None:
            raise AccountingError(
                f"{where}: {account.name} is an income or expense account, so the line "
                "needs a division."
            )
        if account.account_type == "accounts_receivable" and line.customer is None:
            raise AccountingError(
                f"{where}: {account.name} is a receivables account, so the line needs the customer."
            )
        if line.division is not None and not line.division.is_active:
            raise AccountingError(f"{where}: division {line.division.code} is deactivated.")
        if len(line.description or "") > 500:
            raise AccountingError(f"{where}: the description can have at most 500 characters.")
        checked.append((line, debit, credit))
    debits = sum((d for _, d, _ in checked), Decimal("0"))
    credits = sum((c for _, _, c in checked), Decimal("0"))
    if debits != credits:
        raise AccountingError(
            f"The entry does not balance: debits {debits:,.2f}, credits {credits:,.2f}."
        )
    return checked


def post(
    user: User,
    *,
    entry_date: date,
    narration: str,
    lines: list[Line],
    source_type: str = "manual",
    source_id: str = "",
    reversal_of: JournalEntry | None = None,
) -> JournalEntry:
    """Post a balanced entry. Its number comes from the "journal" number series inside this
    transaction (rule 10). Raises AccountingError and saves nothing if any rule is broken."""
    narration = " ".join((narration or "").split())
    if not narration:
        raise AccountingError("The narration is required.")
    if len(narration) > 500:
        raise AccountingError("The narration can have at most 500 characters.")
    if not source_type:
        raise AccountingError("The source of the entry is required.")
    checked = _check_lines(lines)
    with audit_context("journal_posted"), transaction.atomic():
        period = _lock_period(entry_date)
        if period.is_closed:
            raise AccountingError(
                f"The period {entry_date:%Y-%m} is closed: nothing can be posted into it."
            )
        try:
            number = allocate("journal", on_date=entry_date)
        except NumberSeriesError as error:
            raise AccountingError(str(error)) from None
        entry = JournalEntry.objects.create(
            number=number,
            entry_date=entry_date,
            source_type=source_type,
            source_id=str(source_id or ""),
            narration=narration,
            reversal_of=reversal_of,
            posted_by=user,
        )
        JournalLine.objects.bulk_create(
            JournalLine(
                entry=entry,
                line_no=number,
                account=line.account,
                division=line.division,
                supplier=line.supplier,
                customer=line.customer,
                description=(line.description or "").strip(),
                debit=debit,
                credit=credit,
            )
            for number, (line, debit, credit) in enumerate(checked, start=1)
        )
        _mark_used(checked)
        return entry


def _mark_used(checked) -> None:
    from apps.masters.services import mark_used as mark_master_used

    seen = set()
    for line, _, _ in checked:
        for obj, mark in (
            (line.account, services.mark_used),
            (line.division, mark_division_used),
            (line.supplier, mark_master_used),
        ):
            if obj is not None and (type(obj), obj.pk) not in seen:
                seen.add((type(obj), obj.pk))
                mark(obj)


def reverse(user: User, entry: JournalEntry, *, reason: str, on_date: date | None = None):
    """Post the mirror entry of `entry` (debits and credits swapped), linked to it. The
    original stays as it was. By default it is dated like the original when that month is
    open, otherwise today."""
    reason = (reason or "").strip()
    if not reason:
        raise AccountingError("Give a reason for reversing the entry.")
    with transaction.atomic():
        entry = JournalEntry.objects.select_for_update().get(pk=entry.pk)
        if entry.reversal_of_id:
            raise AccountingError(
                f"{entry.number} is itself a reversal; post a new entry instead of reversing it."
            )
        if JournalEntry.objects.filter(reversal_of=entry).exists():
            raise AccountingError(f"{entry.number} has already been reversed.")
        if on_date is None:
            on_date = entry.entry_date if not is_closed(entry.entry_date) else timezone.localdate()
        lines = []
        for line in entry.lines.select_related("account", "division", "supplier"):
            account = line.account
            if account.merged_into_id:
                account = Account.objects.get(pk=services.surviving(account.pk))
            if not account.is_active:
                raise AccountingError(
                    f"{account.name} is inactive; make it active to reverse {entry.number}."
                )
            lines.append(
                Line(
                    account=account,
                    debit=line.credit,
                    credit=line.debit,
                    division=line.division,
                    supplier=line.supplier,
                    customer=line.customer,
                    description=line.description,
                )
            )
        return post(
            user,
            entry_date=on_date,
            narration=f"Reversal of {entry.number}: {reason}",
            lines=lines,
            source_type="reversal",
            source_id=entry.number,
            reversal_of=entry,
        )


# --- Periods ----------------------------------------------------------------------------


def _director(user: User) -> None:
    if not effective_access(user).can("close_period"):
        raise AccountingError("Only the Director can close and reopen accounting periods.")


def set_closed(user: User, month: date, closed: bool, reason: str = "") -> AccountingPeriod:
    """Close a month (nothing more can be posted into it) or reopen it (reason required)."""
    _director(user)
    month = month_of(month)
    if not closed and not (reason or "").strip():
        raise AccountingError("Give a reason for reopening the period.")
    if closed and month >= month_of(timezone.localdate()):
        raise AccountingError("Only a month that has ended can be closed.")
    event = "period_closed" if closed else "period_reopened"
    with audit_context(event, reason), transaction.atomic():
        period = _lock_period(month)
        if period.is_closed == closed:
            state = "closed" if closed else "open"
            raise AccountingError(f"The period {month:%Y-%m} is already {state}.")
        period.is_closed = closed
        period.changed_by = user
        period.changed_at = timezone.now()
        period.save()
        return period


def periods(year: int) -> list[dict]:
    """The twelve months of a calendar year with their state and number of entries."""
    stored = {p.month: p for p in AccountingPeriod.objects.filter(month__year=year)}
    counts = defaultdict(int)
    for day in JournalEntry.objects.filter(entry_date__year=year).values_list(
        "entry_date", flat=True
    ):
        counts[month_of(day)] += 1
    result = []
    for m in range(1, 13):
        month = date(year, m, 1)
        period = stored.get(month)
        result.append(
            {
                "month": month.strftime("%Y-%m"),
                "is_closed": bool(period and period.is_closed),
                "changed_by": period.changed_by.full_name if period and period.changed_by else None,
                "changed_at": period.changed_at if period else None,
                "entries": counts[month],
            }
        )
    return result


# --- Reports ----------------------------------------------------------------------------


def profit_and_loss(
    date_from: date, date_to: date, division: Division | None = None
) -> dict[int, Decimal]:
    """Profit and loss per account for a date range, for one division or the whole company.
    Income is positive, costs negative (credit minus debit), so the sum is the profit.
    Merged accounts' entries are counted under the account that replaced them."""
    if date_to < date_from:
        raise AccountingError("The end date is before the start date.")
    pnl_types = [code for code, (_, section, _) in TYPES.items() if section == PROFIT_AND_LOSS]
    lines = JournalLine.objects.filter(
        entry__entry_date__gte=date_from,
        entry__entry_date__lte=date_to,
        account__account_type__in=pnl_types,
    )
    if division is not None:
        lines = lines.filter(division=division)
    totals = {
        row["account"]: (row["credits"] or Decimal("0")) - (row["debits"] or Decimal("0"))
        for row in lines.values("account").annotate(debits=Sum("debit"), credits=Sum("credit"))
    }
    return services.roll_up(totals)


def has_closed_entries(account: Account) -> bool:
    """True if the account has entries in a closed month (its type is then fixed)."""
    closed = AccountingPeriod.objects.filter(is_closed=True).values_list("month", flat=True)
    months = {
        month_of(d) for d in account.journal_lines.values_list("entry__entry_date", flat=True)
    }
    return bool(months & set(closed))
