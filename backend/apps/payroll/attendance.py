"""Attendance from the Excel sheet (backlog P2B-04; spec 7A, owner's decision: no device link).

- The template has one row per employee and day: employee number, date, time in, time out,
  shift, leave code, remarks. HR uploads it; it is checked first and saved all or nothing,
  every refused row listed. A later sheet replaces the same days while the month is open.
- A row with a leave code and no times is a day of that leave; with times, half a day.
- Each day keeps the minutes worked (less the shift's break), and the minutes late and left
  early against the shift; overtime, grace periods, short leave and no-pay are worked out
  from these by the rules of P2B-05.
- Everything is per **pay month** (P2B-15, periods.py): pay month November 2026 is 21 October
  to 20 November by default. `month` below always means the 1st of a pay month.
- HR confirms a division's pay month when it is complete. Leave codes then become leave records
  (P2B-03: balances checked, every problem listed, nothing saved if one fails), and the days
  never change (database). Payroll (P2B-06) uses confirmed months only. Reopening needs a
  reason and cancels the leave taken from the sheet.
"""

import hashlib
import io
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from apps.core.access import division_scope
from apps.core.audit import audit_context
from apps.core.models import Division, User
from apps.masters.models import Shift

from . import employees, leave, periods
from .leave import LeaveError
from .models import (
    AttendanceDay,
    AttendanceImport,
    AttendanceMonth,
    Employee,
    Leave,
    LeaveType,
    OvertimeCheck,
    PayrollRun,
)

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20000
COLUMNS = [
    ("number", "Employee no"),
    ("date", "Date"),
    ("time_in", "Time in"),
    ("time_out", "Time out"),
    ("shift", "Shift"),
    ("leave", "Leave code"),
    ("remarks", "Remarks"),
]
DAY = 24 * 60


class AttendanceError(Exception):
    pass


def first_of(value) -> date:
    if isinstance(value, date):
        return value.replace(day=1)
    try:
        return date.fromisoformat(f"{str(value).strip()[:7]}-01")
    except ValueError:
        raise AttendanceError("Give the month, for example 2026-11.") from None


def is_confirmed(division_id: int, month: date) -> bool:
    return AttendanceMonth.objects.filter(
        division_id=division_id, month=first_of(month), confirmed=True
    ).exists()


# --- Reading the sheet -------------------------------------------------------------------------


def _text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value if value is not None else "").split())


def _date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise AttendanceError(f"the date {text!r} is not a date (for example 2026-11-03)")


