"""Holidays and leave: the year's holidays, leave types granted by the Shop and Office
Employees Act rules, balances, leave recorded, applied for and approved (backlog P2B-03)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core.models import AuditEvent
from apps.payroll import employees, leave
from apps.payroll.leave import LeaveError
from apps.payroll.models import Holiday, Leave, LeaveGrant, LeaveType

from .test_access import as_user, person
from .test_employees import values

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def hr():
    return person("hr@sml.lk", "hr_payroll_officer", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def staff(hr, joined="2024-01-15", n=1):
    return employees.create(hr, values(number=f"E{n:03}", nic=f"19901234567{n}", join_date=joined))


def t(code):
    return LeaveType.objects.get(code=code)


# --- Entitlements ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "joined, year, annual, casual",
    [
        ("2025-02-10", 2025, "0", "5.0"),  # first year: no annual; 10 completed months
        ("2025-01-01", 2025, "0", "6.0"),  # joined on the 1st: 12 months, half a day each
        ("2025-02-10", 2026, "14", "7"),  # joined in the 1st quarter: 14 days the next year
        ("2025-05-20", 2026, "10", "7"),
        ("2025-08-01", 2026, "7", "7"),
        ("2025-11-30", 2026, "4", "7"),
        ("2023-06-01", 2026, "14", "7"),  # later years: the full days
        ("2027-01-01", 2026, "0", "0"),  # not joined yet
    ],
)
def test_entitlements_follow_the_shop_and_office_act(hr, joined, year, annual, casual):
    e = staff(hr, joined)
    assert leave.entitlement(e, t("ANNUAL"), year) == D(annual)
    assert leave.entitlement(e, t("CASUAL"), year) == D(casual)
    assert leave.entitlement(e, t("NOPAY"), year) is None


def test_granting_the_year_is_done_once_and_adds_only_new_joiners(hr):
    old = staff(hr, "2023-06-01", 1)
    made = leave.grant_year(hr, 2025)
    assert made == {"employees": 1, "grants": 2}
    assert leave.grant_year(hr, 2025) == {"employees": 0, "grants": 0}
    staff(hr, "2025-03-01", 2)
    assert leave.grant_year(hr, 2025)["employees"] == 1  # casual leave for the joiner
    assert {b.leave_type.code: b.available for b in leave.balances(old, 2025)} == {
        "ANNUAL": D("14"),
        "CASUAL": D("7"),
    }
    assert AuditEvent.objects.filter(event="leave_year_granted").exists()


def test_carry_forward_only_where_the_type_allows(hr):
    e = staff(hr, "2023-06-01")
    leave.grant_year(hr, 2025)
    leave.record(hr, e, t("ANNUAL"), "2025-03-03", "2025-03-08")  # 6 days, 8 left
    leave.grant_year(hr, 2026)
    assert leave.balance(e, t("ANNUAL"), 2026).granted == D("14")  # no carry-forward default
    leave.save_leave_type(hr, {"carry_forward_max": "5"}, t("ANNUAL"), "Company policy")
    leave.grant_year(hr, 2026)
    assert leave.balance(e, t("ANNUAL"), 2026).granted == D("19")


def test_grants_are_never_changed(hr):
    e = staff(hr, "2023-06-01")
    leave.grant_year(hr, 2025)
    grant = LeaveGrant.objects.filter(employee=e).first()
    with pytest.raises(DatabaseError), transaction.atomic():
        LeaveGrant.objects.filter(pk=grant.pk).update(days=D("30"))
    with pytest.raises(DatabaseError), transaction.atomic():
        LeaveGrant.objects.filter(pk=grant.pk).delete()


def test_an_adjustment_needs_a_reason_and_cannot_make_the_balance_negative(hr):
    e = staff(hr, "2023-06-01")
    leave.grant_year(hr, 2025)
    with pytest.raises(LeaveError, match="reason"):
        leave.adjust(hr, e, t("CASUAL"), 2025, "1", "")
    with pytest.raises(LeaveError, match="below zero"):
        leave.adjust(hr, e, t("CASUAL"), 2025, "-8", "Wrong")
    with pytest.raises(LeaveError, match="half days"):
        leave.adjust(hr, e, t("CASUAL"), 2025, "0.3", "Wrong")
    leave.adjust(hr, e, t("CASUAL"), 2025, "1.5", "Worked on a Poya day")
    assert leave.balance(e, t("CASUAL"), 2025).available == D("8.5")


# --- Holidays and working days ----------------------------------------------------------------


def test_leave_days_skip_sundays_and_holidays(hr):
    leave.add_holiday(
        hr, {"date": "2025-04-14", "name": "Sinhala and Tamil New Year", "kind": "public"}
    )
    # Mon 7 April to Mon 14 April 2025: Sunday the 13th and the holiday on the 14th not counted.
    assert leave.working_days(date(2025, 4, 7), date(2025, 4, 14)) == 6
    with pytest.raises(LeaveError, match="already a holiday"):
        leave.add_holiday(hr, {"date": "2025-04-14", "name": "Again"})


def test_a_past_holiday_is_kept_and_a_future_one_can_be_removed(hr):
    past = leave.add_holiday(hr, {"date": "2025-12-25", "name": "Christmas Day", "kind": "public"})
    with pytest.raises(LeaveError, match="passed"):
        leave.remove_holiday(hr, past, "Wrong")
    with pytest.raises(DatabaseError), transaction.atomic():
        Holiday.objects.filter(pk=past.pk).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        Holiday.objects.filter(pk=past.pk).update(name="Changed")
    soon = timezone.localdate() + timedelta(days=30)
    future = leave.add_holiday(
        hr, {"date": soon.isoformat(), "name": "Company day", "kind": "company"}
    )
    response = as_user(hr).delete(
        f"/api/v1/holidays/{future.pk}/", {"reason": "Cancelled"}, format="json"
    )
    assert response.status_code == 204
    assert AuditEvent.objects.filter(event="holiday_removed", reason="Cancelled").exists()


def test_only_hr_keeps_holidays_and_leave_types(director):
    response = as_user(director).post(
        "/api/v1/holidays/", {"date": "2027-01-15", "name": "Thai Pongal"}, format="json"
    )
    assert response.status_code == 403
    assert as_user(director).get("/api/v1/holidays/?year=2027").json()["can_manage"] is False
    accountant = person("acc@sml.lk", "accountant", all_divisions=True)
    assert as_user(accountant).get("/api/v1/holidays/").status_code == 403


# --- Leave types -------------------------------------------------------------------------------


def test_leave_types_are_kept_by_hr_and_never_deleted(hr):
    sick = leave.save_leave_type(
        hr, {"code": "sick", "name": "Sick leave", "rule": "fixed", "days": "7"}
    )
    assert (sick.code, sick.days, sick.paid) == ("SICK", D("7"), True)
    with pytest.raises(LeaveError, match="reason"):
        leave.save_leave_type(hr, {"days": "14"}, sick)
    with pytest.raises(LeaveError, match="never changes"):
        leave.save_leave_type(hr, {"code": "ILL"}, sick, "x")
    with pytest.raises(LeaveError, match="days granted"):
        leave.save_leave_type(hr, {"code": "X", "name": "X", "rule": "fixed", "days": "0"})
    with pytest.raises(DatabaseError), transaction.atomic():
        LeaveType.objects.filter(code="SICK").delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        LeaveType.objects.filter(code="SICK").update(code="ILL")


# --- Recording, applying and approving ---------------------------------------------------------


def test_hr_records_leave_and_the_balance_goes_down(hr):
    e = staff(hr, "2023-06-01")
    leave.grant_year(hr, 2025)
    response = as_user(hr).post(
        "/api/v1/leave/",
        {"employee": e.pk, "leave_type": "casual", "start": "2025-06-02", "end": "2025-06-03"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["status"] == "approved"
    half = leave.record(hr, e, t("CASUAL"), "2025-06-04", half_day=True)
    assert half.days == D("0.5")
    assert leave.balance(e, t("CASUAL"), 2025).available == D("4.5")


@pytest.mark.parametrize(
    "kind, start, end, extra, message",
    [
        ("CASUAL", "2025-06-10", "2025-06-09", {}, "before the first day"),
        ("CASUAL", "2025-12-31", "2026-01-02", {}, "new year"),
        ("CASUAL", "2025-06-10", "2025-06-11", {"half_day": True}, "one day only"),
        ("CASUAL", "2025-06-08", "2025-06-08", {}, "Sundays or holidays"),
        ("CASUAL", "2023-01-02", "2023-01-02", {}, "before the employee joined"),
        ("CASUAL", "2025-06-02", "2025-06-12", {}, "7.0 days of casual leave left"),
    ],
)
def test_wrong_leave_is_refused(hr, kind, start, end, extra, message):
    e = staff(hr, "2023-06-01")
    leave.grant_year(hr, 2025)
    with pytest.raises(LeaveError, match=message):
        leave.record(hr, e, t(kind), start, end, **extra)


def test_overlapping_leave_is_refused_and_no_pay_leave_has_no_balance(hr):
    e = staff(hr, "2023-06-01")
    leave.record(hr, e, t("NOPAY"), "2025-06-02", "2025-06-20")  # no balance kept
    with pytest.raises(LeaveError, match="already has leave"):
        leave.record(hr, e, t("NOPAY"), "2025-06-20", "2025-06-21")


def test_leave_applied_for_waits_for_hr_and_nobody_approves_their_own(hr):
    clerk = person("kamal@sml.lk", "clerk", divisions=["WS"])
    e = staff(hr, "2023-06-01")
    employees.update(hr, e, {"user": clerk.pk})
    e.refresh_from_db()
    leave.grant_year(hr, 2025)
    applied = leave.record(clerk, e, t("ANNUAL"), "2025-07-07", "2025-07-09", source="applied")
    assert applied.status == "applied"
    assert leave.balance(e, t("ANNUAL"), 2025).pending == D("3")
    other = person("hr2@sml.lk", "hr_payroll_officer", all_divisions=True)
    with pytest.raises(LeaveError, match="reason for rejecting"):
        leave.decide(other, applied, False)
    approved = leave.decide(other, applied, True)
    assert approved.status == "approved"
    # HR who is also the employee cannot approve their own application.
    me = staff(hr, "2023-06-01", 2)
    employees.update(hr, me, {"user": other.pk})
    me.refresh_from_db()
    leave.grant_year(hr, 2025)
    mine = leave.record(other, me, t("ANNUAL"), "2025-07-07", source="applied")
    with pytest.raises(LeaveError, match="own leave"):
        leave.decide(other, mine, True)
    with pytest.raises(LeaveError, match="own leave only"):
        leave.record(clerk, me, t("ANNUAL"), "2025-08-04", source="applied")


def test_leave_is_cancelled_not_deleted_and_never_changed(hr):
    e = staff(hr, "2023-06-01")
    leave.grant_year(hr, 2025)
    taken = leave.record(hr, e, t("CASUAL"), "2025-06-02")
    with pytest.raises(LeaveError, match="reason"):
        leave.cancel(hr, taken, "")
    response = as_user(hr).post(
        f"/api/v1/leave/{taken.pk}/cancel/", {"reason": "Came to work"}, format="json"
    )
    assert response.status_code == 200, response.json()
    assert leave.balance(e, t("CASUAL"), 2025).available == D("7")
    with pytest.raises(DatabaseError), transaction.atomic():
        Leave.objects.filter(pk=taken.pk).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        Leave.objects.filter(pk=taken.pk).update(days=D("2"))


def test_the_director_sees_leave_and_balances_but_does_not_record_them(hr, director):
    e = staff(hr, "2023-06-01")
    leave.grant_year(hr, 2025)
    leave.record(hr, e, t("CASUAL"), "2025-06-02")
    body = as_user(director).get(f"/api/v1/employees/{e.pk}/leave/balances/?year=2025").json()
    rows = {b["leave_type"]: b for b in body["balances"]}
    assert (rows["CASUAL"]["taken"], rows["CASUAL"]["available"]) == ("1.0", "6.0")
    assert body["can_adjust"] is False
    response = as_user(director).post(
        "/api/v1/leave/",
        {"employee": e.pk, "leave_type": "CASUAL", "start": "2025-06-03"},
        format="json",
    )
    assert response.status_code == 403
    assert (
        as_user(director).post("/api/v1/leave/grant/", {"year": 2025}, format="json").status_code
        == 403
    )
