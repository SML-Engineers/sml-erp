"""Attendance from the Excel sheet: checked first, all or nothing; minutes worked, late and
early; the month confirmed by HR, its leave codes recorded, then fixed (backlog P2B-04)."""

import io
from datetime import date, time

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone
from openpyxl import Workbook

from apps.core.models import AuditEvent
from apps.masters.models import Shift
from apps.payroll import attendance, employees, leave, periods
from apps.payroll.attendance import COLUMNS, AttendanceError
from apps.payroll.models import AttendanceDay, Leave, LeaveType

from .test_access import as_user, person
from .test_employees import values

pytestmark = pytest.mark.django_db

OCT = date(2026, 10, 1)


@pytest.fixture
def hr():
    return person("hr@sml.lk", "hr_payroll_officer", all_divisions=True)


@pytest.fixture
def kamal(hr):
    return employees.create(hr, values(join_date="2024-01-15"))


@pytest.fixture
def shifts():
    day = Shift.objects.create(
        code="DX", name="Day test", start_time=time(8), end_time=time(17), break_minutes=60
    )
    night = Shift.objects.create(
        code="NX", name="Night test", start_time=time(22), end_time=time(6), break_minutes=30
    )
    return day, night


def sheet(rows) -> bytes:
    book = Workbook()
    ws = book.active
    ws.append([label for _, label in COLUMNS])
    for row in rows:
        ws.append([row.get(key) for key, _ in COLUMNS])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def row(day=2, **extra):
    return {
        "number": "E001",
        "date": date(2026, 10, day),
        "time_in": "08:00",
        "time_out": "17:00",
    } | extra


def upload(hr, rows, dry_run=False):
    return attendance.import_sheet(hr, sheet(rows), "oct.xlsx", dry_run=dry_run)


def test_the_sheet_is_checked_first_then_saved_with_minutes_worked_late_and_early(
    hr, kamal, shifts
):
    rows = [
        row(1, shift="dx", time_in="08:10", time_out="16:50"),
        row(2, shift="NX", time_in="22:05", time_out="06:00"),  # night shift past midnight
        row(3, time_in=time(8, 0), time_out=time(12, 0), leave="casual"),  # half a day of leave
    ]
    result = upload(hr, rows, dry_run=True)
    assert (result["rows"], result["saved"], result["errors"]) == (3, False, [])
    assert AttendanceDay.objects.count() == 0
    assert upload(hr, rows)["saved"] is True
    one = AttendanceDay.objects.get(date=date(2026, 10, 1))
    assert (one.worked_minutes, one.late_minutes, one.early_minutes) == (460, 10, 10)
    two = AttendanceDay.objects.get(date=date(2026, 10, 2))
    assert (two.worked_minutes, two.late_minutes, two.early_minutes) == (445, 5, 0)
    assert AuditEvent.objects.filter(event="attendance_imported").exists()


def test_every_wrong_row_is_listed_and_nothing_is_saved(hr, kamal, shifts):
    tomorrow = timezone.localdate().toordinal() + 1
    rows = [
        row(1),
        row(2, number="E999"),
        row(3, time_in="8 o'clock"),
        row(5, time_out=None),
        row(6, shift="ZZ"),
        row(7, leave="HOLIDAY", time_in=None, time_out=None),
        row(1),
        row(8, time_in=None, time_out=None),
        {
            "number": "E001",
            "date": date.fromordinal(tomorrow),
            "time_in": "08:00",
            "time_out": "17:00",
        },
        {"number": "E001", "date": date(2023, 1, 2), "time_in": "08:00", "time_out": "17:00"},
    ]
    result = upload(hr, rows)
    assert result["saved"] is False
    messages = " | ".join(result["errors"])
    for text in (
        "Row 3 (E999): no employee E999",
        "Row 4 (E001): the time in",
        "both time in and time out",
        "no shift ZZ",
        "no leave code HOLIDAY",
        "appear twice",
        "give the times, or a leave code",
        "in the future",
        "not employed on that date",
    ):
        assert text in messages, text
    assert AttendanceDay.objects.count() == 0


def test_a_later_sheet_replaces_the_day_while_the_month_is_open(hr, kamal):
    upload(hr, [row(2)])
    upload(hr, [row(2, time_out="18:00", remarks="Stayed late")])
    day = AttendanceDay.objects.get()
    assert (day.time_out, day.remarks, day.worked_minutes) == (time(18), "Stayed late", 600)


