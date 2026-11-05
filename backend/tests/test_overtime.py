"""Overtime and attendance rules: dated work rules; overtime on working days, Sundays and
holidays; short leave and no-pay; the month checked by the supervisor or the Director
(backlog P2B-05)."""

from datetime import date, time
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.core.models import Division
from apps.masters.models import Section, Shift
from apps.payroll import attendance, employees, leave, overtime
from apps.payroll.models import LeaveType, OvertimeCheck, WorkRule
from apps.payroll.overtime import OvertimeError

from .test_access import as_user, person
from .test_attendance import row, upload
from .test_employees import values

pytestmark = pytest.mark.django_db

OCT = date(2026, 10, 1)


@pytest.fixture
def hr():
    return person("hr@sml.lk", "hr_payroll_officer", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def kamal(hr):
    return employees.create(hr, values(join_date="2024-01-15"))


@pytest.fixture
def october(hr, kamal):
    Shift.objects.create(
        code="DX", name="Day test", start_time=time(8), end_time=time(17), break_minutes=60
    )
    leave.add_holiday(hr, {"date": "2026-10-06", "name": "Vap Poya", "kind": "poya"})
    leave.record(hr, kamal, LeaveType.objects.get(code="NOPAY"), "2026-10-12", "2026-10-13")
    upload(
        hr,
        [
            row(1, shift="DX", time_in="08:05", time_out="19:00"),  # 595 worked: 105 overtime
            row(2, time_in="08:00", time_out="17:20"),  # no shift: 560 worked, 75 overtime
            row(3, shift="DX", time_in="08:30", time_out="17:00"),  # 30 late: short leave 1
            row(4, time_in="08:00", time_out="12:10"),  # Sunday: 250 worked, 240 counted
            row(5, shift="DX", time_in="08:00", time_out="15:00"),  # 120 early: no-pay
            row(6, time_in="08:00", time_out="10:20"),  # Poya day: 140 worked, 135 counted
            row(7, shift="DX", time_in="08:00", time_out="17:20"),  # 20 extra: below 30
            row(8, shift="DX", time_in="08:20", time_out="17:00"),  # 20 late: short leave 2
            row(9, shift="DX", time_in="08:15", time_out="17:00"),  # 15 late: none left
        ],
    )
    return kamal


def test_the_month_is_worked_out_by_the_division_rule(october):
    [s] = attendance.month_summary_for(employees.Employee.objects.all(), october.division, OCT)
    m = overtime.work_out(october, OCT, s.absent_days)
    assert (m.ot_working, m.ot_sunday, m.ot_holiday) == (180, 240, 135)
    assert (m.short_minutes, m.short_leaves, m.nopay_minutes) == (185, 2, 135)
    # 26 working days: 7 worked, 2 of no-pay leave, 17 absent.
    assert (m.absent_days, m.unpaid_leave_days, m.nopay_days) == (17, Decimal(2), Decimal(19))
    assert m.rule.rate_working_day == Decimal("1.50")


def test_a_new_rule_applies_from_its_month_and_earlier_months_keep_theirs(hr, october):
    rule = overtime.add_rule(
        hr, "WS", {"effective_from": "2026-10", "grace_minutes": 30, "reason": "Wages Board"}
    )
    assert rule.rate_sunday == Decimal("2.00")  # unchanged values carried from the old rule
    m = overtime.work_out(october, OCT, 0)
    assert (m.short_leaves, m.nopay_minutes) == (0, 120)  # only the early leaving is short now
    assert overtime.work_out(october, date(2026, 9, 1), 0).rule.grace_minutes == 10
    with pytest.raises(DatabaseError), transaction.atomic():
        WorkRule.objects.filter(pk=rule.pk).update(grace_minutes=5)


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"reason": ""}, "reason"),
        ({"rate_sunday": "0.5"}, "between 1 and 5"),
        ({"ot_step_minutes": "0"}, "above 0"),
        ({"grace_minutes": "abc"}, "whole number"),
    ],
)
def test_wrong_rules_are_refused(hr, extra, message):
    with pytest.raises(OvertimeError, match=message):
        overtime.add_rule(hr, "WS", {"effective_from": "2027-01", "reason": "x"} | extra)


