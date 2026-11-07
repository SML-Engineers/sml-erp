"""Attendance from the fingerprint machine's file (backlog P2B-21; owner, 7 Nov 2026).

The machine exports a "Schedule" report (an Excel 2003 XML file, often named .XLS): for
each person a block with "ID:", "Name:", "Dept:", "Shift:" and "Date: dd/mm/yy~dd/mm/yy",
then one row per day ("mm.dd", weekday) in two side-by-side halves, each day with up to
three IN/OUT pairs of clock times, then the machine's own totals (ignored here).

HR uploads it on the attendance page exactly like the template (P2B-04): it is recognised
by its content, checked first, and saved only when nothing is wrong.

- **Who**: the person's ID on the machine is matched to the employee's **Fingerprint ID**
  (employee page). An ID with punches but no employee is an error to fix first (add the
  Fingerprint ID); a block without any punch is ignored.
- **The day**: time in = the earliest punch, time out = the latest (the machine often
  repeats the same time as OUT and IN). A day with only one punch is listed for HR to enter
  in the sheet and is not brought in. The shift is the active shift starting nearest the
  time in (within 2 hours), for late and early minutes.
- **Kept**: days already entered from the attendance sheet (HR's corrections) and days of
  leave are kept as they are; days from an earlier machine file are replaced. Today is left
  for tomorrow; days outside the employee's employment are listed and skipped; a confirmed
  pay month is an error, as for the sheet.
- Night shifts that cross midnight show as two single punches on two dates; they are listed
  for HR to enter in the sheet.
"""

import re
from datetime import date, time

from defusedxml import ElementTree as ET
from django.utils import timezone

from apps.masters.models import Shift

from . import employees, periods
from .attendance import AttendanceError, Plan, Row, _measure
from .models import AttendanceDay, AttendanceImport, AttendanceMonth

SS = "urn:schemas-microsoft-com:office:spreadsheet"
NS = {"ss": SS}
DAY = re.compile(r"^(\d{1,2})\.(\d{1,2})$")
CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")
RANGE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s*~\s*(\d{1,2})/(\d{1,2})/(\d{2,4})")


def is_device_file(content: bytes) -> bool:
    return SS.encode() in content[:4000] and b"<Worksheet" in content[:20000]


def _rows(content: bytes) -> list[dict[int, str]]:
    if content.startswith(b"\xef\xbb\xbf"):
        content = content[3:]
    # The machine writes no encoding and some non-UTF-8 bytes in its totals lines.
    text = content.decode("utf-8", errors="replace")
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError):  # ValueError: entities or DTDs refused
        raise AttendanceError("The fingerprint machine's file could not be read.") from None
    out = []
    for row in root.iter(f"{{{SS}}}Row"):
        cells, col = {}, 0
        for cell in row.findall("ss:Cell", NS):
            if cell.get(f"{{{SS}}}Index"):
                col = int(cell.get(f"{{{SS}}}Index")) - 1
            data = cell.find("ss:Data", NS)
            cells[col] = " ".join((data.text or "").split()) if data is not None else ""
            col += 1 + int(cell.get(f"{{{SS}}}MergeAcross") or 0)
        out.append(cells)
    return out


def _year(n: int) -> int:
    return n + 2000 if n < 100 else n


def _field(cells: dict, label: str) -> str:
    for value in cells.values():
        if value.startswith(f"{label}:"):
            return value[len(label) + 1 :].strip()
    return ""


def _clock(text: str) -> time | None:
    m = CLOCK.match(text or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return time(int(m.group(1)), int(m.group(2)))


def read(content: bytes) -> list[dict]:
    """The people in the file: {"id", "name", "days": {date: [times]}}."""
    people, current, first, last = [], None, None, None
    for cells in _rows(content):
        if cells.get(0, "").startswith("ID:"):
            m = RANGE.search(_field(cells, "Date"))
            if not m:
                raise AttendanceError("The file's date range (Date: dd/mm/yy~dd/mm/yy) is missing.")
            d1, m1, y1, d2, m2, y2 = (int(x) for x in m.groups())
            first, last = date(_year(y1), m1, d1), date(_year(y2), m2, d2)
            current = {"id": _field(cells, "ID"), "name": _field(cells, "Name"), "days": {}}
            people.append(current)
            continue
        if current is None:
            continue
        for base in sorted(cells):
            m = DAY.match(cells.get(base, ""))
            if not m:
                continue
            month, day = int(m.group(1)), int(m.group(2))
            found = None
            for year in sorted({first.year, last.year}):
                try:
                    candidate = date(year, month, day)
                except ValueError:
                    continue
                if first <= candidate <= last:
                    found = candidate
            if found is None:
                continue
            times = sorted(
                {t for t in (_clock(cells.get(base + 2 + i, "")) for i in range(6)) if t}
            )
            if times:
                current["days"][found] = times
    return people


def check(user, content: bytes) -> tuple[Plan, list[str]]:
    from .punches import nearest_shift

    if not employees.can_edit(user):
        raise AttendanceError("Only HR uploads attendance.")
    people = read(content)
    if not people:
        raise AttendanceError("There is nobody in the fingerprint machine's file.")
    staff = {e.device_id: e for e in employees.visible(user).exclude(device_id="")}
    shifts = list(Shift.objects.filter(is_active=True))
    confirmed = set(
        AttendanceMonth.objects.filter(confirmed=True).values_list("division_id", "month")
    )
    calendar = periods.calendar()
    today = timezone.localdate()
    plan, notes = Plan(), []
    kept = {
        (d.employee_id, d.date)
        for d in AttendanceDay.objects.filter(employee__in=staff.values()).select_related("source")
        if d.source.kind == AttendanceImport.Kind.SHEET or d.leave_type_id
    }
    for p in people:
        if not p["days"]:
            continue
        employee = staff.get(p["id"])
        who = f"ID {p['id']} ({p['name']})"
        if employee is None:
            plan.errors.append(
                f"{who}: no employee has this Fingerprint ID; set it on the employee's page."
            )
            continue
        for day, times in sorted(p["days"].items()):
            label = f"{employee.number} {day:%Y-%m-%d}"
            if day >= today:
                continue
            if day < employee.join_date or (employee.leaving_date and day > employee.leaving_date):
                notes.append(f"{label}: not employed on that date; not brought in.")
                continue
            if len(times) == 1:
                notes.append(
                    f"{label}: only one punch ({times[0]:%H:%M}); enter the day in the sheet."
                )
                continue
            month = calendar.month_of(day)
            if (employee.division_id, month) in confirmed:
                plan.errors.append(
                    f"{label}: pay month {month:%B %Y} is confirmed for {employee.division.code}."
                )
                continue
            if (employee.pk, day) in kept:
                notes.append(f"{label}: kept as entered from the sheet or as leave.")
                continue
            row = Row(
                0,
                employee,
                day,
                nearest_shift(times[0], shifts),
                times[0],
                times[-1],
                None,
                "Fingerprint machine",
            )
            try:
                _measure(row)
            except AttendanceError as error:
                plan.errors.append(f"{label}: {error}.")
                continue
            plan.rows.append(row)
    return plan, notes
