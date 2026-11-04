"""Cash flow statement (indirect method) and the financial tiles of the home page (backlog
P2-24, spec 6 and 7A).

Cash flow statement, for the company and a period
- Cash is the balance of the Bank-type accounts (bank, cash and petty cash).
- It starts from the profit of the period (as the profit and loss reports it) and explains the
  change in cash by the change in every other balance sheet account over the period, worked
  out from the journal: as every entry balances, the statement always adds up to the actual
  change in cash. Each account's change is placed by its type:
  - operating: depreciation added back (the accumulated depreciation accounts of the asset
    classes), and the change in working capital: receivables, other current assets,
    payables, credit cards and other current liabilities;
  - investing: fixed assets at cost and other (long-term) assets;
  - financing: long-term liabilities and equity.
  An increase in an asset uses cash (shown negative); an increase in a liability or equity
  provides it. The year-end closing entry only moves the profit to retained earnings, so it
  is left out, as in the profit and loss.
- Entries are kept per division, but money moves between divisions through shared bank
  accounts, so the statement is for the company only.

Home page tiles, for the company or a division: this month's profit and loss, the profit of
the financial year so far against the budget, cash (the company's accounts, or those set up
for the division), receivables and payables with what is overdue. Each opens its report.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.models import Division, User

from . import budgets, journal
from .models import Account, JournalLine
from .services import AccountingError

ZERO = Decimal("0")
CASH_TYPES = {"bank"}
WORKING_CAPITAL = {
    "accounts_receivable",
    "other_current_asset",
    "accounts_payable",
    "credit_card",
    "other_current_liability",
}
INVESTING = {"fixed_asset", "other_asset"}
FINANCING = {"long_term_liability", "equity"}
CLOSING = Q(entry__source_type="year_end_close") | Q(
    entry__reversal_of__source_type="year_end_close"
)


@dataclass
class Row:
    label: str
    amount: Decimal
    account: Account | None = None


@dataclass
class Section:
    key: str
    rows: list[Row] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((r.amount for r in self.rows), ZERO)


@dataclass
class Statement:
    date_from: date
    date_to: date
    profit: Decimal
    operating: Section
    investing: Section
    financing: Section
    opening_cash: Decimal
    closing_cash: Decimal

    @property
    def net_change(self) -> Decimal:
        return self.operating.total + self.investing.total + self.financing.total

    @property
    def difference(self) -> Decimal:
        """Nil when the books balance; shown if ever not."""
        return self.closing_cash - self.opening_cash - self.net_change


def _accumulated_ids() -> set[int]:
    from apps.assets.models import AssetClass

    return set(AssetClass.objects.values_list("accumulated_account_id", flat=True))


def _cash(as_at: date, account_ids=None) -> Decimal:
    lines = JournalLine.objects.filter(
        account__account_type__in=CASH_TYPES, entry__entry_date__lte=as_at
    )
    if account_ids is not None:
        lines = lines.filter(account_id__in=account_ids)
    totals = lines.aggregate(d=Sum("debit"), c=Sum("credit"))
    return (totals["d"] or ZERO) - (totals["c"] or ZERO)


def statement(date_from: date, date_to: date) -> Statement:
    if date_to < date_from:
        raise AccountingError("The end date is before the start date.")
    profit = sum(journal.profit_and_loss(date_from, date_to).values(), ZERO)
    moved = (
        JournalLine.objects.filter(
            entry__entry_date__gte=date_from,
            entry__entry_date__lte=date_to,
            account__account_type__in=WORKING_CAPITAL | INVESTING | FINANCING,
        )
        .exclude(CLOSING)
        .values("account")
        .annotate(d=Sum("debit"), c=Sum("credit"))
    )
    accounts = Account.objects.in_bulk({r["account"] for r in moved})
    accumulated = _accumulated_ids()
    operating = Section("operating", [Row("Profit for the period", profit)])
    investing, financing = Section("investing"), Section("financing")
    depreciation = ZERO
    for r in sorted(
        moved, key=lambda r: (accounts[r["account"]].number, accounts[r["account"]].name)
    ):
        account = accounts[r["account"]]
        amount = (r["c"] or ZERO) - (r["d"] or ZERO)  # cash provided (+) or used (-)
        if not amount:
            continue
        name = f"{account.number} {account.name}".strip()
        if account.pk in accumulated:
            depreciation += amount
        elif account.account_type in WORKING_CAPITAL:
            operating.rows.append(Row(f"Change in {name}", amount, account))
        elif account.account_type in INVESTING:
            investing.rows.append(Row(name, amount, account))
        else:
            financing.rows.append(Row(name, amount, account))
    if depreciation:
        operating.rows.insert(1, Row("Depreciation added back", depreciation))
    return Statement(
        date_from=date_from,
        date_to=date_to,
        profit=profit,
        operating=operating,
        investing=investing,
        financing=financing,
        opening_cash=_cash(date_from - timedelta(days=1)),
        closing_cash=_cash(date_to),
    )


# --- Home page tiles -------------------------------------------------------------------------


def _pnl(date_from: date, date_to: date, division: Division | None) -> dict:
    totals = journal.profit_and_loss(date_from, date_to, division)
    types = dict(Account.objects.filter(pk__in=totals).values_list("pk", "account_type"))
    income = sum((v for k, v in totals.items() if types[k] in budgets.INCOME_TYPES), ZERO)
    costs = -sum((v for k, v in totals.items() if types[k] not in budgets.INCOME_TYPES), ZERO)
    return {"income": income, "costs": costs, "profit": income - costs}


def dashboard(user: User, division: Division | None = None, today: date | None = None) -> dict:
    from apps.masters.models import CompanyAccount
    from apps.purchasing import payables
    from apps.sales import receivables

    today = today or timezone.localdate()
    month_start = today.replace(day=1)
    year_start = budgets.year_start_of(today)

    this_month = _pnl(month_start, today, division)
    so_far = _pnl(year_start, today, division)
    planned = budgets.budgeted(year_start, today, division)
    budget_profit = sum(planned.values(), ZERO) if planned else None

    company_accounts = CompanyAccount.objects.filter(is_active=True, ledger_account__isnull=False)
    if division is not None:
        company_accounts = company_accounts.filter(division=division)
    ledger_ids = list(company_accounts.values_list("ledger_account_id", flat=True))
    cash = _cash(today, None if division is None else ledger_ids)

    due_in = [
        i
        for i in receivables.open_items(user, today)
        if division is None or i["invoice"].division_id == division.pk
    ]
    due_out = payables.open_items(today, user=user, division=division)
    return {
        "today": today,
        "division": division.code if division else None,
        "this_month": {"from": month_start, "to": today, **this_month},
        "year_to_date": {
            "from": year_start,
            "to": today,
            "label": budgets.label(year_start),
            **so_far,
            "budget_profit": budget_profit,
        },
        "cash": {"balance": cash, "accounts": len(ledger_ids) if division else None},
        "receivables": {
            "total": sum((i["open_lkr"] for i in due_in), ZERO),
            "overdue": sum((i["open_lkr"] for i in due_in if i["days_overdue"] > 0), ZERO),
            "count": len(due_in),
        },
        "payables": {
            "total": sum((i["open"] for i in due_out), ZERO),
            "overdue": sum((i["open"] for i in due_out if i["days_overdue"] > 0), ZERO),
            "count": len(due_out),
        },
    }
