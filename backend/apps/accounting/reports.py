"""Trial balance, balance sheet and general ledger (backlog P2-03, spec 6 and 3).

All three are read from posted journal lines only, so they always agree with each other and
with the profit and loss. Balances are worked out as debit minus credit; a report turns them
into the sign a reader expects (assets positive, liabilities and equity positive).

- Merged accounts' history is shown under the account that replaced them.
- Sub-accounts can be shown, or rolled up into their top-level account.
- For one division, only lines carrying that division count. Bank, loans and equity belong
  to the company (spec 3.1), so a division's balance sheet shows the difference as funded
  at company level.
- There is no year-end close yet (P2-23): the profit and loss to date is shown inside
  equity as "profit not yet closed to retained earnings", so the balance sheet balances.
"""

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import QuerySet, Sum

from apps.core.models import Division

from . import services
from .catalogue import ASSETS, EQUITY, LIABILITIES, PROFIT_AND_LOSS, TYPE_ORDER, TYPES
from .models import Account, JournalLine
from .services import AccountingError

ZERO = Decimal("0.00")
COMPARE = ("", "month", "year")
MAX_LEDGER_LINES = 5000


# --- Dates ------------------------------------------------------------------------------------


def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def compare_date(as_at: date, compare: str) -> date | None:
    """The date of the comparison column: the end of the previous month, or the same day a
    year earlier (29 February becomes 28 February)."""
    if compare not in COMPARE:
        raise AccountingError("Compare with the previous month or the previous year.")
    if compare == "month":
        return as_at.replace(day=1) - timedelta(days=1)
    if compare == "year":
        try:
            return as_at.replace(year=as_at.year - 1)
        except ValueError:
            return as_at.replace(year=as_at.year - 1, day=28)
    return None


# --- Balances ---------------------------------------------------------------------------------


def _lines(division: Division | None) -> QuerySet[JournalLine]:
    lines = JournalLine.objects.all()
    if division is not None:
        lines = lines.filter(division=division)
    return lines


def _top(account_id: int, parents: dict[int, int | None]) -> int:
    seen = set()
    while parents.get(account_id) and account_id not in seen:
        seen.add(account_id)
        account_id = parents[account_id]
    return account_id


def balances(
    as_at: date,
    division: Division | None = None,
    *,
    since: date | None = None,
    roll_up_subaccounts: bool = False,
) -> dict[int, Decimal]:
    """Debit minus credit per account, for entries dated up to `as_at` (and from `since`)."""
    lines = _lines(division).filter(entry__entry_date__lte=as_at)
    if since is not None:
        lines = lines.filter(entry__entry_date__gte=since)
    totals = {
        row["account"]: (row["debits"] or ZERO) - (row["credits"] or ZERO)
        for row in lines.values("account").annotate(debits=Sum("debit"), credits=Sum("credit"))
    }
    totals = services.roll_up(totals)
    if roll_up_subaccounts:
        parents = dict(Account.objects.values_list("pk", "parent_id"))
        rolled: dict[int, Decimal] = defaultdict(Decimal)
        for pk, amount in totals.items():
            rolled[_top(pk, parents)] += amount
        totals = dict(rolled)
    return {pk: amount for pk, amount in totals.items() if amount != 0}


@dataclass
class AccountRef:
    id: int
    number: str
    name: str
    account_type: str


def _accounts(ids) -> dict[int, AccountRef]:
    found = Account.objects.select_related("parent").in_bulk(list(ids))
    return {
        pk: AccountRef(pk, a.number, services.full_name(a), a.account_type)
        for pk, a in found.items()
    }


def _order(ref: AccountRef):
    return (TYPE_ORDER[ref.account_type], ref.number or "~", ref.name.lower())


# --- Trial balance ----------------------------------------------------------------------------


@dataclass
class TrialRow:
    account: AccountRef
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    compare_debit: Decimal = ZERO
    compare_credit: Decimal = ZERO


def _split(amount: Decimal) -> tuple[Decimal, Decimal]:
    return (amount, ZERO) if amount > 0 else (ZERO, -amount)


def trial_balance(
    as_at: date,
    division: Division | None = None,
    *,
    compare: str = "",
    roll_up_subaccounts: bool = False,
) -> tuple[list[TrialRow], date | None]:
    """Every account with a balance at the date, as a debit or a credit."""
    other = compare_date(as_at, compare)
    now = balances(as_at, division, roll_up_subaccounts=roll_up_subaccounts)
    then = balances(other, division, roll_up_subaccounts=roll_up_subaccounts) if other else {}
    refs = _accounts(set(now) | set(then))
    rows = []
    for pk in sorted(refs, key=lambda pk: _order(refs[pk])):
        debit, credit = _split(now.get(pk, ZERO))
        compare_debit, compare_credit = _split(then.get(pk, ZERO))
        rows.append(TrialRow(refs[pk], debit, credit, compare_debit, compare_credit))
    return rows, other


# --- Balance sheet ----------------------------------------------------------------------------


@dataclass
class SheetRow:
    label: str
    amount: Decimal
    compare: Decimal = ZERO
    account: AccountRef | None = None
    kind: str = "account"  # account, profit, company, total


@dataclass
class Section:
    key: str
    title: str
    rows: list[SheetRow] = field(default_factory=list)

    def total(self) -> tuple[Decimal, Decimal]:
        return (
            sum((r.amount for r in self.rows), ZERO),
            sum((r.compare for r in self.rows), ZERO),
        )


SHEET_SECTIONS = {ASSETS: "Assets", LIABILITIES: "Liabilities", EQUITY: "Equity"}
PROFIT_LABEL = "Profit to date, not yet closed to retained earnings"
COMPANY_LABEL = "Funded at company level (bank, loans and equity not held by the division)"


