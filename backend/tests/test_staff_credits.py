"""Salary advances and staff loans (backlog P2B-10; owner's answers of 5 Nov 2026). The
employee's pay: earnings 72,500, EPF 8% 5,400, welfare 250, basic 60,000 (40% = 24,000)."""

from datetime import date
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.payroll import credits, payroll, periods
from apps.payroll.credits import CreditError
from apps.payroll.models import Employee, PayrollItem, StaffCredit

from .test_access import as_user, person
from .test_attendance import upload
from .test_payroll import close_month, director, hr, kamal, present, working_days  # noqa: F401

pytestmark = pytest.mark.django_db
OCT = date(2026, 10, 1)


def this_month():
    return periods.pay_month_of(timezone.localdate()).isoformat()[:7]


def loan(**extra):
    return {
        "kind": "loan",
        "amount": "240000",
        "interest": "0",
        "months": "24",
        "first_month": this_month(),
        "reason": "Housing",
    } | extra


def given(employee, hr, **extra):  # noqa: F811
    """An approved advance or loan, as if recorded earlier (recovery from October)."""
    values = {
        "kind": "loan",
        "amount": D("240000"),
        "months": 24,
        "first_month": OCT,
        "reason": "Housing",
        "status": "approved",
        "number": "SL261001",
    } | extra
    return StaffCredit.objects.create(employee=employee, created_by=hr, **values)


def test_a_loan_is_recorded_approved_and_numbered(hr, director, kamal):  # noqa: F811
    c = credits.record(hr, kamal, loan())
    assert (c.instalment, c.status) == (D("10000.00"), "draft")  # 240,000 over 24 months
    credits.submit(hr, c)
    with pytest.raises(CreditError, match="Director"):
        credits.approve(hr, c)  # never the person who recorded it (rule 5)
    credits.approve(director, c, "OK")
    c.refresh_from_db()
    assert c.status == "approved" and c.number.startswith("SL")
    with pytest.raises(DatabaseError), transaction.atomic():
        StaffCredit.objects.filter(pk=c.pk).update(amount=D("1"))
    with pytest.raises(DatabaseError), transaction.atomic():
        StaffCredit.objects.filter(pk=c.pk).delete()


def test_the_employee_keeps_more_than_40_percent_of_the_basic(hr, kamal):  # noqa: F811
    big = credits.record(
        hr,
        kamal,
        {"kind": "advance", "amount": "50000", "first_month": this_month(), "reason": "Wedding"},
    )
    # 72,500 - 5,400 - 250 - 50,000 = 16,850: not more than 24,000.
    with pytest.raises(CreditError, match="not more than 40% of the basic salary"):
        credits.submit(hr, big)
    credits.edit(
        hr,
        big,
        {"kind": "advance", "amount": "20000", "first_month": this_month(), "reason": "Wedding"},
    )
    credits.submit(hr, big)


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"kind": "gift"}, "advance or a loan"),
        ({"amount": "0"}, "more than 0"),
        ({"amount": "10.005"}, "two decimal places"),
        ({"interest": "-1"}, "0 or more"),
        ({"months": "0"}, "1 to 120 months"),
        ({"months": "x"}, "number of months"),
        ({"first_month": "2020-01"}, "or later"),
        ({"reason": " "}, "reason"),
    ],
)
def test_wrong_entries_are_refused(hr, kamal, extra, message):  # noqa: F811
    with pytest.raises(CreditError, match=message):
        credits.record(hr, kamal, loan(**extra))


def test_returned_rejected_and_withdrawn(hr, director, kamal):  # noqa: F811
    c = credits.record(hr, kamal, loan())
    credits.submit(hr, c)
    credits.send_back(director, c, "36 months")
    c.refresh_from_db()
    assert c.status == "draft"
    credits.edit(hr, c, loan(months="36"))
    credits.submit(hr, c)
    credits.reject(director, c, "Not now")
    assert StaffCredit.objects.get(pk=c.pk).status == "rejected"
    other = credits.record(hr, kamal, loan())
    with pytest.raises(CreditError, match="reason"):
        credits.withdraw(hr, other, "")
    credits.withdraw(hr, other, "Entered twice")
    assert StaffCredit.objects.get(pk=other.pk).status == "withdrawn"


