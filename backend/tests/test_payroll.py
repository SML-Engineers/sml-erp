"""The monthly payroll run (backlog P2B-06; owner's answers of 5 Nov 2026). Pay month October
2026 runs from 21 September to 20 October: 30 days, 26 working days (Monday to Saturday)."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.payroll import attendance, changes, employees, overtime, payroll
from apps.payroll.attendance import AttendanceError
from apps.payroll.changes import ChangeError
from apps.payroll.models import PayrollItem, PayrollLine, PayrollRun, TaxTable
from apps.payroll.payroll import PayrollError

from .test_access import as_user, person
from .test_attendance import upload
from .test_employees import values

pytestmark = pytest.mark.django_db

START, END = date(2026, 9, 21), date(2026, 10, 20)


@pytest.fixture
def hr():
    return person("hr@sml.lk", "hr_payroll_officer", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def approve_pay(hr, director, employee, lines, month="2024-01", settings=None):
    body = {"effective_from": month, "reason": "Joined", "lines": lines}
    if settings is not None:
        body["settings"] = settings
    change = changes.prepare(hr, employee, body)
    changes.submit(hr, change)
    changes.approve(director, change)


PAY = [
    {"component": "BASIC", "amount": "60000"},
    {"component": "FIXED", "amount": "6000"},
    {"component": "ATTEND", "amount": "1500"},
    {"component": "TRAVEL", "amount": "5000"},  # not for EPF
    {"component": "WELFARE", "amount": "250"},
]


@pytest.fixture
def kamal(hr, director):
    e = employees.create(hr, values(join_date="2024-01-15"))
    approve_pay(hr, director, e, PAY)
    return e


def working_days(first=START, last=END, skip=()):
    day = first
    while day <= last:
        if day.weekday() != 6 and day not in skip:
            yield day
        day += timedelta(days=1)


def present(number, days, **changed):
    """A full 8-hour day (no overtime) on each day, with some days changed."""
    return [
        {"number": number, "date": d, "time_in": "08:00", "time_out": "16:00"}
        | changed.get(d.isoformat(), {})
        for d in days
    ]


def close_month(hr, director, *people):
    attendance.confirm(hr, "WS", "2026-10")
    overtime.check(director, "WS", "2026-10", [p.pk for p in people])


def items(line):
    return {i.code: i.amount for i in line.items.all()}


def test_a_full_month(hr, director, kamal):
    rows = present("E001", working_days(), **{"2026-10-01": {"time_out": "18:00"}})
    upload(hr, rows)
    close_month(hr, director, kamal)
    run = payroll.prepare(hr, "WS", "2026-10")
    assert (run.period_start, run.period_end, run.status) == (START, END, "draft")
    line = PayrollLine.objects.get(run=run)
    got = items(line)
    # Day rate (basic + fixed) / 30 = 2,200; hourly rate / 240 = 275.
    assert (line.day_rate, line.hourly_rate) == (D("2200.00"), D("275.00"))
    assert got["OT_WORKING"] == D("825.00")  # 2 h x 275 x 1.5
    assert got["ATTEND"] == D("1500.00")
    assert line.gross == D("73325.00")
    assert line.epf_earnings == D("67500.00")  # basic + fixed + attendance bonus
    assert (line.epf_employee, line.epf_employer, line.etf) == (
        D("5400.00"),
        D("8100.00"),
        D("2025.00"),
    )
    assert line.apit_earnings == D("73325.00") and line.apit == D("0.00")  # under 150,000
    assert line.deductions == D("250.00")
    assert line.net == D("67675.00")  # 73,325 - 5,400 - 250
    basis = {i.code: i.basis for i in line.items.all()}
    assert basis["OT_WORKING"] == "2:00 h x 275.00 x 1.50"
    assert "8.00% of 67,500.00" in basis["EPF_EE"]


def test_away_four_half_days_loses_the_bonus_and_no_pay_days_are_deducted(hr, director, kamal):
    away = {date(2026, 10, 1), date(2026, 10, 2)}  # two days absent = four half days
    upload(hr, present("E001", working_days(skip=away)))
    close_month(hr, director, kamal)
    line = PayrollLine.objects.get(run=payroll.prepare(hr, "WS", "2026-10"))
    got = items(line)
    assert got["ATTEND"] == D("0.00")
    assert got["NOPAY_DAYS"] == D("4400.00")  # 2 x 2,200
    assert line.gross == D("72500.00") - D("1500.00") - D("4400.00")
    assert line.epf_earnings == D("67500.00") - D("1500.00") - D("4400.00")
    assert "Lost: away 4" in line.items.get(code="ATTEND").basis


def test_one_day_away_keeps_the_bonus(hr, director, kamal):
    upload(hr, present("E001", working_days(skip={date(2026, 10, 1)})))
    close_month(hr, director, kamal)
    line = PayrollLine.objects.get(run=payroll.prepare(hr, "WS", "2026-10"))
    assert items(line)["ATTEND"] == D("1500.00")


def test_a_joiner_is_paid_for_the_days_employed(hr, director, kamal):
    nimal = employees.create(hr, values(number="E002", nic="198812345678", join_date="2026-10-06"))
    approve_pay(hr, director, nimal, [{"component": "BASIC", "amount": "45000"}], "2026-10")
    upload(
        hr,
        present("E001", working_days()) + present("E002", working_days(first=date(2026, 10, 6))),
    )
    close_month(hr, director, kamal, nimal)
    run = payroll.prepare(hr, "WS", "2026-10")
    line = run.lines.get(employee=nimal)
    assert (line.days_employed, line.days_in_period) == (15, 30)
    assert items(line)["BASIC"] == D("22500.00")  # 45,000 x 15 / 30
    assert "x 15 days employed / 30" in line.items.get(code="BASIC").basis


@pytest.mark.parametrize(
    "earnings, tax",
    [
        ("100000", "0.00"),
        ("150000", "0.00"),
        ("200000", "3000.00"),  # 6% x 200,000 - 9,000
        ("300000", "18500.00"),  # 24% x 300,000 - 53,500
        ("500000", "86000.00"),  # 36% x 500,000 - 94,000
    ],
)
def test_apit_follows_ird_table_01(earnings, tax):
    table = TaxTable.objects.get(kind="primary")
    assert payroll.apit_for(D(earnings), table)[0] == D(tax)


def test_amounts_typed_in_for_the_month_and_the_40_percent_rule(hr, director, kamal):
    upload(hr, present("E001", working_days()))
    close_month(hr, director, kamal)
    run = payroll.prepare(hr, "WS", "2026-10")
    payroll.set_entry(hr, run, kamal.pk, "INCENTIVE", "3000", "Target met")
    line = run.lines.get()
    assert items(line)["INCENTIVE"] == D("3000.00")
    assert line.gross == D("75500.00")
    payroll.set_entry(hr, run, kamal.pk, "ADVANCE", "50000", "Advance in October")
    # Net would be 40% of the basic (24,000) or less: refused when sent.
    with pytest.raises(PayrollError, match="40% of the basic salary or less: E001"):
        payroll.submit(hr, run)
    payroll.set_entry(hr, run, kamal.pk, "ADVANCE", "20000")
    payroll.submit(hr, run)


def test_nothing_is_paid_before_attendance_and_overtime_are_done(hr, director, kamal):
    upload(hr, present("E001", working_days()))
    with pytest.raises(PayrollError, match="not confirmed attendance"):
        payroll.prepare(hr, "WS", "2026-10")
    attendance.confirm(hr, "WS", "2026-10")
    with pytest.raises(PayrollError, match="not checked yet: E001"):
        payroll.prepare(hr, "WS", "2026-10")
    overtime.check(director, "WS", "2026-10", [kamal.pk])
    payroll.prepare(hr, "WS", "2026-10")
    with pytest.raises(PayrollError, match="already has a payroll"):
        payroll.prepare(hr, "WS", "2026-10")


def test_the_director_approves_and_the_payroll_is_locked(hr, director, kamal):
    upload(hr, present("E001", working_days()))
    close_month(hr, director, kamal)
    run = payroll.prepare(hr, "WS", "2026-10")
    with pytest.raises(PayrollError, match="Only HR"):
        payroll.prepare(director, "WS", "2026-10")
    payroll.submit(hr, run)
    with pytest.raises(PayrollError, match="waiting for the director"):
        payroll.set_entry(hr, run, kamal.pk, "INCENTIVE", "1")
    with pytest.raises(PayrollError, match="Director"):
        payroll.approve(hr, run)  # never the person who prepared it (rule 5)
    with pytest.raises(AttendanceError, match="sent or approved"):
        attendance.reopen(hr, "WS", "2026-10", "Mistake")
    payroll.approve(director, run, "OK")
    run.refresh_from_db()
    assert run.status == "approved" and run.approved_at is not None
    line = run.lines.get()
    with pytest.raises(DatabaseError), transaction.atomic():
        PayrollLine.objects.filter(pk=line.pk).update(net=D("1"))
    with pytest.raises(DatabaseError), transaction.atomic():
        PayrollItem.objects.filter(line=line).update(amount=D("1"))
    with pytest.raises(DatabaseError), transaction.atomic():
        PayrollRun.objects.filter(pk=run.pk).update(status="draft")
    with pytest.raises(DatabaseError), transaction.atomic():
        PayrollRun.objects.filter(pk=run.pk).delete()
    # A pay change cannot start in a month already paid.
    late = changes.prepare(
        hr,
        kamal,
        {
            "effective_from": "2026-10",
            "reason": "Back pay",
            "lines": [{"component": "BASIC", "amount": "65000"}],
        },
    )
    with pytest.raises(ChangeError, match="already paid"):
        changes.submit(hr, late)


def test_a_returned_payroll_is_corrected_and_a_rejected_one_prepared_again(hr, director, kamal):
    upload(hr, present("E001", working_days()))
    close_month(hr, director, kamal)
    run = payroll.prepare(hr, "WS", "2026-10")
    payroll.submit(hr, run)
    payroll.send_back(director, run, "Add the incentive")
    run.refresh_from_db()
    assert run.status == "draft"
    payroll.set_entry(hr, run, kamal.pk, "INCENTIVE", "2000")
    payroll.submit(hr, run)
    payroll.reject(director, run, "Wrong month")
    again = payroll.prepare(hr, "WS", "2026-10")
    assert again.pk != run.pk and again.status == "draft"


def test_secondary_employment_needs_the_accountants_table(hr, director):
    e = employees.create(hr, values(join_date="2024-01-15"))
    approve_pay(hr, director, e, PAY[:1], settings={"apit": "secondary"})
    upload(hr, present("E001", working_days()))
    close_month(hr, director, e)
    with pytest.raises(PayrollError, match="no APIT table for secondary employment"):
        payroll.prepare(hr, "WS", "2026-10")


def test_the_api(hr, director, kamal):
    upload(hr, present("E001", working_days()))
    close_month(hr, director, kamal)
    made = as_user(hr).post("/api/v1/payroll/", {"division": "WS", "month": "2026-10"})
    assert made.status_code == 201, made.json()
    body = made.json()
    assert body["period"] == {"month": "2026-10", "start": "2026-09-21", "end": "2026-10-20"}
    assert body["totals"]["net"] == "66850.00" and body["can_submit"] is True
    assert body["lines"][0]["items"][0]["code"] == "BASIC"
    pk = body["id"]
    entry = {"employee": kamal.pk, "component": "INCENTIVE", "amount": "1000"}
    assert as_user(hr).post(f"/api/v1/payroll/{pk}/entries/", entry).status_code == 200
    assert as_user(hr).post(f"/api/v1/payroll/{pk}/submit/").status_code == 200
    seen = as_user(director).get(f"/api/v1/payroll/{pk}/").json()
    assert seen["can_approve"] is True and seen["status"] == "awaiting"
    done = as_user(director).post(f"/api/v1/payroll/{pk}/approve/", {"reason": "OK"})
    assert done.status_code == 200 and done.json()["status"] == "approved"
    accountant = person("acc@sml.lk", "accountant", all_divisions=True)
    totals_only = as_user(accountant).get(f"/api/v1/payroll/{pk}/").json()
    assert totals_only["lines"] == [] and totals_only["totals"]["employees"] == 1
    listed = as_user(hr).get("/api/v1/payroll/").json()
    assert listed["results"][0]["status"] == "approved"


def test_the_accountant_keeps_the_apit_tables(hr):
    accountant = person("acc@sml.lk", "accountant", all_divisions=True)
    table = {
        "kind": "secondary",
        "effective_from": "2026-04-01",
        "reason": "IRD APIT Table 07, 2025/26 onwards",
        "bands": [
            {"up_to": "100000", "rate": "6", "constant": "0"},
            {"up_to": "", "rate": "36", "constant": "30000"},
        ],
    }
    made = as_user(accountant).post("/api/v1/payroll-tax-tables/", table, format="json")
    assert made.status_code == 201, made.json()
    assert made.json()["bands"][1]["up_to"] is None
    bad = table | {"effective_from": "2026-05-01", "bands": [{"up_to": "5", "rate": "6"}]}
    response = as_user(accountant).post("/api/v1/payroll-tax-tables/", bad, format="json")
    assert "no upper limit" in response.json()["detail"]
    assert as_user(hr).post("/api/v1/payroll-tax-tables/", table, format="json").status_code == 403
    listed = as_user(accountant).get("/api/v1/payroll-tax-tables/").json()
    assert {t["kind"] for t in listed["tables"]} == {"primary", "secondary"}
    assert listed["statutory"][0]["epf_employee"] == "8.00"
    with pytest.raises(DatabaseError), transaction.atomic():
        TaxTable.objects.filter(kind="primary").update(reason="changed")
