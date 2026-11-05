"""Pay periods (backlog P2B-15; owner, 5 Nov 2026, question 3).

Salaries are for the 21st of one month to the 20th of the next, paid on the last day of the
month. A **pay month** is named by the month it ends in: pay month November 2026 is
21 October to 20 November 2026. Attendance, overtime, short leave and no-pay are worked out
per pay month; `AttendanceMonth.month` and `OvertimeCheck.month` hold the 1st of the pay
month.

The day a period starts is a dated setting (rule 11, `PayPeriodRule`), default the 21st. A
rule from pay month M says on which day of the month before M the period M starts (1 = the
calendar month itself). Period M ends the day before period M+1 starts, so the periods never
overlap or leave a gap, even when the rule changes. The database function
`payroll_pay_month(date)` (migration 0006) follows the same rule.

A new rule starts from a pay month whose previous pay month is not confirmed in any division
(its end moves too); it never changes (database) and can be withdrawn on the same condition.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import User

from .models import AttendanceMonth, PayPeriodRule

DEFAULT_START_DAY = 1  # with no rule at all: the calendar month


class PeriodError(Exception):
    pass


def next_month(month: date) -> date:
    return (month.replace(day=28) + timedelta(days=4)).replace(day=1)


def previous_month(month: date) -> date:
    return (month.replace(day=1) - timedelta(days=1)).replace(day=1)


@dataclass
class Calendar:
    """The pay-period rules, read once (an attendance sheet asks for thousands of days)."""

    rules: list[tuple[date, int]]  # (effective_from, start_day), oldest first

    def start_day(self, month: date) -> int:
        day = DEFAULT_START_DAY
        for effective_from, start_day in self.rules:
            if effective_from > month:
                break
            day = start_day
        return day

    def start(self, month: date) -> date:
        """The first day of pay month `month` (the 1st of a month)."""
        day = self.start_day(month)
        return month if day == 1 else previous_month(month).replace(day=day)

    def period(self, month: date) -> tuple[date, date]:
        month = month.replace(day=1)
        return self.start(month), self.start(next_month(month)) - timedelta(days=1)

    def month_of(self, day: date) -> date:
        """The pay month a date belongs to (the 1st of that month)."""
        following = next_month(day.replace(day=1))
        return following if day >= self.start(following) else day.replace(day=1)


def calendar() -> Calendar:
    return Calendar(
        list(
            PayPeriodRule.objects.order_by("effective_from").values_list(
                "effective_from", "start_day"
            )
        )
    )


def pay_period(month: date) -> tuple[date, date]:
    return calendar().period(month)


def pay_month_of(day: date) -> date:
    return calendar().month_of(day)


def last_pay_month(today: date | None = None) -> date:
    """The latest pay month that has ended (the one HR confirms next)."""
    cal = calendar()
    return previous_month(cal.month_of(today or timezone.localdate()))


def label(month: date, cal: Calendar | None = None) -> dict:
    start, end = (cal or calendar()).period(month)
    return {"month": month.isoformat()[:7], "start": start.isoformat(), "end": end.isoformat()}


# --- Keeping the rule --------------------------------------------------------------------------


def _locked(month: date) -> bool:
    """A rule from `month` moves the end of the month before it: neither may be confirmed."""
    return AttendanceMonth.objects.filter(month__gte=previous_month(month), confirmed=True).exists()


def can_withdraw(rule: PayPeriodRule) -> bool:
    return not _locked(rule.effective_from)


def add_rule(user: User, values: dict) -> PayPeriodRule:
    if not effective_access(user).has("hr_payroll", "manage"):
        raise PeriodError("Only HR keeps the pay period.")
    text = str(values.get("effective_from") or "").strip()
    try:
        month = date.fromisoformat(f"{text[:7]}-01")
    except ValueError:
        raise PeriodError("Give the first pay month, for example 2027-01.") from None
    try:
        start_day = int(values.get("start_day"))
    except (TypeError, ValueError):
        raise PeriodError("The start day is a whole number from 1 to 28.") from None
    if not 1 <= start_day <= 28:
        raise PeriodError("The start day is a whole number from 1 to 28.")
    reason = " ".join(str(values.get("reason") or "").split())
    if not reason:
        raise PeriodError("Give the reason for the new pay period.")
    with audit_context("pay_period_added", reason), transaction.atomic():
        if _locked(month):
            raise PeriodError(
                "Attendance is confirmed for that pay month or the one before it; "
                "a new pay period starts after them."
            )
        if PayPeriodRule.objects.filter(effective_from=month).exists():
            raise PeriodError(f"There is already a pay period rule from {month:%B %Y}.")
        return PayPeriodRule.objects.create(
            effective_from=month, start_day=start_day, reason=reason[:200], created_by=user
        )


def withdraw_rule(user: User, rule: PayPeriodRule, reason: str) -> None:
    if not effective_access(user).has("hr_payroll", "manage"):
        raise PeriodError("Only HR keeps the pay period.")
    reason = " ".join((reason or "").split())
    if not reason:
        raise PeriodError("Give the reason for withdrawing the rule.")
    with audit_context("pay_period_withdrawn", reason), transaction.atomic():
        if _locked(rule.effective_from):
            raise PeriodError("Attendance under this rule is confirmed; enter a new rule instead.")
        rule.delete()