def balance_sheet(
    as_at: date,
    division: Division | None = None,
    *,
    compare: str = "",
    roll_up_subaccounts: bool = False,
) -> tuple[list[Section], date | None]:
    """Assets, liabilities and equity at the date. Assets are positive debit balances;
    liabilities and equity positive credit balances."""
    other = compare_date(as_at, compare)
    now = balances(as_at, division, roll_up_subaccounts=roll_up_subaccounts)
    then = balances(other, division, roll_up_subaccounts=roll_up_subaccounts) if other else {}
    refs = _accounts(set(now) | set(then))
    sections = {key: Section(key, title) for key, title in SHEET_SECTIONS.items()}
    profit_now = profit_then = ZERO
    for pk in sorted(refs, key=lambda pk: _order(refs[pk])):
        ref = refs[pk]
        section = TYPES[ref.account_type][1]
        a, b = now.get(pk, ZERO), then.get(pk, ZERO)
        if section == PROFIT_AND_LOSS:
            profit_now -= a
            profit_then -= b
            continue
        sign = 1 if section == ASSETS else -1
        label = f"{ref.number} {ref.name}".strip()
        sections[section].rows.append(SheetRow(label, sign * a, sign * b, ref))
    if profit_now or profit_then:
        sections[EQUITY].rows.append(SheetRow(PROFIT_LABEL, profit_now, profit_then, kind="profit"))
    if division is not None:
        assets = sections[ASSETS].total()
        claims = [
            x + y
            for x, y in zip(sections[LIABILITIES].total(), sections[EQUITY].total(), strict=True)
        ]
        gap = (assets[0] - claims[0], assets[1] - claims[1])
        if any(gap):
            sections[EQUITY].rows.append(SheetRow(COMPANY_LABEL, *gap, kind="company"))
    return list(sections.values()), other


# --- General ledger ---------------------------------------------------------------------------


@dataclass
class LedgerLine:
    entry_id: int
    number: str
    entry_date: date
    narration: str
    description: str
    division: str
    supplier: str
    debit: Decimal
    credit: Decimal
    balance: Decimal
    source_type: str
    source_id: str


@dataclass
class LedgerAccount:
    account: AccountRef
    opening: Decimal
    lines: list[LedgerLine]
    closing: Decimal


def _family(account: Account, with_subaccounts: bool) -> set[int]:
    """The account, the accounts merged into it and, if asked, its sub-accounts (and the
    accounts merged into those)."""
    ids = {account.pk}
    if with_subaccounts:
        ids |= services.descendant_ids(account)
    merged = list(
        Account.objects.filter(merged_into__isnull=False).values_list("pk", "merged_into_id")
    )
    grew = True
    while grew:
        grew = False
        for pk, into in merged:
            if into in ids and pk not in ids:
                ids.add(pk)
                grew = True
    return ids


def general_ledger(
    date_from: date,
    date_to: date,
    division: Division | None = None,
    *,
    account: Account | None = None,
    with_subaccounts: bool = False,
) -> list[LedgerAccount]:
    """For one account (or every account that moved), the balance brought forward, each line
    in the period with a running balance, and the balance carried forward."""
    if date_to < date_from:
        raise AccountingError("The end date is before the start date.")
    lines = _lines(division)
    if account is not None:
        family = _family(account, with_subaccounts)
        targets = {pk: account.pk for pk in family}
        lines = lines.filter(account_id__in=family)
    else:
        targets = None
        merged = dict(
            Account.objects.filter(merged_into__isnull=False).values_list("pk", "merged_into_id")
        )
    before = {
        row["account"]: (row["d"] or ZERO) - (row["c"] or ZERO)
        for row in lines.filter(entry__entry_date__lt=date_from)
        .values("account")
        .annotate(d=Sum("debit"), c=Sum("credit"))
    }
    period = list(
        lines.filter(entry__entry_date__gte=date_from, entry__entry_date__lte=date_to)
        .select_related("entry", "division", "supplier")
        .order_by("entry__entry_date", "entry__number", "line_no")[: MAX_LEDGER_LINES + 1]
    )
    if len(period) > MAX_LEDGER_LINES:
        raise AccountingError(
            f"More than {MAX_LEDGER_LINES:,} lines: choose one account or a shorter period."
        )

    def target(pk: int) -> int:
        """Merged accounts' lines are shown under the account that replaced them."""
        if targets is not None:
            return targets[pk]
        hops = 0
        while pk in merged and hops <= len(merged):
            pk, hops = merged[pk], hops + 1
        return pk

    openings: dict[int, Decimal] = defaultdict(Decimal)
    for pk, amount in before.items():
        openings[target(pk)] += amount
    moved: dict[int, list[JournalLine]] = defaultdict(list)
    for line in period:
        moved[target(line.account_id)].append(line)
    ids = set(moved) | {pk for pk, amount in openings.items() if amount}
    if account is not None:
        ids.add(account.pk)
    refs = _accounts(ids)
    result = []
    for pk in sorted(refs, key=lambda pk: _order(refs[pk])):
        running = openings.get(pk, ZERO)
        rows = []
        for line in moved.get(pk, []):
            running += line.debit - line.credit
            rows.append(
                LedgerLine(
                    entry_id=line.entry_id,
                    number=line.entry.number,
                    entry_date=line.entry.entry_date,
                    narration=line.entry.narration,
                    description=line.description,
                    division=line.division.code if line.division else "",
                    supplier=line.supplier.name if line.supplier else "",
                    debit=line.debit,
                    credit=line.credit,
                    balance=running,
                    source_type=line.entry.source_type,
                    source_id=line.entry.source_id,
                )
            )
        result.append(LedgerAccount(refs[pk], openings.get(pk, ZERO), rows, running))
    return result
