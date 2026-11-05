"""Employees' pay settings approved by the Director (backlog P2B-17; owner, 5 Nov 2026): HR
prepares, the Director approves, and only then do amounts and settings take effect."""

from datetime import date, time
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.masters.models import Shift
from apps.payroll import changes, employees, leave, overtime, pay, periods
from apps.payroll.changes import ChangeError
from apps.payroll.models import (
    EmployeeSetting,
    LeaveType,
    PayChange,
    PayChangeLine,
    PayComponent,
    PayRate,
)

from .test_access import as_user, person
from .test_attendance import row, upload
from .test_employees import values

pytestmark = pytest.mark.django_db


@pytest.fixture
def hr():
    return person("hr@sml.lk", "hr_payroll_officer", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def kamal(hr):
    return employees.create(hr, values(join_date="2024-01-15"))


def c(code):
    return PayComponent.objects.get(code=code)


def joining(**extra):
    return {
        "effective_from": "2024-01",
        "reason": "Joined",
        "lines": [
            {"component": "BASIC", "amount": "60000"},
            {"component": "ATTEND", "amount": "1500"},
            {"component": "TRAVEL", "amount": ""},  # blank: unchanged
        ],
    } | extra


def approved(hr, director, kamal, **extra):
    change = changes.prepare(hr, kamal, joining(**extra))
    changes.submit(hr, change)
    return changes.approve(director, change, "Agreed")


def amounts(employee, day=date(2026, 1, 1)):
    return {x.component.code: x.amount for x in pay.amounts_on(employee, day)}


def test_nothing_takes_effect_until_the_director_approves(hr, director, kamal):
    change = changes.prepare(hr, kamal, joining())
    assert change.is_new_employee and change.status == "draft"
    assert [x.component.code for x in change.lines.all()] == ["BASIC", "ATTEND"]
    assert amounts(kamal) == {}
    changes.submit(hr, change)
    assert amounts(kamal) == {}
    with pytest.raises(ChangeError, match="Director"):
        changes.approve(hr, change)  # the preparer never approves (rule 5)
    changes.approve(director, change, "Agreed")
    change.refresh_from_db()
    assert change.status == "approved" and change.approved_at is not None
    assert amounts(kamal) == {"BASIC": D("60000.00"), "ATTEND": D("1500.00")}
    assert PayRate.objects.filter(change=change).count() == 2
    later = changes.prepare(
        hr,
        kamal,
        {
            "effective_from": "2025-04",
            "reason": "Increment",
            "lines": [{"component": "BASIC", "amount": "66000"}],
        },
    )
    assert later.is_new_employee is False


def test_returned_rejected_and_withdrawn_changes_change_nothing(hr, director, kamal):
    change = changes.prepare(hr, kamal, joining())
    with pytest.raises(ChangeError, match="already has a pay change waiting"):
        changes.prepare(hr, kamal, joining())
    changes.submit(hr, change)
    with pytest.raises(ChangeError, match="waiting for the director"):
        changes.edit(hr, change, joining())
    changes.send_back(director, change, "Basic is 58,000")
    change.refresh_from_db()
    assert change.status == "draft"
    changes.edit(hr, change, joining(lines=[{"component": "BASIC", "amount": "58000"}]))
    changes.submit(hr, change)
    changes.reject(director, change, "Not agreed")
    assert amounts(kamal) == {}
    with pytest.raises(ChangeError, match="rejected"):
        changes.submit(hr, change)
    other = changes.prepare(hr, kamal, joining())
    with pytest.raises(ChangeError, match="reason"):
        changes.withdraw(hr, other, "")
    changes.withdraw(hr, other, "Entered twice")
    assert PayChange.objects.get(pk=other.pk).status == "withdrawn"
    assert amounts(kamal) == {}


def test_at_most_four_allowances(hr, director, kamal):
    for code in ("MEAL", "PHONE"):
        pay.save_component(
            hr, {"code": code, "name": code.title(), "kind": "earning", "is_allowance": True}
        )
    codes = ("FIXED", "TRAVEL", "INCENTIVE", "MEAL", "PHONE")
    five = [{"component": x, "amount": "1000"} for x in codes]
    change = changes.prepare(hr, kamal, joining(lines=five))
    with pytest.raises(ChangeError, match="at most 4 allowances"):
        changes.submit(hr, change)
    changes.edit(hr, change, joining(lines=five[:4]))
    changes.submit(hr, change)
    changes.approve(director, change)
    # Ending one makes room for another.
    swap = changes.prepare(
        hr,
        kamal,
        {
            "effective_from": "2025-01",
            "reason": "Phone instead of meal",
            "lines": [
                {"component": "MEAL", "amount": "0"},
                {"component": "PHONE", "amount": "800"},
            ],
        },
    )
    changes.submit(hr, swap)


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"reason": ""}, "reason"),
        ({"effective_from": "2023-12"}, "before the employee joined"),
        ({"effective_from": "2024-01-15"}, "1st of a month"),
        ({"lines": [], "settings": None}, "no amounts and no settings"),
        ({"lines": [{"component": "NOPE", "amount": "1"}]}, "no pay component NOPE"),
        ({"lines": [{"component": "BASIC", "amount": "-1"}]}, "0 or more"),
        (
            {"lines": [{"component": "WELFARE", "amount": "250", "epf_liable": True}]},
            "a deduction",
        ),
        ({"settings": {"grace_minutes": "500"}}, "grace is from 0 to 120"),
        ({"settings": {"rate_sunday": "0.5"}}, "Sunday is from 1 to 5"),
        ({"settings": {"annual_leave_days": "7.3"}}, "whole or half days"),
        ({"settings": {"apit": "none"}}, "APIT table"),
    ],
)
def test_wrong_changes_are_refused(hr, kamal, extra, message):
    with pytest.raises(ChangeError, match=message):
        changes.prepare(hr, kamal, joining(**extra))


