"""Payroll in the cash flow planner (backlog P2B-13).

- **When it is paid** (owner, 5 Nov 2026; P2B-15): the net pay of pay month M on the last day
  of M; EPF (8% + 12%) and ETF (3%) by the last day of the month after M; APIT by the 15th
  of the month after M (the due dates of the EPF and ETF Acts and the Inland Revenue Act).
- **Owed now**: the balance of Salaries payable, EPF, ETF and APIT payable in the ledger as
  at today. It is matched to the approved payrolls newest first (older ones are paid
  first), each part on its payroll's due date (today when overdue); anything older than
  every approved payroll (an opening balance) is due today.
- **Still to come**: each division's pay months after its latest approved payroll are
  estimated as the same amounts as that payroll (shown as an estimate) until it is
  approved. A division whose latest payroll is more than three pay months old is not
  estimated.
- Only totals per division appear; no employee's pay is shown.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from . import periods
from .models import PayrollRun

ZERO = Decimal("0")
ROLES = {
    "net": "salaries_payable",
    "epf": "epf_payable",
    "etf": "etf_payable",
    "apit": "apit_payable",
}
NAMES = {"net": "Net pay", "epf": "EPF 8% + 12%", "etf": "ETF 3%", "apit": "APIT"}
ESTIMATE_MONTHS = 3


@dataclass
class Payment:
    day: date
    amount: Decimal  # paid out: positive
    kind: str  # payroll (net pay) or statutory (EPF, ETF, APIT)
    label: str
    link: str = ""


def _next_month(month: date) -> date:
    return (month.replace(day=28) + timedelta(days=4)).replace(day=1)


def _last_day(month: date) -> date:
    return _next_month(month) - timedelta(days=1)


def due(month: date, what: str) -> date:
    """When pay month `month`'s net pay, EPF, ETF or APIT is paid."""
    if what == "net":
        return _last_day(month)
    following = _next_month(month)
    if what == "apit":
        return following.replace(day=15)
    return _last_day(following)


def amounts(run: PayrollRun) -> dict[str, Decimal]:
    t = run.lines.aggregate(
        net=Sum("net"),
        epf_employee=Sum("epf_employee"),
        epf_employer=Sum("epf_employer"),
        etf=Sum("etf"),
        apit=Sum("apit"),
    )
    return {
        "net": t["net"] or ZERO,
        "epf": (t["epf_employee"] or ZERO) + (t["epf_employer"] or ZERO),
        "etf": t["etf"] or ZERO,
        "apit": t["apit"] or ZERO,
    }


def owed(what: str, today: date) -> Decimal:
    """The credit balance of the payroll liability account as at today."""
    from apps.accounting.models import JournalLine

    sums = JournalLine.objects.filter(
        account__system_role=ROLES[what], entry__entry_date__lte=today
    ).aggregate(debit=Sum("debit"), credit=Sum("credit"))
    return (sums["credit"] or ZERO) - (sums["debit"] or ZERO)


def _kind(what: str) -> str:
    return "payroll" if what == "net" else "statutory"


def payments(today: date, end: date) -> list[Payment]:
    runs = list(
        PayrollRun.objects.filter(status=PayrollRun.Status.APPROVED)
        .select_related("division")
        .order_by("-month", "division__code")
    )
    figures = {run.pk: amounts(run) for run in runs}
    out: list[Payment] = []
    # What is owed now, newest payrolls first.
    for what in ROLES:
        left = owed(what, today)
        for run in runs:
            if left <= 0:
                break
            part = min(left, figures[run.pk][what])
            if part <= 0:
                continue
            day = max(today, due(run.month, what))
            if day <= end:
                out.append(
                    Payment(
                        day,
                        part,
                        _kind(what),
                        f"{NAMES[what]}: payroll {run.number or run.division.code} "
                        f"({run.division.code}, {run.month:%B %Y})",
                    )
                )
            left -= part
        if left > 0:
            out.append(Payment(today, left, _kind(what), f"{NAMES[what]}: older amounts owed"))
    # Pay months still to come, estimated from each division's latest approved payroll.
    latest: dict[int, PayrollRun] = {}
    for run in runs:
        latest.setdefault(run.division_id, run)
    recent = periods.pay_month_of(today)
    for _ in range(ESTIMATE_MONTHS):
        recent = periods.previous_month(recent)
    for run in latest.values():
        if run.month < recent:
            continue
        month = _next_month(run.month)
        while due(month, "net") <= end:
            for what, amount in figures[run.pk].items():
                day = max(today, due(month, what))
                if amount > 0 and day <= end:
                    out.append(
                        Payment(
                            day,
                            amount,
                            _kind(what),
                            f"{NAMES[what]}: {run.division.code} {month:%B %Y} "
                            f"(estimate, as {run.month:%B %Y})",
                        )
                    )
            month = _next_month(month)
    return out
