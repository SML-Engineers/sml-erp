"""Holidays and leave (backlog P2B-03).

- Holidays: HR enters the year's public, bank, mercantile, Poya and company holidays. One
  that has passed is kept as it was (database).
- Leave types say how many days are granted each calendar year. The defaults follow the Shop
  and Office Employees Act (backlog question 8): annual leave by the quarter of joining,
  casual leave half a day a month in the first year; no carry-forward. HR adds types and
  changes days with a reason.
- Wages Board employees (P2B-16; owner, 5 Nov 2026) may have their own rule and days per
  leave type: annual leave none in the year of joining, then 7; casual and sick leave 7 like
  Shop and Office staff. Maternity leave: at most 84 working days at a time (the law as
  amended in 2018: 84 working days for each live birth, 42 for a still birth).
- Each year's leave is granted to employees by HR ("Grant the year's leave"), with any days
  carried forward; corrections are adjustments with a reason. Grants are never changed.
- Leave is recorded by HR from the approved leave form, applied for on the self-service page
  (P2B-11; approved by HR, never by the person who applied or entered it, rule 5) or taken
  from the attendance sheet (P2B-04). Days are working days: Monday to Saturday, not
  holidays. Leave with a balance cannot go below zero. Leave is cancelled, never deleted.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import User

from . import employees
from .models import Employee, Holiday, Leave, LeaveGrant, LeaveType

ZERO = Decimal("0.0")
HALF = Decimal("0.5")
CODE = re.compile(r"^[A-Z][A-Z0-9_-]{0,11}$")
# Annual leave in the year after joining, by the quarter of joining (of 14 days).
FIRST_ANNUAL = {1: 14, 2: 10, 3: 7, 4: 4}
OPEN = (Leave.Status.APPLIED, Leave.Status.APPROVED)


class LeaveError(Exception):
    pass


def can_manage(user: User) -> bool:
    """Holidays and leave types: HR (HR and payroll: Manage)."""
    return effective_access(user).has("hr_payroll", "manage")


def _text(value, what: str, *, required=True, length=200) -> str:
    text = " ".join(str(value or "").split())
    if required and not text:
        raise LeaveError(f"Give the {what}.")
    return text[:length]


def day_of(value, what: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        raise LeaveError(f"The {what} is not a date (for example 2026-12-24).") from None


def _days(value, what: str) -> Decimal:
    try:
        days = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise LeaveError(f"The {what} is a number of days, for example 14 or 1.5.") from None
    if not days.is_finite() or days != (days * 2).to_integral_value() / 2 or abs(days) > 366:
        raise LeaveError(f"The {what} is in whole or half days.")
    return days.quantize(HALF)


# --- Holidays ----------------------------------------------------------------------------------


def add_holiday(user: User, values: dict) -> Holiday:
    if not can_manage(user):
        raise LeaveError("Only HR keeps the holidays.")
    day = day_of(values.get("date"), "date")
    kind = values.get("kind") or Holiday.Kind.PUBLIC
    if kind not in Holiday.Kind.values:
        raise LeaveError("Choose the kind of holiday.")
    name = _text(values.get("name"), "holiday's name", length=100)
    try:
        with audit_context("holiday_added"), transaction.atomic():
            return Holiday.objects.create(date=day, name=name, kind=kind, created_by=user)
    except IntegrityError:
        raise LeaveError(f"{day:%d %B %Y} is already a holiday.") from None


def remove_holiday(user: User, holiday: Holiday, reason: str) -> None:
    if not can_manage(user):
        raise LeaveError("Only HR keeps the holidays.")
    if holiday.date <= timezone.localdate():
        raise LeaveError("A holiday that has passed is kept.")
    reason = _text(reason, "reason for removing the holiday")
    with audit_context("holiday_removed", reason), transaction.atomic():
        holiday.delete()


def holidays_between(start: date, end: date) -> set[date]:
    return set(Holiday.objects.filter(date__range=(start, end)).values_list("date", flat=True))


def working_days(start: date, end: date) -> int:
    """Monday to Saturday, not holidays."""
    off = holidays_between(start, end)
    count, day = 0, start
    while day <= end:
        if day.weekday() != 6 and day not in off:
            count += 1
        day += timedelta(days=1)
    return count


# --- Leave types -------------------------------------------------------------------------------


def save_leave_type(
    user: User, values: dict, current: LeaveType | None = None, reason: str = ""
) -> LeaveType:
    if not can_manage(user):
        raise LeaveError("Only HR keeps the leave types.")
    if current is not None:
        reason = _text(reason, "reason for changing the leave type")
    kind = current or LeaveType()
    if current is None:
        code = str(values.get("code") or "").strip().upper()
        if not CODE.match(code):
            raise LeaveError("The code is 1 to 12 capital letters, digits, _ or -.")
        kind.code = code
    elif "code" in values and str(values["code"]).strip().upper() != current.code:
        raise LeaveError("A leave type's code never changes.")
    if current is None or "name" in values:
        kind.name = _text(values.get("name"), "name", length=100)
    if current is None or "rule" in values:
        if values.get("rule") not in LeaveType.Rule.values:
            raise LeaveError("Choose how the days are granted.")
        kind.rule = values["rule"]
    for field in ("days", "carry_forward_max"):
        if field in values:
            days = _days(values[field] or 0, "number of days")
            if days < 0:
                raise LeaveError("Days are 0 or more.")
            setattr(kind, field, days)
    if "wb_rule" in values:
        wb_rule = values.get("wb_rule") or ""
        if wb_rule and wb_rule not in LeaveType.Rule.values:
            raise LeaveError("Choose how the days are granted to Wages Board staff.")
        kind.wb_rule = wb_rule
    for field in ("wb_days", "max_days"):
        if field in values:
            raw = values.get(field)
            if raw in (None, ""):
                setattr(kind, field, None)
                continue
            days = _days(raw, "number of days")
            if days <= 0:
                raise LeaveError("Days are above 0, or blank.")
            setattr(kind, field, days)
    for field in ("paid", "is_active"):
        if field in values:
            value = values[field]
            setattr(kind, field, value in (True, "true", "1", 1, "yes"))
    if kind.rule == LeaveType.Rule.UNLIMITED:
        kind.days, kind.carry_forward_max = ZERO, ZERO
        kind.wb_rule, kind.wb_days = "", None
    elif kind.days <= 0:
        raise LeaveError("Give the days granted each year.")
    if kind.wb_rule == LeaveType.Rule.UNLIMITED:
        raise LeaveError("Wages Board staff keep a balance when the leave type does.")
    event = "leave_type_added" if current is None else "leave_type_changed"
    try:
        with audit_context(event, reason), transaction.atomic():
            kind.save()
    except IntegrityError:
        raise LeaveError(f"The code {kind.code} is taken.") from None
    return kind


# --- Entitlements and balances -----------------------------------------------------------------


def _half_floor(value: Decimal) -> Decimal:
    return (value * 2).to_integral_value(rounding=ROUND_FLOOR) / 2


def entitlement(employee: Employee, kind: LeaveType, year: int) -> Decimal | None:
    """The days of `kind` the employee is entitled to in `year` (None: no balance kept)."""
    if not kind.keeps_balance:
        return None
    joined = employee.join_date
    if joined.year > year or (employee.leaving_date and employee.leaving_date.year < year):
        return ZERO
    rule, days = kind.rule_for(employee.category)
    full = Decimal(days)
    if rule == LeaveType.Rule.AFTER_JOINING:
        return ZERO if joined.year == year else full
    if rule == LeaveType.Rule.ANNUAL:
        if joined.year == year:
            return ZERO
        if joined.year == year - 1:
            quarter = (joined.month - 1) // 3 + 1
            return _half_floor(full * FIRST_ANNUAL[quarter] / 14)
        return full
    if rule == LeaveType.Rule.CASUAL and joined.year == year:
        months = 12 - joined.month + (1 if joined.day == 1 else 0)
        return min(full, HALF * months)
    return full


@dataclass
class Balance:
    leave_type: LeaveType
    granted: Decimal
    taken: Decimal
    pending: Decimal

    @property
    def available(self) -> Decimal:
        return self.granted - self.taken - self.pending


def balance(employee: Employee, kind: LeaveType, year: int, *, without: Leave | None = None):
    granted = (
        LeaveGrant.objects.filter(employee=employee, leave_type=kind, year=year).aggregate(
            s=Sum("days")
        )["s"]
        or ZERO
    )
    used = Leave.objects.filter(employee=employee, leave_type=kind, start__year=year)
    if without is not None:
        used = used.exclude(pk=without.pk)
    taken = used.filter(status=Leave.Status.APPROVED).aggregate(s=Sum("days"))["s"] or ZERO
    pending = used.filter(status=Leave.Status.APPLIED).aggregate(s=Sum("days"))["s"] or ZERO
    return Balance(kind, granted, taken, pending)


def balances(employee: Employee, year: int) -> list[Balance]:
    kinds = LeaveType.objects.filter(is_active=True).exclude(rule=LeaveType.Rule.UNLIMITED)
    return [balance(employee, k, year) for k in kinds]


def _check_year(year) -> int:
    try:
        year = int(year)
    except (TypeError, ValueError):
        raise LeaveError("Give the year, for example 2027.") from None
    this = timezone.localdate().year
    if not 2000 <= year <= this + 1:
        raise LeaveError(f"Leave is granted for years up to {this + 1}.")
    return year


def grant_year(user: User, year) -> dict:
    """Grant `year`'s leave to every working employee HR keeps who has not had it yet, with
    the days carried forward where the leave type allows. Running it again adds only what is
    missing (new joiners)."""
    if not employees.can_edit(user):
        raise LeaveError("Only HR grants leave.")
    year = _check_year(year)
    kinds = list(LeaveType.objects.filter(is_active=True).exclude(rule=LeaveType.Rule.UNLIMITED))
    people = employees.visible(user).filter(is_active=True, join_date__year__lte=year)
    made = {"employees": 0, "grants": 0}
    with audit_context("leave_year_granted", str(year)), transaction.atomic():
        for person in people:
            before = made["grants"]
            for kind in kinds:
                have = set(
                    LeaveGrant.objects.filter(
                        employee=person, leave_type=kind, year=year
                    ).values_list("kind", flat=True)
                )
                days = entitlement(person, kind, year)
                if LeaveGrant.Kind.ENTITLEMENT not in have and days:
                    _grant(user, person, kind, year, LeaveGrant.Kind.ENTITLEMENT, days, "Year")
                    made["grants"] += 1
                if LeaveGrant.Kind.CARRIED not in have and kind.carry_forward_max > 0:
                    left = balance(person, kind, year - 1).available
                    carried = min(left, Decimal(kind.carry_forward_max))
                    if carried > 0:
                        _grant(user, person, kind, year, LeaveGrant.Kind.CARRIED, carried, "")
                        made["grants"] += 1
            if made["grants"] > before:
                made["employees"] += 1
    return made


def _grant(user, person, kind, year, grant_kind, days, reason) -> LeaveGrant:
    labels = {
        LeaveGrant.Kind.ENTITLEMENT: f"Entitlement for {year}",
        LeaveGrant.Kind.CARRIED: f"Carried forward from {year - 1}",
    }
    return LeaveGrant.objects.create(
        employee=person,
        leave_type=kind,
        year=year,
        kind=grant_kind,
        days=days,
        reason=reason if grant_kind == LeaveGrant.Kind.ADJUSTMENT else labels[grant_kind],
        created_by=user,
    )


def adjust(user: User, employee: Employee, kind: LeaveType, year, days, reason: str):
    if not employees.can_edit(user):
        raise LeaveError("Only HR adjusts leave.")
    _visible(user, employee)
    if not kind.keeps_balance:
        raise LeaveError(f"{kind.name} keeps no balance.")
    year = _check_year(year)
    days = _days(days, "adjustment")
    if days == 0:
        raise LeaveError("The adjustment is not 0.")
    reason = _text(reason, "reason for the adjustment")
    with audit_context("leave_adjusted", reason), transaction.atomic():
        Employee.objects.select_for_update().get(pk=employee.pk)
        if balance(employee, kind, year).available + days < 0:
            raise LeaveError("The balance would go below zero.")
        return _grant(user, employee, kind, year, LeaveGrant.Kind.ADJUSTMENT, days, reason)


# --- Leave taken -------------------------------------------------------------------------------


def _visible(user: User, employee: Employee) -> Employee:
    found = employees.visible(user).filter(pk=employee.pk).first()
    if found is None:
        raise LeaveError("This employee is not in one of your divisions.")
    return found


def _check_room(employee: Employee, kind: LeaveType, start: date, days: Decimal, without=None):
    if not kind.keeps_balance:
        return
    left = balance(employee, kind, start.year, without=without).available
    if days > left:
        raise LeaveError(
            f"{employee.full_name} has {left} days of {kind.name.lower()} left in {start.year}."
        )


def record(
    user: User,
    employee: Employee,
    kind: LeaveType,
    start,
    end=None,
    *,
    half_day=False,
    reason: str = "",
    source: str = Leave.Source.HR,
) -> Leave:
    """Leave approved on the leave form (HR) or taken from attendance; applied for on the
    self-service page with source 'applied' (then it waits for HR's approval)."""
    if source in (Leave.Source.HR, Leave.Source.ATTENDANCE) and not employees.can_edit(user):
        raise LeaveError("Only HR records leave.")
    if source == Leave.Source.APPLIED and getattr(employee, "user_id", None) != user.pk:
        raise LeaveError("Employees apply for their own leave only.")
    if source != Leave.Source.APPLIED:
        employee = _visible(user, employee)
    if not kind.is_active:
        raise LeaveError(f"{kind.name} is no longer used.")
    start = day_of(start, "first day")
    end = day_of(end, "last day") if end not in (None, "") else start
    if end < start:
        raise LeaveError("The last day is before the first day.")
    if start.year != end.year:
        raise LeaveError("Leave across the new year is recorded as two leaves, one each year.")
    if (end - start).days > 120:
        raise LeaveError("Leave is recorded up to 120 days at a time.")
    if half_day and end != start:
        raise LeaveError("Half a day is for one day only.")
    if start < employee.join_date:
        raise LeaveError("The leave starts before the employee joined.")
    if employee.leaving_date and end > employee.leaving_date:
        raise LeaveError("The leave ends after the employee left.")
    if not employee.is_active and employee.leaving_date is None:
        raise LeaveError("This employee has left.")
    count = working_days(start, end)
    if count == 0:
        raise LeaveError("Those days are Sundays or holidays; no leave is needed.")
    days = HALF if half_day else Decimal(count)
    if kind.max_days is not None and days > kind.max_days:
        raise LeaveError(f"{kind.name} is at most {kind.max_days} working days at a time.")
    status = Leave.Status.APPLIED if source == Leave.Source.APPLIED else Leave.Status.APPROVED
    with audit_context("leave_recorded", reason), transaction.atomic():
        Employee.objects.select_for_update().get(pk=employee.pk)
        overlap = Leave.objects.filter(
            employee=employee, status__in=OPEN, start__lte=end, end__gte=start
        )
        if overlap.exists():
            raise LeaveError("The employee already has leave on some of those days.")
        _check_room(employee, kind, start, days)
        return Leave.objects.create(
            employee=employee,
            leave_type=kind,
            start=start,
            end=end,
            half_day=bool(half_day),
            days=days,
            reason=_text(reason, "reason", required=False),
            status=status,
            source=source,
            created_by=user,
            decided_by=user if status == Leave.Status.APPROVED else None,
            decided_at=timezone.now() if status == Leave.Status.APPROVED else None,
        )


def decide(user: User, leave: Leave, approve: bool, note: str = "") -> Leave:
    """HR approves or rejects leave applied for (rule 5: never one's own, nor what one entered)."""
    if not employees.can_edit(user):
        raise LeaveError("Only HR approves leave.")
    _visible(user, leave.employee)
    with (
        audit_context("leave_approved" if approve else "leave_rejected", note),
        transaction.atomic(),
    ):
        leave = (
            Leave.objects.select_for_update()
            .select_related("employee", "leave_type")
            .get(pk=leave.pk)
        )
        if leave.status != Leave.Status.APPLIED:
            raise LeaveError("This leave is not waiting for a decision.")
        if user.pk in (leave.created_by_id, leave.employee.user_id):
            raise LeaveError("Nobody approves their own leave or leave they entered.")
        if not approve and not note.strip():
            raise LeaveError("Give the reason for rejecting the leave.")
        if approve:
            _check_room(leave.employee, leave.leave_type, leave.start, leave.days, without=leave)
        leave.status = Leave.Status.APPROVED if approve else Leave.Status.REJECTED
        leave.decided_by, leave.decided_at = user, timezone.now()
        leave.decision_note = _text(note, "note", required=False)
        leave.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
        return leave


def cancel(user: User, leave: Leave, reason: str) -> Leave:
    if not employees.can_edit(user):
        raise LeaveError("Only HR cancels leave.")
    _visible(user, leave.employee)
    reason = _text(reason, "reason for cancelling")
    with audit_context("leave_cancelled", reason), transaction.atomic():
        leave = Leave.objects.select_for_update().get(pk=leave.pk)
        if leave.status not in OPEN:
            raise LeaveError("Only leave applied for or approved can be cancelled.")
        leave.status = Leave.Status.CANCELLED
        leave.decided_by, leave.decided_at = user, timezone.now()
        leave.decision_note = reason
        leave.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
        return leave


def visible_leave(user: User):
    return Leave.objects.filter(employee__in=employees.visible(user)).select_related(
        "employee", "leave_type", "created_by", "decided_by"
    )


def search(rows, text: str):
    text = (text or "").strip()
    if not text:
        return rows
    return rows.filter(Q(employee__number__icontains=text) | Q(employee__full_name__icontains=text))