def test_only_hr_prepares(director, kamal):
    with pytest.raises(ChangeError, match="Only HR"):
        changes.prepare(director, kamal, joining())
    im_hr = person("hr-im@sml.lk", "hr_payroll_officer", divisions=["IM"])
    with pytest.raises(ChangeError, match="divisions"):
        changes.prepare(im_hr, kamal, joining())


def test_the_employees_own_epf_and_apit_marks(hr, director, kamal):
    lines = [
        {"component": "BASIC", "amount": "60000"},
        {"component": "TRAVEL", "amount": "5000", "epf_liable": True, "apit_taxable": "false"},
    ]
    approved(hr, director, kamal, lines=lines)
    totals = pay.totals(pay.amounts_on(kamal, date(2026, 1, 1)))
    assert (totals["epf_earnings"], totals["apit_earnings"]) == (D("65000.00"), D("60000.00"))


def test_the_employees_own_settings_replace_the_defaults(hr, director, kamal):
    settings = {
        "normal_day_minutes": "420",
        "grace_minutes": "40",
        "rate_working_day": "1.75",
        "annual_leave_days": "20",
        "casual_leave_days": "",
        "apit": "secondary",
    }
    approved(hr, director, kamal, settings=settings)
    own = EmployeeSetting.objects.get(employee=kamal)
    assert (own.normal_day_minutes, own.grace_minutes, own.casual_leave_days, own.apit) == (
        420,
        40,
        None,
        "secondary",
    )
    annual, casual = LeaveType.objects.get(code="ANNUAL"), LeaveType.objects.get(code="CASUAL")
    assert leave.entitlement(kamal, annual, 2026) == D(20)
    assert leave.entitlement(kamal, casual, 2026) == D(7)
    Shift.objects.create(
        code="DX", name="Day test", start_time=time(8), end_time=time(17), break_minutes=60
    )
    upload(hr, [row(1, shift="DX", time_in="08:30")])  # 30 minutes late: within his grace
    month = overtime.work_out(kamal, date(2026, 10, 1), 0)
    assert (month.short_minutes, month.short_leaves) == (0, 0)
    assert month.rate("rate_working_day") == D("1.75")
    assert month.rate("rate_sunday") == D("2.00")  # the division's rule


