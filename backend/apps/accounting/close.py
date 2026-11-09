"""Month-end and year-end close (backlog P2-23).

Month end
- Before the Director closes a month, its checklist must be complete:
  1. every bank account reconciled to the month end (Banking → Reconciliation);
  2. the month's depreciation posted, when assets are depreciated in it;
  3. the month-end revaluation posted, when anything is held in a foreign currency;
  4. no manual journal dated in the month left as a draft or waiting for approval;
  5. accruals and prepayments entered (the Accountant ticks it: the system cannot see it);
  6. the payroll of the pay month ending in the month approved (and so posted) for every
     division with employees in it (P2B-13).
  The system checks 1-4 and 6 itself. The Accountant may tick any of them with a note when it is
  done another way or not needed that month (an account with no statement yet, land only);
  ticks are never changed or taken back (database).
- Closing then works as before (nothing more is posted into the month); reopening needs the
  Director and a reason, and is refused for a month of a year that is closed.

Year end
- Once all twelve months of a financial year are closed, the Director closes the year: an
  entry on the first day of the next year moves the balance of every income and cost
  account, per division, to Retained earnings, so the new year starts from nil. The profit
  and loss report leaves that entry out, so the closed year's report is unchanged.
- The Director may reopen the year, with a reason: the entry is reversed, and the year can
  be closed again later. Reopening a month of the year needs the year reopened first.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, User

from . import journal
from .budgets import label, months, year_start_of
from .catalogue import PROFIT_AND_LOSS, TYPES
from .models import (
    Account,
    AccountingPeriod,
    JournalLine,
    ManualJournal,
    MonthEndTick,
    Revaluation,
    YearEndClose,
)
from .services import AccountingError

ZERO = Decimal("0")
SOURCE = "year_end_close"

ITEMS = {
    "bank_reconciliations": "Bank accounts reconciled to the month end",
    "depreciation": "Depreciation posted",
    "revaluation": "Foreign-currency balances revalued",
    "journals": "No manual journal of the month left as a draft or waiting for approval",
    "accruals": "Accruals and prepayments entered",
    "payroll": "Payroll of the month approved and posted for every division",
    "order_costs": "Order costs up to date and Work in progress agreeing with the open jobs",
}


class CloseError(AccountingError):
    pass


def can_tick(user: User) -> bool:
    return effective_access(user).has("accounting", "enter")


def _director(user: User) -> None:
    if not effective_access(user).can("close_period"):
        raise CloseError("Only the Director closes and reopens months and years.")


def month_end(month: date) -> date:
    return months(month.replace(day=1))[1] - timedelta(days=1)


# --- The checklist ---------------------------------------------------------------------------


@dataclass
class Item:
    key: str
    label: str
    done: bool
    detail: str
    ticked_by: str = ""
    ticked_at: object = None
    note: str = ""


def _bank(end: date) -> tuple[bool, str]:
    from apps.banking.models import BankReconciliation
    from apps.masters.models import CompanyAccount

    accounts = CompanyAccount.objects.filter(
        is_active=True,
        kind__in=[CompanyAccount.Kind.CURRENT, CompanyAccount.Kind.SAVINGS],
        ledger_account__isnull=False,
    ).order_by("code")
    done = set(
        BankReconciliation.objects.filter(period_end=end).values_list("account_id", flat=True)
    )
    missing = [a.code for a in accounts if a.pk not in done]
    if not accounts:
        return True, "No bank accounts."
    if missing:
        return False, "Not reconciled: " + ", ".join(missing) + "."
    return True, f"All {len(accounts)} reconciled."


def _depreciation(end: date) -> tuple[bool, str]:
    from apps.assets.models import DepreciationRun, FixedAsset

    run = DepreciationRun.objects.filter(month_end=end).first()
    if run is not None and run.status == DepreciationRun.Status.POSTED:
        return True, "Posted."
    assets = FixedAsset.objects.filter(depreciation_from__lte=end).exclude(
        status=FixedAsset.Status.DISPOSED, disposed_on__lt=end.replace(day=1)
    )
    if not assets.exists():
        return True, "No assets to depreciate."
    if run is not None:
        return False, "Worked out but not posted yet."
    return False, "Not worked out yet (Accounts → Fixed assets)."


def _revaluation(end: date) -> tuple[bool, str]:
    from apps.masters.models import CompanyAccount
    from apps.purchasing.models import SupplierInvoice
    from apps.sales.models import TaxInvoice

    run = Revaluation.objects.filter(month_end=end).first()
    if run is not None and run.status == Revaluation.Status.POSTED:
        return True, "Posted."
    foreign = (
        TaxInvoice.objects.filter(status=TaxInvoice.Status.ISSUED, invoice_date__lte=end)
        .exclude(currency__is_base=True)
        .exists()
        or SupplierInvoice.objects.filter(
            status=SupplierInvoice.Status.POSTED, invoice_date__lte=end
        )
        .exclude(currency__is_base=True)
        .exists()
        or JournalLine.objects.filter(
            account__company_account__in=CompanyAccount.objects.exclude(currency__is_base=True),
            entry__entry_date__lte=end,
        ).exists()
    )
    if not foreign:
        return True, "Nothing in a foreign currency."
    if run is not None:
        return False, "Worked out but not posted yet."
    return False, "Not worked out yet (Accounts → Month-end revaluation)."


def _journals(start: date, end: date) -> tuple[bool, str]:
    open_ones = ManualJournal.objects.filter(
        entry_date__gte=start,
        entry_date__lte=end,
        status__in=[ManualJournal.Status.DRAFT, ManualJournal.Status.AWAITING_APPROVAL],
    ).order_by("number")
    numbers = list(open_ones.values_list("number", flat=True)[:10])
    if numbers:
        return False, "Still open: " + ", ".join(numbers) + "."
    return True, "None open."


def _payroll(start: date) -> tuple[bool, str]:
    """Pay month M (P2B-15: the 21st of the month before to the 20th of M) is posted on its
    last day, so it belongs to calendar month M."""
    from apps.payroll import periods
    from apps.payroll.models import Employee, PayrollRun

    first, last = periods.pay_period(start)
    employed = Employee.objects.filter(join_date__lte=last).exclude(leaving_date__lt=first)
    divisions = sorted(set(employed.values_list("division__code", flat=True)))
    if not divisions:
        return True, "No employees."
    done = set(
        PayrollRun.objects.filter(month=start, status=PayrollRun.Status.APPROVED).values_list(
            "division__code", flat=True
        )
    )
    missing = [d for d in divisions if d not in done]
    if missing:
        return False, "Not approved yet: " + ", ".join(missing) + " (HR and payroll → Payroll)."
    return True, "Approved: " + ", ".join(divisions) + "."


def _order_costs(start: date) -> tuple[bool, str]:
    """P3-16: Work in progress per division agrees with the open jobs' costs."""
    from apps.production import wip

    return wip.check(start)