def _time(value, what: str) -> time | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0)
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if isinstance(value, timedelta):  # Excel durations
        minutes = int(value.total_seconds() // 60) % DAY
        return time(minutes // 60, minutes % 60)
    if isinstance(value, (int, float)) and 0 <= value < 1:  # a fraction of a day
        minutes = round(value * DAY) % DAY
        return time(minutes // 60, minutes % 60)
    text = _text(value).replace(".", ":").upper()
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise AttendanceError(f"the {what} {text!r} is not a time (for example 08:00 or 17:30)")


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _late(actual: time, planned: time) -> int:
    """Minutes `actual` is after `planned`, across midnight; up to 12 hours counts as late."""
    diff = (_minutes(actual) - _minutes(planned)) % DAY
    return diff if 0 < diff < DAY // 2 else 0


@dataclass
class Row:
    line: int
    employee: Employee
    day: date
    shift: Shift | None
    time_in: time | None
    time_out: time | None
    leave_type: LeaveType | None
    remarks: str
    worked: int = 0
    late: int = 0
    early: int = 0


def _measure(row: Row) -> None:
    if row.time_in is None:
        return
    span = (_minutes(row.time_out) - _minutes(row.time_in)) % DAY
    if span == 0:
        raise AttendanceError("time in and time out are the same")
    if span > 20 * 60:
        raise AttendanceError("more than 20 hours between time in and time out")
    breaks = row.shift.break_minutes if row.shift and span > row.shift.break_minutes else 0
    row.worked = span - breaks
    if row.shift:
        row.late = _late(row.time_in, row.shift.start_time)
        row.early = _late(row.shift.end_time, row.time_out)


@dataclass
class Plan:
    rows: list[Row] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def check(user: User, content: bytes) -> Plan:
    if not employees.can_edit(user):
        raise AttendanceError("Only HR uploads attendance.")
    if len(content) > MAX_BYTES:
        raise AttendanceError("The file is larger than 5 MB.")
    try:
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, OSError, KeyError, ValueError):
        raise AttendanceError("The file is not an Excel workbook (.xlsx).") from None
    rows = [list(r) for r in book.worksheets[0].iter_rows(values_only=True)]
    if not rows:
        raise AttendanceError("The file is empty.")
    if len(rows) > MAX_ROWS:
        raise AttendanceError(f"The file has more than {MAX_ROWS} rows; upload a month at a time.")
    head = [_text(c).lower() for c in rows[0]]
    index = {key: head.index(label.lower()) for key, label in COLUMNS if label.lower() in head}
    if "number" not in index or "date" not in index:
        raise AttendanceError(
            "The first row must hold the template's column names (at least Employee no and Date)."
        )
    people = {e.number: e for e in employees.visible(user)}
    shifts = {s.code.upper(): s for s in Shift.objects.filter(is_active=True)}
    kinds = {k.code: k for k in LeaveType.objects.filter(is_active=True)}
    confirmed = set(
        AttendanceMonth.objects.filter(confirmed=True).values_list("division_id", "month")
    )
    calendar = periods.calendar()
    plan, seen = Plan(), set()
    for line, raw in enumerate(rows[1:], start=2):
        values = {key: (raw[i] if i < len(raw) else None) for key, i in index.items()}
        if not any(_text(v) for v in values.values()):
            continue
        number = _text(values.get("number")).upper()
        try:
            person = people.get(number)
            if person is None:
                raise AttendanceError(f"no employee {number or '(blank)'} in your divisions")
            day = _date(values.get("date"))
            if (person.pk, day) in seen:
                raise AttendanceError("this employee and date appear twice")
            seen.add((person.pk, day))
            if day < person.join_date or (person.leaving_date and day > person.leaving_date):
                raise AttendanceError("the employee was not employed on that date")
            if day > timezone.localdate():
                raise AttendanceError("the date is in the future")
            pay_month = calendar.month_of(day)
            if (person.division_id, pay_month) in confirmed:
                raise AttendanceError(
                    f"pay month {pay_month:%B %Y} is confirmed for {person.division.code}"
                )
            code = _text(values.get("shift")).upper()
            shift = None
            if code:
                shift = shifts.get(code)
                if shift is None:
                    raise AttendanceError(f"no shift {code}")
            time_in = _time(values.get("time_in"), "time in")
            time_out = _time(values.get("time_out"), "time out")
            if (time_in is None) != (time_out is None):
                raise AttendanceError("give both time in and time out, or neither")
            leave_code = _text(values.get("leave")).upper()
            kind = None
            if leave_code:
                kind = kinds.get(leave_code)
                if kind is None:
                    raise AttendanceError(f"no leave code {leave_code}")
            if time_in is None and kind is None:
                raise AttendanceError("give the times, or a leave code for a day of leave")
            row = Row(
                line,
                person,
                day,
                shift,
                time_in,
                time_out,
                kind,
                _text(values.get("remarks"))[:200],
            )
            _measure(row)
        except AttendanceError as error:
            plan.errors.append(f"Row {line} ({number or 'no number'}): {error}.")
            continue
        plan.rows.append(row)
    return plan


def import_sheet(user: User, content: bytes, file_name: str, *, dry_run: bool) -> dict:
    """The template, or the fingerprint machine's own file (P2B-21, device.py), recognised by
    its content."""
    from . import device

    kind, notes = AttendanceImport.Kind.SHEET, []
    if device.is_device_file(content):
        if len(content) > MAX_BYTES:
            raise AttendanceError("The file is larger than 5 MB.")
        kind = AttendanceImport.Kind.DEVICE
        plan, notes = device.check(user, content)
    else:
        plan = check(user, content)
    calendar = periods.calendar()
    months = sorted({calendar.month_of(r.day).isoformat()[:7] for r in plan.rows})
    summary = {
        "rows": len(plan.rows),
        "employees": len({r.employee.pk for r in plan.rows}),
        "months": months,
        "leave_days": sum(1 for r in plan.rows if r.leave_type),
        "source": kind,
        "notes": notes[:200],
    }
    if plan.errors:
        return summary | {"errors": plan.errors[:100], "saved": False}
    if not plan.rows:
        return summary | {"errors": ["The file has no attendance rows."], "saved": False}
    if dry_run:
        return summary | {"errors": [], "saved": False}
    with audit_context("attendance_imported", file_name), transaction.atomic():
        source = AttendanceImport.objects.create(
            kind=kind,
            file_name=(file_name or "attendance.xlsx")[:200],
            sha256=hashlib.sha256(content).hexdigest(),
            rows=len(plan.rows),
            created_by=user,
        )
        for r in plan.rows:
            AttendanceDay.objects.update_or_create(
                employee=r.employee,
                date=r.day,
                defaults={
                    "shift": r.shift,
                    "time_in": r.time_in,
                    "time_out": r.time_out,
                    "leave_type": r.leave_type,
                    "remarks": r.remarks,
                    "worked_minutes": r.worked,
                    "late_minutes": r.late,
                    "early_minutes": r.early,
                    "source": source,
                },
            )
    return summary | {"errors": [], "saved": True}


def template() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Attendance"
    sheet.append([label for _, label in COLUMNS])
    start, end = periods.pay_period(periods.pay_month_of(date(2026, 11, 2)))
    sheet.append(
        [
            "E001",
            start,
            "08:00",
            "17:00",
            "",
            "",
            f"Example row: delete it. A pay month runs from {start:%d %b} to {end:%d %b}.",
        ]
    )
    for column in "ABCDEFG":
        sheet.column_dimensions[column].width = 16
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


# --- The pay month -------------------------------------------------------------------------------


@dataclass
class Summary:
    employee: Employee
    working_days: int
    days_worked: int
    minutes_worked: int
    late_days: int
    late_minutes: int
    early_minutes: int
    leave_days: Decimal
    absent_days: int


def month_summary(user: User, division: Division, month: date) -> list[Summary]:
    """Per employee of the division: days and minutes worked, late, leave and days absent
    (working days, Monday to Saturday without holidays, with neither attendance nor leave)."""
    return month_summary_for(employees.visible(user), division, month)


def month_summary_for(people, division: Division, month: date) -> list[Summary]:
    first, last_day = periods.pay_period(first_of(month))
    end = min(last_day, timezone.localdate())
    off = leave.holidays_between(first, last_day)
    people = people.filter(division=division, join_date__lte=last_day)
    people = people.exclude(leaving_date__lt=first).select_related("division")
    days = {}
    for d in AttendanceDay.objects.filter(employee__in=people, date__range=(first, last_day)):
        days.setdefault(d.employee_id, {})[d.date] = d
    leaves = {}
    for x in Leave.objects.filter(
        employee__in=people,
        status=Leave.Status.APPROVED,
        start__lte=last_day,
        end__gte=first,
    ):
        current = max(x.start, first)
        while current <= min(x.end, last_day):
            leaves.setdefault(x.employee_id, {})[current] = x.days if x.half_day else Decimal(1)
            current += timedelta(days=1)
    out = []
    for p in people:
        mine, away = days.get(p.pk, {}), leaves.get(p.pk, {})
        working = absent = 0
        leave_days = Decimal(0)
        current = max(first, p.join_date)
        last = min(end, p.leaving_date or end)
        while current <= last:
            if current.weekday() != 6 and current not in off:
                working += 1
                d = mine.get(current)
                if current in away:
                    leave_days += away[current]
                elif d is not None and d.leave_type is not None:
                    leave_days += Decimal("0.5") if d.time_in else Decimal(1)
                elif d is None:
                    absent += 1
            current += timedelta(days=1)
        present = [d for d in mine.values() if d.time_in is not None]
        out.append(
            Summary(
                employee=p,
                working_days=working,
                days_worked=len(present),
                minutes_worked=sum(d.worked_minutes for d in present),
                late_days=sum(1 for d in present if d.late_minutes),
                late_minutes=sum(d.late_minutes for d in present),
                early_minutes=sum(d.early_minutes for d in present),
                leave_days=leave_days,
                absent_days=absent,
            )
        )
    return out


def _division(user: User, code) -> Division:
    found = division_scope(user).filter(code=str(code or "").upper()).first()
    if found is None:
        raise AttendanceError("Choose one of your divisions.")
    return found


def confirm(user: User, division_code, month) -> AttendanceMonth:
    """HR confirms the pay month: the sheet's leave codes become leave records, then the days are
    fixed. All or nothing: every problem is listed and nothing is saved if one fails."""
    if not employees.can_edit(user):
        raise AttendanceError("Only HR confirms attendance.")
    division, month = _division(user, division_code), first_of(month)
    first, last_day = periods.pay_period(month)
    if last_day >= timezone.localdate():
        raise AttendanceError(
            f"Pay month {month:%B %Y} runs to {last_day:%d %B}; it is confirmed after it has ended."
        )
    with (
        audit_context("attendance_confirmed", f"{division.code} {month:%Y-%m}"),
        transaction.atomic(),
    ):
        record, _ = AttendanceMonth.objects.select_for_update().get_or_create(
            division=division, month=month
        )
        if record.confirmed:
            raise AttendanceError(
                f"Pay month {month:%B %Y} is already confirmed for {division.code}."
            )
        problems = []
        sheet = AttendanceDay.objects.filter(
            employee__division=division,
            date__range=(first, last_day),
            leave_type__isnull=False,
        ).select_related("employee", "leave_type")
        for d in sheet.order_by("employee__number", "date"):
            covered = Leave.objects.filter(
                employee=d.employee,
                status__in=leave.OPEN,
                start__lte=d.date,
                end__gte=d.date,
            ).first()
            if covered is not None:
                if covered.leave_type_id != d.leave_type_id:
                    problems.append(
                        f"{d.employee.number} {d.date}: the sheet says {d.leave_type.code}, "
                        f"but {covered.leave_type.name.lower()} is recorded."
                    )
                continue
            try:
                with transaction.atomic():
                    leave.record(
                        user,
                        d.employee,
                        d.leave_type,
                        d.date,
                        half_day=d.time_in is not None,
                        reason="From the attendance sheet",
                        source=Leave.Source.ATTENDANCE,
                    )
            except LeaveError as error:
                problems.append(f"{d.employee.number} {d.date}: {error}")
        if problems:
            raise AttendanceError(" ".join(["Not confirmed."] + problems[:30]))
        record.confirmed = True
        record.confirmed_by, record.confirmed_at = user, timezone.now()
        record.save()
        return record


def reopen(user: User, division_code, month, reason: str) -> AttendanceMonth:
    if not employees.can_edit(user):
        raise AttendanceError("Only HR reopens attendance.")
    reason = " ".join((reason or "").split())
    if not reason:
        raise AttendanceError("Give the reason for reopening the month.")
    division, month = _division(user, division_code), first_of(month)
    first, last_day = periods.pay_period(month)
    with audit_context("attendance_reopened", reason), transaction.atomic():
        record = (
            AttendanceMonth.objects.select_for_update()
            .filter(division=division, month=month, confirmed=True)
            .first()
        )
        if record is None:
            raise AttendanceError(f"Pay month {month:%B %Y} is not confirmed for {division.code}.")
        # P2B-06: refused once a payroll for the month is sent or approved.
        if PayrollRun.objects.filter(
            division=division, month=month, status__in=["awaiting", "approved"]
        ).exists():
            raise AttendanceError(
                f"The payroll for pay month {month:%B %Y} is sent or approved; its attendance "
                "stays as it is."
            )
        taken = Leave.objects.filter(
            employee__division=division,
            source=Leave.Source.ATTENDANCE,
            status=Leave.Status.APPROVED,
            start__range=(first, last_day),
        )
        for x in taken:
            leave.cancel(user, x, f"Attendance reopened: {reason}")
        # Overtime checked on the month no longer stands (P2B-05).
        OvertimeCheck.objects.filter(employee__division=division, month=month, voided=False).update(
            voided=True
        )
        record.confirmed, record.confirmed_by, record.confirmed_at = False, None, None
        record.save()
        return record