def test_a_change_for_a_month_to_come_replaces_one_approved_for_the_same_month(hr, director, kamal):
    approved(hr, director, kamal)
    coming = periods.next_month(periods.pay_month_of(timezone.localdate())).isoformat()[:7]
    for amount in ("70000", "72000"):
        approved(
            hr,
            director,
            kamal,
            effective_from=coming,
            reason="Promotion",
            lines=[{"component": "BASIC", "amount": amount}],
        )
    rates = PayRate.objects.filter(employee=kamal, component=c("BASIC"))
    assert sorted(r.amount for r in rates) == [D("60000.00"), D("72000.00")]
    # A month in force is never replaced.
    change = changes.prepare(
        hr, kamal, joining(reason="Mistake", lines=[{"component": "BASIC", "amount": "1"}])
    )
    with pytest.raises(ChangeError, match="in force"):
        changes.submit(hr, change)


def test_the_database_keeps_decided_changes_and_settings(hr, director, kamal):
    change = approved(hr, director, kamal, settings={"grace_minutes": "20"})
    with pytest.raises(DatabaseError), transaction.atomic():
        PayChange.objects.filter(pk=change.pk).update(reason="changed")
    with pytest.raises(DatabaseError), transaction.atomic():
        PayChange.objects.filter(pk=change.pk).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        PayChangeLine.objects.create(change=change, component=c("TRAVEL"), amount=D("1"))
    with pytest.raises(DatabaseError), transaction.atomic():
        EmployeeSetting.objects.filter(employee=kamal).update(grace_minutes=0)
    with pytest.raises(DatabaseError), transaction.atomic():
        EmployeeSetting.objects.filter(employee=kamal).delete()


def test_the_api_flow(hr, director, kamal):
    url = f"/api/v1/employees/{kamal.pk}/pay-changes/"
    response = as_user(hr).post(url, joining(settings={"grace_minutes": "15"}), format="json")
    assert response.status_code == 201, response.json()
    body = response.json()
    [change] = body["changes"]
    assert (change["status"], change["is_new_employee"], change["can_submit"]) == (
        "draft",
        True,
        True,
    )
    assert change["settings"]["grace_minutes"] == "15"
    assert body["defaults"]["annual_leave_days"] == "14.0"
    assert body["can_prepare"] is False  # one open change at a time
    pk = change["id"]
    put = as_user(hr).put(
        f"/api/v1/pay-changes/{pk}/", joining(reason="Joined 15 Jan"), format="json"
    )
    assert put.status_code == 200, put.json()
    assert as_user(hr).post(f"/api/v1/pay-changes/{pk}/submit/").status_code == 200
    waiting = as_user(director).get(f"/api/v1/employees/{kamal.pk}/pay/").json()["changes"][0]
    assert (waiting["status"], waiting["can_approve"]) == ("awaiting", True)
    assert as_user(hr).post(f"/api/v1/pay-changes/{pk}/approve/").status_code == 400
    done = as_user(director).post(f"/api/v1/pay-changes/{pk}/approve/", {"reason": "OK"})
    assert done.status_code == 200, done.json()
    body = done.json()
    assert body["changes"][0]["status"] == "approved"
    assert [h["action"] for h in body["changes"][0]["history"]] == ["Submitted", "Approved"]
    assert {x["component"] for x in body["current"]} == {"BASIC", "ATTEND"}
    assert as_user(hr).post(f"/api/v1/pay-changes/{pk}/nonsense/").status_code == 400
    accountant = person("acc@sml.lk", "accountant", all_divisions=True)
    assert as_user(accountant).post(url, joining(), format="json").status_code == 403
