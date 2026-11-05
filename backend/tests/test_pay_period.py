"""The pay period, the 21st to the 20th (backlog P2B-15; owner, 5 Nov 2026): attendance,
overtime and short leave per pay month; the dated pay period rule; the database follows the
same periods."""

from datetime import date, time, timedelta

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.masters.models import Shift
from apps.payroll import attendance, employees, overtime, periods
from apps.payroll.attendance import AttendanceError
from apps.payroll.models import AttendanceDay, PayPeriodRule, WorkRule
from apps.payroll.periods import PeriodError

from .test_access import as_user, person
from .test_attendance import upload
from .test_employees import values

pytestmark = pytest.mark.django_db

OCT, NOV, DEC = date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)


@pytest.fixture
def hr():
    return person("hr@sml.lk", "hr_payroll_officer", all_divisions=True)


@pytest.fixture
def kamal(hr):
    return employees.create(hr, values(join_date="2024-01-15"))


def day(d: date, **extra):
    return {"number": "E001", "date": d, "time_in": "08:00", "time_out": "17:00"} | extra


def sql_pay_month(d: date) -> date:
    with connection.cursor() as cursor:
        cursor.execute("SELECT payroll_pay_month(%s)", [d])
        return cursor.fetchone()[0]


def test_a_pay_month_runs_from_the_21st_to_the_20th():
    assert periods.pay_period(NOV) == (date(2026, 10, 21), date(2026, 11, 20))
    assert periods.pay_period(date(2027, 1, 1)) == (date(2026, 12, 21), date(2027, 1, 20))
    assert periods.pay_period(date(2027, 3, 1)) == (date(2027, 2, 21), date(2027, 3, 20))
    assert periods.pay_month_of(date(2026, 11, 20)) == NOV
    assert periods.pay_month_of(date(2026, 11, 21)) == DEC
    assert periods.pay_month_of(date(2026, 12, 31)) == date(2027, 1, 1)
    assert periods.label(NOV) == {"month": "2026-11", "start": "2026-10-21", "end": "2026-11-20"}


def test_the_database_finds_the_same_pay_month(hr):
    periods.add_rule(hr, {"effective_from": "2027-03", "start_day": 1, "reason": "Calendar"})
    current = date(2026, 9, 1)
    while current < date(2027, 6, 1):
        assert sql_pay_month(current) == periods.pay_month_of(current), current
        current += timedelta(days=1)
    # The change of rule leaves no gap: pay month February 2027 runs on to 28 February.
    assert periods.pay_period(date(2027, 2, 1)) == (date(2027, 1, 21), date(2027, 2, 28))
    assert periods.pay_period(date(2027, 3, 1)) == (date(2027, 3, 1), date(2027, 3, 31))


def test_the_sheet_and_the_summary_follow_the_pay_month(hr, kamal):
    result = upload(hr, [day(date(2026, 10, 20)), day(date(2026, 10, 21))])
    assert (result["saved"], result["months"]) == (True, ["2026-10", "2026-11"])
    [october] = attendance.month_summary(hr, kamal.division, OCT)
    [november] = attendance.month_summary(hr, kamal.division, NOV)
    assert (october.days_worked, november.days_worked) == (1, 1)
    body = as_user(hr).get("/api/v1/attendance/?division=WS&month=2026-11").json()
    assert body["period"] == {"month": "2026-11", "start": "2026-10-21", "end": "2026-11-20"}
    days = as_user(hr).get(f"/api/v1/employees/{kamal.pk}/attendance/?month=2026-11").json()
    assert [d["date"] for d in days["days"]] == ["2026-10-21"]


def test_confirming_a_pay_month_freezes_only_its_days(hr, kamal):
    upload(hr, [day(date(2026, 10, 20)), day(date(2026, 10, 21))])
    attendance.confirm(hr, "WS", "2026-10")
    # 20 October is in the confirmed pay month; 21 October starts pay month November.
    errors = " ".join(upload(hr, [day(date(2026, 10, 20), time_out="18:00")])["errors"])
    assert "pay month October 2026 is confirmed for WS" in errors
    assert upload(hr, [day(date(2026, 10, 21), time_out="18:00")])["saved"] is True
    with pytest.raises(DatabaseError), transaction.atomic():
        AttendanceDay.objects.filter(date=date(2026, 10, 20)).update(remarks="changed")
    AttendanceDay.objects.filter(date=date(2026, 10, 21)).update(remarks="still open")


def test_a_pay_month_is_confirmed_only_after_its_last_day(hr, kamal):
    current = periods.pay_month_of(timezone.localdate())
    with pytest.raises(AttendanceError, match="runs to .*after it has ended"):
        attendance.confirm(hr, "WS", current.isoformat()[:7])
    assert periods.last_pay_month() == periods.previous_month(current)