def checklist(month: date) -> list[Item]:
    start = month.replace(day=1)
    end = month_end(start)
    checks = {
        "bank_reconciliations": _bank(end),
        "depreciation": _depreciation(end),
        "revaluation": _revaluation(end),
        "journals": _journals(start, end),
        "accruals": (False, "The Accountant ticks this once they are entered."),
        "payroll": _payroll(start),
        "order_costs": _order_costs(start),
    }
    ticks = {}
    for tick in MonthEndTick.objects.filter(month=start).select_related("ticked_by"):
        ticks.setdefault(tick.item, tick)  # the latest first
    items = []
    for key, text in ITEMS.items():
        done, detail = checks[key]
        item = Item(key, text, done, detail)
        tick = ticks.get(key)
        if tick is not None:
            item.done = True
            item.ticked_by = tick.ticked_by.full_name
            item.ticked_at = tick.ticked_at
            item.note = tick.note
        items.append(item)
    return items


def tick(user: User, month: date, item: str, note: str) -> MonthEndTick:
    if not can_tick(user):
        raise CloseError("Only the Accountant ticks the month-end checklist.")
    if item not in ITEMS:
        raise CloseError("Unknown checklist item.")
    note = " ".join((note or "").split())
    if not note:
        raise CloseError("Say what was done, or why it is not needed this month.")
    start = month.replace(day=1)
    if journal.is_closed(start):
        raise CloseError(f"{start:%B %Y} is closed already.")
    with audit_context("month_end_ticked", note):
        return MonthEndTick.objects.create(month=start, item=item, note=note[:300], ticked_by=user)


def close_month(user: User, month: date) -> AccountingPeriod:
    """The Director closes a month once its checklist is complete."""
    _director(user)
    start = month.replace(day=1)
    missing = [i.label for i in checklist(start) if not i.done]
    if missing:
        raise CloseError(
            f"{start:%B %Y} cannot be closed yet. Still to do: " + "; ".join(missing) + "."
        )
    return journal.set_closed(user, start, True)


def reopen_month(user: User, month: date, reason: str) -> AccountingPeriod:
    _director(user)
    start = month.replace(day=1)
    if active_close(year_start_of(start)) is not None:
        raise CloseError(
            f"The year {label(year_start_of(start))} is closed: reopen the year first."
        )
    return journal.set_closed(user, start, False, reason)