def test_the_month_summary_counts_days_worked_leave_and_absent(hr, kamal):
    leave.add_holiday(hr, {"date": "2026-10-06", "name": "Vap Poya", "kind": "poya"})
    upload(hr, [row(1), row(2), row(3, time_in=None, time_out=None, leave="CASUAL")])
    [s] = attendance.month_summary(hr, kamal.division, OCT)
    # Pay month October 2026 (21 Sep - 20 Oct): 30 days, 4 Sundays and one Poya day leave 25
    # working days.
    assert (s.working_days, s.days_worked, s.leave_days, s.absent_days) == (25, 2, 1, 22)
    assert s.minutes_worked == 18 * 60


def test_confirming_records_the_leave_and_fixes_the_days(hr, kamal):
    upload(hr, [row(1), row(2, time_in=None, time_out=None, leave="CASUAL")])
    with pytest.raises(AttendanceError, match="Not confirmed.*0.0 days of casual leave left"):
        attendance.confirm(hr, "WS", "2026-10")
    leave.grant_year(hr, 2026)
    response = as_user(hr).post(
        "/api/v1/attendance/confirm/", {"division": "WS", "month": "2026-10"}, format="json"
    )
    assert response.status_code == 200, response.json()
    taken = Leave.objects.get(employee=kamal)
    assert (taken.source, taken.status, taken.start) == (
        "attendance",
        "approved",
        date(2026, 10, 2),
    )
    with pytest.raises(AttendanceError, match="already confirmed"):
        attendance.confirm(hr, "WS", "2026-10")
    # The confirmed days never change.
    assert "is confirmed for WS" in " ".join(upload(hr, [row(5)])["errors"])
    with pytest.raises(DatabaseError), transaction.atomic():
        AttendanceDay.objects.filter(date=date(2026, 10, 1)).update(remarks="changed")
    with pytest.raises(DatabaseError), transaction.atomic():
        AttendanceDay.objects.filter(date=date(2026, 10, 1)).delete()


def test_reopening_needs_a_reason_and_cancels_the_leave_from_the_sheet(hr, kamal):
    leave.grant_year(hr, 2026)
    upload(hr, [row(1), row(2, time_in=None, time_out=None, leave="CASUAL")])
    attendance.confirm(hr, "WS", "2026-10")
    with pytest.raises(AttendanceError, match="reason"):
        attendance.reopen(hr, "WS", "2026-10", "")
    attendance.reopen(hr, "WS", "2026-10", "Wrong sheet")
    assert Leave.objects.get(employee=kamal).status == "cancelled"
    assert upload(hr, [row(5)])["saved"] is True


def test_leave_already_recorded_by_hr_is_not_recorded_twice(hr, kamal):
    leave.grant_year(hr, 2026)
    leave.record(hr, kamal, LeaveType.objects.get(code="CASUAL"), "2026-10-02")
    upload(hr, [row(2, time_in=None, time_out=None, leave="CASUAL")])
    attendance.confirm(hr, "WS", "2026-10")
    assert Leave.objects.filter(employee=kamal).count() == 1


def test_a_sheet_that_disagrees_with_recorded_leave_is_not_confirmed(hr, kamal):
    leave.grant_year(hr, 2026)
    leave.record(hr, kamal, LeaveType.objects.get(code="ANNUAL"), "2026-10-02")
    upload(hr, [row(2, time_in=None, time_out=None, leave="CASUAL")])
    with pytest.raises(AttendanceError, match="the sheet says CASUAL, but annual leave"):
        attendance.confirm(hr, "WS", "2026-10")


def test_the_current_month_is_confirmed_only_after_it_ends(hr, kamal):
    current = periods.pay_month_of(timezone.localdate())
    with pytest.raises(AttendanceError, match="after it has ended"):
        attendance.confirm(hr, "WS", current.isoformat()[:7])


def test_who_sees_and_uploads_attendance(hr, kamal):
    director = person("director@sml.lk", "director", all_divisions=True)
    upload(hr, [row(1)])
    body = as_user(director).get("/api/v1/attendance/?division=WS&month=2026-10").json()
    assert body["rows"][0]["days_worked"] == 1
    assert body["can_edit"] is False
    days = as_user(director).get(f"/api/v1/employees/{kamal.pk}/attendance/?month=2026-10").json()
    assert days["days"][0]["worked"] == "9:00"
    upload_file = io.BytesIO(sheet([row(2)]))
    upload_file.name = "oct.xlsx"
    response = as_user(director).post(
        "/api/v1/attendance/import/", {"file": upload_file}, format="multipart"
    )
    assert response.status_code == 403
    accountant = person("acc@sml.lk", "accountant", all_divisions=True)
    assert as_user(accountant).get("/api/v1/attendance/").status_code == 403
    response = as_user(hr).get("/api/v1/attendance/template/")
    assert response.status_code == 200 and response.content[:2] == b"PK"