def run_october(hr, director, kamal):  # noqa: F811
    upload(hr, present("E001", working_days()))
    close_month(hr, director, kamal)
    return payroll.prepare(hr, "WS", "2026-10")


def test_the_payroll_recovers_instalments_and_advances(hr, director, kamal):  # noqa: F811
    housing = given(kamal, hr)
    advance = given(kamal, hr, kind="advance", amount=D("10000"), months=1, number="SL261002")
    run = run_october(hr, director, kamal)
    line = run.lines.get()
    got = {i.code: (i.amount, i.credit_id) for i in line.items.filter(credit__isnull=False)}
    assert got == {"LOAN": (D("10000.00"), housing.pk), "ADVANCE": (D("10000.00"), advance.pk)}
    assert line.net == D("46850.00")  # 66,850 - 20,000
    assert "balance after 230,000.00" in line.items.get(code="LOAN").basis
    payroll.submit(hr, run)
    payroll.approve(director, run)
    assert (credits.balance(housing), credits.balance(advance)) == (D("230000.00"), D("0.00"))
    lines = {x.account.system_role: x.credit for x in run_entry(run).lines.all()}
    assert lines["staff_loans"] == D("20000.00")
    assert lines["payroll_deductions"] == D("250.00")


def run_entry(run):
    run.refresh_from_db()
    return run.journal_entry


def test_interest_is_income_as_it_is_recovered(hr, director, kamal):  # noqa: F811
    given(kamal, hr, amount=D("12000"), interest=D("1200"), months=12)  # 1,100 a month
    run = run_october(hr, director, kamal)
    payroll.submit(hr, run)
    payroll.approve(director, run)
    lines = {x.account.system_role: x.credit for x in run_entry(run).lines.all()}
    assert (lines["staff_loans"], lines["staff_loan_interest"]) == (D("1000.00"), D("100.00"))


def test_a_recovery_never_takes_the_net_to_40_percent(hr, director, kamal):  # noqa: F811
    advance = given(kamal, hr, kind="advance", amount=D("50000"), months=1)
    line = run_october(hr, director, kamal).lines.get()
    item = line.items.get(credit=advance)
    assert item.amount == D("42849.99")  # 66,850 - 24,000.01
    assert line.net == D("24000.01")
    assert "reduced from 50,000.00" in item.basis


def test_a_leaver_repays_the_balance_as_far_as_it_goes(hr, director, kamal):  # noqa: F811
    housing = given(kamal, hr, amount=D("20000"))
    Employee.objects.filter(pk=kamal.pk).update(leaving_date=date(2026, 10, 20))
    line = run_october(hr, director, kamal).lines.get()
    item = line.items.get(credit=housing)
    assert item.amount == D("20000.00") and "whole balance (leaving)" in item.basis


def test_the_api(hr, director, kamal):  # noqa: F811
    listed = as_user(hr).get("/api/v1/staff-credits/").json()
    assert listed["can_record"] is True and listed["employees"][0]["number"] == "E001"
    made = as_user(hr).post("/api/v1/staff-credits/", loan(employee=kamal.pk), format="json")
    assert made.status_code == 201, made.json()
    pk = made.json()["id"]
    assert made.json()["instalment"] == "10000.00"
    assert as_user(hr).post(f"/api/v1/staff-credits/{pk}/submit/").status_code == 200
    seen = as_user(director).get("/api/v1/staff-credits/").json()["results"][0]
    assert seen["can_approve"] is True
    done = as_user(director).post(f"/api/v1/staff-credits/{pk}/approve/")
    assert done.status_code == 200 and done.json()["balance"] == "240000.00"
    accountant = person("acc@sml.lk", "accountant", all_divisions=True)
    assert as_user(accountant).get("/api/v1/staff-credits/").status_code == 403
    assert PayrollItem.objects.count() == 0
