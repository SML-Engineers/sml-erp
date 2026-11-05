"""Overtime and attendance rules (backlog P2B-05).

- Each division has dated work rules (rule 11): normal minutes a day, a grace period for late
  arrival, short leaves allowed a month, the overtime minimum and step, the overtime rates
  for working days, Sundays and holidays, and the hourly divisor payroll uses (P2B-06).
  Defaults (backlog question 5): 8 hours a day; 1.5 times on working days, 2 times on Sundays
  and holidays; HR enters new rules from a month, with a reason.
- Everything is per pay month (P2B-15, periods.py): a rule "from November 2026" applies from
  the first day of pay month November (21 October by default).
- From a confirmed attendance pay month (P2B-04), each day gives:
  - working day: overtime = minutes worked beyond the shift's working minutes (or the normal
    day); short time = minutes late beyond the grace period plus minutes left early;
  - Sunday or holiday: all minutes worked are overtime at that day's rate.
  Overtime below the minimum is not counted, and is rounded down to the step.
- A pay month's short time is covered by short leave (up to the number allowed, each up to its
  length); the rest is no-pay time. Short leave is paid for Shop and Office staff; for Wages
  Board staff each one costs a quarter of a day's pay unless the rule says it is paid
  (P2B-16; owner, 5 Nov 2026). Payroll (P2B-06) deducts them. Days absent and days of
  unpaid leave are no-pay days.
- The section's supervisor, or the Director, checks each employee's month; never the person
  who confirmed the attendance, nor the employee (rule 5). Checked figures are kept as
  checked and are what payroll pays; reopening the attendance month voids them.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, User

from . import attendance, employees, leave, periods
from .models import AttendanceDay, AttendanceMonth, Employee, Leave, OvertimeCheck, WorkRule

FLAG_FIELDS = ("short_leave_paid_wb",)
MINUTE_FIELDS = (
    "normal_day_minutes",
    "grace_minutes",
    "short_leaves_per_month",
    "short_leave_minutes",
    "ot_min_minutes",
    "ot_step_minutes",
    "hourly_divisor",
)
RATE_FIELDS = ("rate_working_day", "rate_sunday", "rate_holiday")


class OvertimeError(Exception):
    pass


# --- Rules -------------------------------------------------------------------------------------


def rule_for(division_id: int, day: date) -> WorkRule | None:
    return (
        WorkRule.objects.filter(division_id=division_id, effective_from__lte=day)
        .order_by("-effective_from")
        .first()
    )


def _division(user: User, code) -> Division:
    found = division_scope(user).filter(code=str(code or "").upper()).first()
    if found is None:
        raise OvertimeError("Choose one of your divisions.")
    return found


def add_rule(user: User, division_code, values: dict) -> WorkRule:
    if not effective_access(user).has("hr_payroll", "manage"):
        raise OvertimeError("Only HR keeps the work rules.")
    division = _division(user, division_code)
    try:
        start = attendance.first_of(values.get("effective_from"))
    except attendance.AttendanceError as error:
        raise OvertimeError(str(error)) from None
    if AttendanceMonth.objects.filter(division=division, month__gte=start, confirmed=True).exists():
        raise OvertimeError(
            "Attendance from that pay month is already confirmed; a new rule starts after it."
        )
    reason = " ".join(str(values.get("reason") or "").split())
    if not reason:
        raise OvertimeError("Give the reason (for example: Wages Board decision of 2026).")
    current = rule_for(division.pk, start)
    rule = WorkRule(division=division, effective_from=start, reason=reason[:200], created_by=user)
    for name in MINUTE_FIELDS:
        value = values.get(name, getattr(current, name) if current else None)
        if value in (None, ""):
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise OvertimeError(f"{name.replace('_', ' ')} is a whole number.") from None
        if not 0 <= number <= 1440:
            raise OvertimeError(f"{name.replace('_', ' ')} is between 0 and 1440.")
        setattr(rule, name, number)
    for name in RATE_FIELDS:
        value = values.get(name, getattr(current, name) if current else None)
        if value in (None, ""):
            continue
        try:
            rate = Decimal(str(value)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            raise OvertimeError("A rate is a number such as 1.5.") from None
        if not Decimal(1) <= rate <= Decimal(5):
            raise OvertimeError("An overtime rate is between 1 and 5 times.")
        setattr(rule, name, rate)
    for name in FLAG_FIELDS:
        value = values.get(name, getattr(current, name) if current else None)
        if value in (None, ""):
            continue
        setattr(rule, name, value in (True, "true", "1", 1, "yes"))
    if rule.normal_day_minutes == 0 or rule.ot_step_minutes == 0 or rule.hourly_divisor == 0:
        raise OvertimeError("The normal day, the overtime step and the divisor are above 0.")
    try:
        with audit_context("work_rule_added", reason), transaction.atomic():
            rule.save()
    except IntegrityError:
        raise OvertimeError(f"{division.code} already has a rule from {start:%B %Y}.") from None
    return rule


def in_force(rule: WorkRule) -> bool:
    """A rule is in force from the first day of its pay month."""
    return periods.pay_period(rule.effective_from)[0] <= timezone.localdate()


def withdraw_rule(user: User, rule: WorkRule, reason: str) -> None:
    if not effective_access(user).has("hr_payroll", "manage"):
        raise OvertimeError("Only HR keeps the work rules.")
    if in_force(rule):
        raise OvertimeError("A rule in force is never withdrawn; enter a new one.")
    reason = " ".join((reason or "").split())
    if not reason:
        raise OvertimeError("Give the reason for withdrawing the rule.")
    with audit_context("work_rule_withdrawn", reason), transaction.atomic():
        rule.delete()


# --- Working out a month -----------------------------------------------------------------------


def _counted(minutes: int, rule: WorkRule) -> int:
    if minutes < max(rule.ot_min_minutes, 1):
        return 0
    return minutes - minutes % rule.ot_step_minutes


@dataclass
class Month:
    employee: Employee
    rule: WorkRule
    ot_working: int = 0
    ot_sunday: int = 0
    ot_holiday: int = 0
    short_minutes: int = 0
    short_leaves: int = 0
    nopay_minutes: int = 0
    absent_days: int = 0
    unpaid_leave_days: Decimal = Decimal(0)
    unpaid_short_leaves: int = 0
    check: OvertimeCheck | None = None

    @property
    def nopay_days(self) -> Decimal:
        return Decimal(self.absent_days) + self.unpaid_leave_days


def work_out(employee: Employee, month: date, absent_days: int) -> Month:
    month = attendance.first_of(month)
    first, end = periods.pay_period(month)
    rule = rule_for(employee.division_id, month)
    if rule is None:
        raise OvertimeError(f"{employee.division.code} has no work rule for {month:%B %Y}.")
    off = leave.holidays_between(first, end)
    out = Month(employee, rule, absent_days=absent_days)
    shorts = []
    days = AttendanceDay.objects.filter(employee=employee, date__range=(first, end))
    for d in days.select_related("shift").order_by("date"):
        if d.time_in is None:
            continue
        if d.date in off:
            out.ot_holiday += _counted(d.worked_minutes, rule)
        elif d.date.weekday() == 6:
            out.ot_sunday += _counted(d.worked_minutes, rule)
        else:
            normal = d.shift.working_minutes if d.shift else rule.normal_day_minutes
            if d.leave_type_id:  # half a day of leave
                normal //= 2
            else:
                late = d.late_minutes if d.late_minutes > rule.grace_minutes else 0
                if late + d.early_minutes:
                    shorts.append(late + d.early_minutes)
            out.ot_working += _counted(max(d.worked_minutes - normal, 0), rule)
    for minutes in shorts:
        out.short_minutes += minutes
        if out.short_leaves < rule.short_leaves_per_month and minutes <= rule.short_leave_minutes:
            out.short_leaves += 1
        else:
            out.nopay_minutes += minutes
    wages_board = employee.category == Employee.Category.WAGES_BOARD
    if wages_board and not rule.short_leave_paid_wb:
        out.unpaid_short_leaves = out.short_leaves
    unpaid = Leave.objects.filter(
        employee=employee,
        status=Leave.Status.APPROVED,
        leave_type__paid=False,
        start__lte=end,
        end__gte=first,
    )
    for x in unpaid:
        if x.half_day:
            out.unpaid_leave_days += x.days
        else:
            out.unpaid_leave_days += leave.working_days(max(x.start, first), min(x.end, end))
    return out


# --- Checking ----------------------------------------------------------------------------------


def can_check(user: User, employee: Employee) -> bool:
    if employee.user_id == user.pk:
        return False
    if effective_access(user).has("hr_payroll", "approve"):
        return True
    return bool(employee.section_id) and employee.section.supervisors.filter(pk=user.pk).exists()


def people_for(user: User, division: Division):
    """HR and the Director see the division; a supervisor sees the sections they supervise."""
    if employees.can_view(user):
        rows = employees.visible(user)
    else:
        rows = Employee.objects.filter(section__supervisors=user).select_related(
            "division", "section", "user"
        )
    return rows.filter(division=division)


def division_month(user: User, division_code, month) -> tuple[Division, date, bool, list[Month]]:
    division, month = _division(user, division_code), attendance.first_of(month)
    record = AttendanceMonth.objects.filter(division=division, month=month).first()
    confirmed = bool(record and record.confirmed)
    allowed = {p.pk for p in people_for(user, division)}
    summary = {
        s.employee.pk: s
        for s in attendance.month_summary_for(
            Employee.objects.filter(pk__in=allowed), division, month
        )
    }
    checks = {
        c.employee_id: c
        for c in OvertimeCheck.objects.filter(
            employee_id__in=allowed, month=month, voided=False
        ).select_related("checked_by")
    }
    rows = []
    for pk, s in sorted(summary.items(), key=lambda kv: kv[1].employee.number):
        figures = work_out(s.employee, month, s.absent_days)
        figures.check = checks.get(pk)
        rows.append(figures)
    return division, month, confirmed, rows


def check(user: User, division_code, month, employee_ids) -> int:
    """The supervisor or the Director checks employees' months; all or nothing."""
    division, month = _division(user, division_code), attendance.first_of(month)
    record = AttendanceMonth.objects.filter(division=division, month=month, confirmed=True).first()
    if record is None:
        raise OvertimeError(
            f"HR has not confirmed attendance for pay month {month:%B %Y} in {division.code}."
        )
    if record.confirmed_by_id == user.pk:
        raise OvertimeError("The person who confirmed the attendance does not check the overtime.")
    wanted = {int(x) for x in employee_ids or []}
    if not wanted:
        raise OvertimeError("Choose the employees to check.")
    people = {p.pk: p for p in people_for(user, division).filter(pk__in=wanted)}
    if set(people) != wanted:
        raise OvertimeError("Some of those employees are not yours to check.")
    absent = {
        s.employee.pk: s.absent_days
        for s in attendance.month_summary_for(
            Employee.objects.filter(pk__in=wanted), division, month
        )
    }
    with audit_context("overtime_checked", f"{division.code} {month:%Y-%m}"), transaction.atomic():
        for pk, person in sorted(people.items()):
            if not can_check(user, person):
                raise OvertimeError(f"You do not check {person.number} {person.full_name}.")
            figures = work_out(person, month, absent.get(pk, 0))
            try:
                with transaction.atomic():
                    OvertimeCheck.objects.create(
                        employee=person,
                        month=month,
                        rule=figures.rule,
                        ot_working_minutes=figures.ot_working,
                        ot_sunday_minutes=figures.ot_sunday,
                        ot_holiday_minutes=figures.ot_holiday,
                        short_minutes=figures.short_minutes,
                        nopay_minutes=figures.nopay_minutes,
                        nopay_days=figures.nopay_days,
                        unpaid_short_leaves=figures.unpaid_short_leaves,
                        checked_by=user,
                    )
            except IntegrityError:
                raise OvertimeError(
                    f"{person.number} is already checked for {month:%B %Y}."
                ) from None
    return len(people)


def minutes_text(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d}"
