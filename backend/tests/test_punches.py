"""The phone punch clock (backlog P2B-12): employees HR switches on clock in and out from the
phone at the server's time, limited to a site's area only with their consent; HR brings a pay
month's punches into attendance like a sheet."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.masters.models import Shift
from apps.payroll import attendance, employees, punches
from apps.payroll.models import AttendanceDay, Employee, Punch, PunchSite
from apps.payroll.punches import PunchError

from .test_access import as_user, person
from .test_attendance import sheet
from .test_employees import values

pytestmark = pytest.mark.django_db
COLOMBO = ZoneInfo("Asia/Colombo")
OFFICE = {"name": "Colombo office", "latitude": "6.927079", "longitude": "79.861244"}
NEAR = {"latitude": "6.927500", "longitude": "79.861244", "accuracy": 12}  # about 47 m north
FAR = {"latitude": "6.940000", "longitude": "79.861244", "accuracy": 12}  # about 1.4 km


@pytest.fixture
def hr():
    return person("hr@sml.lk", "hr_payroll_officer", all_divisions=True)


@pytest.fixture
def kamal(hr):
    return employees.create(hr, values(join_date="2024-01-15"))


@pytest.fixture
def me(hr, kamal):
    user = person("kamal@sml.lk", divisions=["WS"])
    employees.update(hr, kamal, {"user_email": "kamal@sml.lk"})
    return user


@pytest.fixture
def shifts():
    day = Shift.objects.create(
        code="DX", name="Day test", start_time=time(8), end_time=time(17), break_minutes=60
    )
    night = Shift.objects.create(
        code="NX", name="Night test", start_time=time(22), end_time=time(6), break_minutes=30
    )
    return day, night


def at(monkeypatch, day, hour, minute=0, month=10):
    moment = datetime(2026, month, day, hour, minute, tzinfo=COLOMBO)
    monkeypatch.setattr(timezone, "now", lambda: moment)


def clock(user, kind, **where):
    return as_user(user).post("/api/v1/my/clock/", {"kind": kind, **where}, format="json")


def test_the_phone_clock_is_off_until_hr_switches_it_on(hr, kamal, me):
    assert Employee.objects.get(pk=kamal.pk).phone_clock == "off"
    assert as_user(me).get("/api/v1/my/").json()["clock"] is None
    refused = clock(me, "in")
    assert refused.status_code == 400 and "not switched on" in refused.json()["detail"]
    with pytest.raises(employees.EmployeeError, match="phone clock is one of"):
        employees.update(hr, kamal, {"phone_clock": "always"})
    employees.update(hr, kamal, {"phone_clock": "From anywhere"})
    body = as_user(hr).get(f"/api/v1/employees/{kamal.pk}/").json()
    assert body["phone_clock"] == "anywhere"


def test_clock_in_then_out_at_the_servers_time(hr, kamal, me, monkeypatch):
    employees.update(hr, kamal, {"phone_clock": "anywhere"})
    at(monkeypatch, 1, 8, 5)
    made = clock(me, "in")
    assert made.status_code == 201, made.json()
    state = made.json()["clock"]
    assert (state["clocked_in"], state["since"], state["needs_location"]) == (True, "08:05", False)
    again = clock(me, "in")
    assert again.status_code == 400 and "clocked in at 08:05" in again.json()["detail"]
    at(monkeypatch, 1, 17, 10)
    out = clock(me, "out")
    assert out.status_code == 201 and out.json()["clock"]["clocked_in"] is False
    assert [p["kind"] for p in out.json()["clock"]["recent"]] == ["out", "in"]
    refused = clock(me, "out")
    assert refused.status_code == 400 and "not clocked in" in refused.json()["detail"]
    # No location is asked or kept for "from anywhere".
    assert not Punch.objects.filter(latitude__isnull=False).exists()
    # A clock-in left open for 20 hours is forgotten: the next day starts afresh.
    at(monkeypatch, 2, 8)
    assert clock(me, "in").status_code == 201
    at(monkeypatch, 3, 9)
    assert clock(me, "in").status_code == 201


def test_limited_to_sites_needs_consent_and_the_area(hr, kamal, me, monkeypatch):
    employees.update(hr, kamal, {"phone_clock": "sites"})
    at(monkeypatch, 1, 8)
    assert "not set up any punch sites" in _refused(me, NEAR, consent=True)
    added = as_user(hr).post("/api/v1/punch-sites/", OFFICE, format="json")
    assert added.status_code == 201 and added.json()["radius_m"] == 200
    assert as_user(me).post("/api/v1/punch-sites/", OFFICE, format="json").status_code == 403
    bad = as_user(hr).post("/api/v1/punch-sites/", OFFICE | {"name": "X", "radius_m": 5})
    assert bad.status_code == 400 and "20 to 5,000" in bad.json()["detail"]

    as_user(me).post("/api/v1/my/location-consent/", {"consent": False}, format="json")
    assert "Agree to the location check" in _refused(me, NEAR)
    given = as_user(me).post("/api/v1/my/location-consent/", {"consent": True}, format="json")
    assert given.json()["clock"]["consent"] is True
    assert given.json()["clock"]["sites"] == ["Colombo office"]
    assert "share its location" in _refused(me, {})
    assert "accurate to 500 m" in _refused(me, NEAR | {"accuracy": 500})
    assert "m from the nearest site (Colombo office)" in _refused(me, FAR)

    assert clock(me, "in", **NEAR).status_code == 201
    made = Punch.objects.get()
    assert made.site.name == "Colombo office" and 40 <= made.distance_m <= 55

    withdrawn = as_user(me).post("/api/v1/my/location-consent/", {"consent": False}, format="json")
    assert withdrawn.json()["clock"]["consent"] is False
    assert "Agree to the location check" in _refused(me, NEAR, kind="out")


def _refused(user, where, *, consent=False, kind="in"):
    if consent:
        punches.consent(user, True)
    response = clock(user, kind, **where)
    assert response.status_code == 400, response.json()
    return response.json()["detail"]


def test_punches_never_change_and_sites_are_never_deleted(hr, kamal, me):
    employees.update(hr, kamal, {"phone_clock": "anywhere"})
    made = punches.punch(me, "in")
    with pytest.raises(DatabaseError), transaction.atomic():
        Punch.objects.filter(pk=made.pk).update(kind="out")
    with pytest.raises(DatabaseError), transaction.atomic():
        Punch.objects.filter(pk=made.pk).delete()
    site = punches.add_site(hr, OFFICE)
    with pytest.raises(DatabaseError), transaction.atomic():
        PunchSite.objects.filter(pk=site.pk).delete()
    changed = as_user(hr).patch(f"/api/v1/punch-sites/{site.pk}/", {"is_active": False})
    assert changed.json()["is_active"] is False


def test_hr_brings_a_pay_month_of_punches_into_attendance(hr, kamal, me, shifts, monkeypatch):
    employees.update(hr, kamal, {"phone_clock": "anywhere"})
    for when, kind in [
        ((1, 8, 10), "in"),  # a day shift, 10 minutes late
        ((1, 17, 0), "out"),
        ((2, 22, 5), "in"),  # a night shift, out the next morning
        ((3, 6, 0), "out"),
        ((5, 8, 0), "in"),  # never clocked out
        ((6, 8, 0), "in"),  # the sheet has this day: kept
        ((6, 17, 0), "out"),
    ]:
        at(monkeypatch, *when)
        punches.punch(me, kind)
    at(monkeypatch, 25, 9)
    attendance.import_sheet(
        hr,
        sheet(
            [
                {
                    "number": "E001",
                    "date": date(2026, 10, 6),
                    "time_in": time(7, 30),
                    "time_out": time(16, 30),
                    "shift": "DX",
                }
            ]
        ),
        "sheet.xlsx",
        dry_run=False,
    )
    with pytest.raises(PunchError, match="Only HR"):
        punches.bring_in(me, "2026-10", dry_run=True)
    preview = as_user(hr).post("/api/v1/attendance/punches/", {"month": "2026-10"}).json()
    assert (preview["saved"], preview["days"], preview["punches"]) == (False, 2, 7)
    assert any("08:00 but never out" in n for n in preview["notes"])
    assert any("2026-10-06: kept as entered from the attendance" in n for n in preview["notes"])
    assert not AttendanceDay.objects.filter(date=date(2026, 10, 1)).exists()

    saved = (
        as_user(hr)
        .post("/api/v1/attendance/punches/", {"month": "2026-10", "dry_run": "false"})
        .json()
    )
    assert saved["saved"] is True
    day = AttendanceDay.objects.get(date=date(2026, 10, 1))
    # The active shift starting nearest the clock-in (08:00, test or seeded General).
    assert (day.shift.start_time, day.late_minutes, day.worked_minutes) == (time(8), 10, 470)
    assert day.source.kind == "punches"
    night = AttendanceDay.objects.get(date=date(2026, 10, 2))
    assert (night.shift.code, night.late_minutes, night.worked_minutes) == ("NX", 5, 445)
    assert AttendanceDay.objects.get(date=date(2026, 10, 6)).time_in == time(7, 30)

    # Bringing them in again replaces the days from punches, never duplicates them.
    punches.bring_in(hr, "2026-10", dry_run=False)
    assert AttendanceDay.objects.filter(employee=kamal).count() == 3
    days = as_user(hr).get(f"/api/v1/employees/{kamal.pk}/attendance/?month=2026-10").json()
    assert len(days["punches"]) == 7
    assert any(d["from_punches"] for d in days["days"])