def test_a_rule_for_a_confirmed_month_is_refused_and_a_future_rule_can_be_withdrawn(
    hr, director, october
):
    attendance.confirm(hr, "WS", "2026-10")
    with pytest.raises(OvertimeError, match="already confirmed"):
        overtime.add_rule(hr, "WS", {"effective_from": "2026-10", "reason": "late"})
    future = overtime.add_rule(hr, "WS", {"effective_from": "2027-01", "reason": "New year"})
    with pytest.raises(OvertimeError, match="reason"):
        overtime.withdraw_rule(hr, future, "")
    overtime.withdraw_rule(hr, future, "Not agreed")
    assert not WorkRule.objects.filter(pk=future.pk).exists()
    response = as_user(director).post(
        "/api/v1/work-rules/",
        {"division": "WS", "effective_from": "2027-02", "reason": "x"},
        format="json",
    )
    assert response.status_code == 403


def test_the_director_checks_the_month_and_the_figures_are_kept(hr, director, october):
    with pytest.raises(OvertimeError, match="not confirmed"):
        overtime.check(director, "WS", "2026-10", [october.pk])
    attendance.confirm(hr, "WS", "2026-10")
    body = as_user(director).get("/api/v1/overtime/?division=WS&month=2026-10").json()
    [line] = body["rows"]
    assert (line["ot_working"], line["ot_sunday"], line["ot_holiday"]) == ("3:00", "4:00", "2:15")
    assert (line["nopay_time"], line["nopay_days"], line["can_check"]) == ("2:15", "19.0", True)
    response = as_user(director).post(
        "/api/v1/overtime/check/",
        {"division": "WS", "month": "2026-10", "employees": [october.pk]},
        format="json",
    )
    assert response.status_code == 200, response.json()
    kept = OvertimeCheck.objects.get()
    assert (kept.ot_working_minutes, kept.nopay_days, kept.checked_by) == (
        180,
        Decimal("19.0"),
        director,
    )
    with pytest.raises(OvertimeError, match="already checked"):
        overtime.check(director, "WS", "2026-10", [october.pk])
    with pytest.raises(DatabaseError), transaction.atomic():
        OvertimeCheck.objects.filter(pk=kept.pk).update(ot_working_minutes=999)
    with pytest.raises(DatabaseError), transaction.atomic():
        OvertimeCheck.objects.filter(pk=kept.pk).delete()


def test_the_person_who_confirmed_attendance_does_not_check_it(hr, october):
    both = person("both@sml.lk", "hr_payroll_officer", "director", all_divisions=True)
    attendance.confirm(both, "WS", "2026-10")
    with pytest.raises(OvertimeError, match="confirmed the attendance"):
        overtime.check(both, "WS", "2026-10", [october.pk])


def test_a_supervisor_checks_only_their_section(hr, october):
    section = Section.objects.create(
        code="SX",
        name="Test section",
        division=Division.objects.get(code="WS"),
        section_type="machining",
    )
    supervisor = person("sup@sml.lk", divisions=["WS"])
    section.supervisors.add(supervisor)
    other = employees.create(hr, values(number="E002", nic="198812345678", join_date="2024-01-15"))
    employees.update(hr, october, {"section": "SX"})
    attendance.confirm(hr, "WS", "2026-10")
    with pytest.raises(OvertimeError, match="not yours"):
        overtime.check(supervisor, "WS", "2026-10", [october.pk, other.pk])
    assert overtime.check(supervisor, "WS", "2026-10", [october.pk]) == 1


def test_reopening_attendance_voids_the_checks(hr, director, october):
    attendance.confirm(hr, "WS", "2026-10")
    overtime.check(director, "WS", "2026-10", [october.pk])
    attendance.reopen(hr, "WS", "2026-10", "Wrong sheet")
    assert OvertimeCheck.objects.get().voided is True
    attendance.confirm(hr, "WS", "2026-10")
    overtime.check(director, "WS", "2026-10", [october.pk])
    assert OvertimeCheck.objects.filter(voided=False).count() == 1


def test_every_division_starts_with_the_default_rule():
    for division in Division.objects.all():
        rule = overtime.rule_for(division.pk, OCT)
        assert (rule.normal_day_minutes, rule.rate_working_day, rule.rate_holiday) == (
            480,
            Decimal("1.50"),
            Decimal("2.00"),
        )