def test_short_leave_is_counted_per_pay_month(hr, kamal):
    Shift.objects.create(
        code="DX", name="Day test", start_time=time(8), end_time=time(17), break_minutes=60
    )
    # 30 minutes late on three days: two in pay month October, one in pay month November.
    # By calendar month the third would be beyond the 2 short leaves and become no-pay time.
    late = {"shift": "DX", "time_in": "08:30"}
    upload(
        hr,
        [
            day(date(2026, 10, 19), **late),
            day(date(2026, 10, 20), **late),
            day(date(2026, 10, 22), **late),
        ],
    )
    october = overtime.work_out(kamal, OCT, 0)
    november = overtime.work_out(kamal, NOV, 0)
    assert october.rule.short_leaves_per_month == 2
    assert (october.short_leaves, october.nopay_minutes) == (2, 0)
    assert (november.short_leaves, november.nopay_minutes) == (1, 0)


def test_overtime_is_shown_and_checked_per_pay_month(hr, kamal):
    director = person("director@sml.lk", "director", all_divisions=True)
    upload(hr, [day(date(2026, 10, 20), time_out="19:00"), day(date(2026, 10, 21))])
    attendance.confirm(hr, "WS", "2026-10")
    body = as_user(director).get("/api/v1/overtime/?division=WS&month=2026-10").json()
    assert body["period"]["start"] == "2026-09-21"
    assert body["rows"][0]["ot_working"] == "3:00"  # 20 October, 11 hours without a shift
    with pytest.raises(overtime.OvertimeError, match="pay month November 2026"):
        overtime.check(director, "WS", "2026-11", [kamal.pk])
    assert overtime.check(director, "WS", "2026-10", [kamal.pk]) == 1


def test_a_work_rule_is_in_force_from_the_first_day_of_its_pay_month(hr):
    current = periods.pay_month_of(timezone.localdate())
    following = periods.next_month(current)
    now = overtime.add_rule(
        hr, "WS", {"effective_from": current.isoformat()[:7], "reason": "This pay month"}
    )
    later = overtime.add_rule(
        hr, "WS", {"effective_from": following.isoformat()[:7], "reason": "Next pay month"}
    )
    assert overtime.in_force(now) and not overtime.in_force(later)
    with pytest.raises(overtime.OvertimeError, match="never withdrawn"):
        overtime.withdraw_rule(hr, now, "Wrong")
    with pytest.raises(DatabaseError), transaction.atomic():
        WorkRule.objects.filter(pk=now.pk).delete()
    overtime.withdraw_rule(hr, later, "Not agreed")


def test_the_pay_period_starts_on_the_21st_by_default():
    rule = PayPeriodRule.objects.get()
    assert (rule.effective_from, rule.start_day) == (date(2024, 1, 1), 21)


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"reason": ""}, "reason"),
        ({"start_day": "29"}, "1 to 28"),
        ({"start_day": "x"}, "1 to 28"),
        ({"effective_from": "next year"}, "first pay month"),
        ({"effective_from": "2024-01"}, "already"),
    ],
)
def test_wrong_pay_period_rules_are_refused(hr, extra, message):
    with pytest.raises(PeriodError, match=message):
        periods.add_rule(hr, {"effective_from": "2027-01", "start_day": 1, "reason": "x"} | extra)


def test_a_new_pay_period_never_moves_a_confirmed_month(hr, kamal):
    upload(hr, [day(date(2026, 10, 20))])
    attendance.confirm(hr, "WS", "2026-10")
    # A rule from pay month November would move the end of the confirmed pay month October.
    with pytest.raises(PeriodError, match="confirmed"):
        periods.add_rule(hr, {"effective_from": "2026-11", "start_day": 1, "reason": "x"})
    rule = periods.add_rule(hr, {"effective_from": "2026-12", "start_day": 26, "reason": "x"})
    assert periods.pay_period(NOV) == (date(2026, 10, 21), date(2026, 11, 25))
    with pytest.raises(DatabaseError), transaction.atomic():
        PayPeriodRule.objects.filter(pk=rule.pk).update(start_day=25)
    with pytest.raises(PeriodError, match="reason"):
        periods.withdraw_rule(hr, rule, "")
    periods.withdraw_rule(hr, rule, "Not agreed")
    # The rule in force since 2024 covers a confirmed month: never withdrawn.
    first = PayPeriodRule.objects.get()
    with pytest.raises(PeriodError, match="confirmed"):
        periods.withdraw_rule(hr, first, "x")
    with pytest.raises(DatabaseError), transaction.atomic():
        PayPeriodRule.objects.filter(pk=first.pk).delete()


def test_who_keeps_the_pay_period(hr):
    director = person("director@sml.lk", "director", all_divisions=True)
    body = as_user(director).get("/api/v1/pay-periods/").json()
    assert body["results"][0]["start_day"] == 21
    assert body["can_manage"] is False
    assert body["current"]["month"] == periods.pay_month_of(timezone.localdate()).isoformat()[:7]
    response = as_user(director).post(
        "/api/v1/pay-periods/",
        {"effective_from": "2027-01", "start_day": 1, "reason": "x"},
        format="json",
    )
    assert response.status_code == 403
    response = as_user(hr).post(
        "/api/v1/pay-periods/",
        {"effective_from": "2027-01", "start_day": 1, "reason": "Calendar months"},
        format="json",
    )
    assert response.status_code == 201, response.json()
    accountant = person("acc@sml.lk", "accountant", all_divisions=True)
    assert as_user(accountant).get("/api/v1/pay-periods/").status_code == 403