# --- The year --------------------------------------------------------------------------------


def active_close(year_start: date) -> YearEndClose | None:
    return YearEndClose.objects.filter(year_start=year_start, reopened=False).first()


def year_status(year_start: date) -> dict:
    year = months(year_start)
    closed = set(
        AccountingPeriod.objects.filter(month__in=year, is_closed=True).values_list(
            "month", flat=True
        )
    )
    done = active_close(year_start)
    return {
        "year_start": year_start,
        "label": label(year_start),
        "open_months": [m for m in year if m not in closed],
        "closed": done,
        "history": list(
            YearEndClose.objects.filter(year_start=year_start).select_related(
                "closed_by", "reopened_by", "journal_entry", "reopen_entry"
            )
        ),
    }


def excluded_entries() -> Q:
    """Entries the profit and loss leaves out: year-end closing entries and their reversals."""
    return Q(entry__source_type=SOURCE) | Q(entry__reversal_of__source_type=SOURCE)


def close_year(user: User, year_start: date) -> YearEndClose:
    _director(user)
    year_start = year_start_of(year_start)
    year = months(year_start)
    next_start = months(year[-1])[1]
    status = year_status(year_start)
    if status["closed"] is not None:
        raise CloseError(f"The year {label(year_start)} is closed already.")
    if status["open_months"]:
        names = ", ".join(f"{m:%b %Y}" for m in status["open_months"])
        raise CloseError(f"Close every month of the year first. Still open: {names}.")
    pnl = [code for code, (_, section, _) in TYPES.items() if section == PROFIT_AND_LOSS]
    rows = (
        JournalLine.objects.filter(account__account_type__in=pnl, entry__entry_date__lt=next_start)
        .values("account", "division")
        .annotate(d=Sum("debit"), c=Sum("credit"))
    )
    accounts = Account.objects.in_bulk({r["account"] for r in rows})
    divisions = Division.objects.in_bulk({r["division"] for r in rows if r["division"]})
    retained = Account.objects.filter(system_role="retained_earnings", is_active=True).first()
    if retained is None:
        raise CloseError("The chart of accounts has no active Retained earnings account.")
    text = f"Year-end close {label(year_start)}"
    lines: list[journal.Line] = []
    profit_by_division: dict = {}
    for r in rows:
        balance = (r["d"] or ZERO) - (r["c"] or ZERO)  # a cost is a debit balance
        if not balance:
            continue
        division = divisions.get(r["division"])
        lines.append(
            journal.Line(
                account=accounts[r["account"]],
                debit=max(-balance, ZERO),
                credit=max(balance, ZERO),
                division=division,
                description=text,
            )
        )
        profit_by_division[division] = profit_by_division.get(division, ZERO) - balance
    if not lines:
        raise CloseError("The year has no income or costs to close.")
    for division, profit in sorted(
        profit_by_division.items(), key=lambda kv: kv[0].code if kv[0] else ""
    ):
        if profit:
            lines.append(
                journal.Line(
                    account=retained,
                    debit=max(-profit, ZERO),
                    credit=max(profit, ZERO),
                    division=division,
                    description=f"{text}: profit carried to retained earnings",
                )
            )
    profit = sum(profit_by_division.values(), ZERO)
    with audit_context("year_closed"), transaction.atomic():
        entry = journal.post(
            user,
            entry_date=next_start,
            narration=f"{text}: income and costs carried to retained earnings",
            lines=lines,
            source_type=SOURCE,
            source_id=label(year_start),
        )
        return YearEndClose.objects.create(
            year_start=year_start, profit=profit, journal_entry=entry, closed_by=user
        )


def reopen_year(user: User, year_start: date, reason: str) -> YearEndClose:
    _director(user)
    reason = " ".join((reason or "").split())
    if not reason:
        raise CloseError("Give a reason for reopening the year.")
    year_start = year_start_of(year_start)
    with audit_context("year_reopened", reason), transaction.atomic():
        done = (
            YearEndClose.objects.select_for_update()
            .filter(year_start=year_start, reopened=False)
            .first()
        )
        if done is None:
            raise CloseError(f"The year {label(year_start)} is not closed.")
        reversal = journal.reverse(
            user, done.journal_entry, reason=reason, on_date=done.journal_entry.entry_date
        )
        done.reopened = True
        done.reopen_reason = reason[:300]
        done.reopen_entry = reversal
        done.reopened_by = user
        done.reopened_at = timezone.now()
        done.save(
            update_fields=[
                "reopened",
                "reopen_reason",
                "reopen_entry",
                "reopened_by",
                "reopened_at",
            ]
        )
        return done
