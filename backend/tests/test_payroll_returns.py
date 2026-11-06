"""Statutory returns from the approved payrolls (backlog P2B-09). Two employees in pay month
October 2026: E001 with EPF earnings 67,500 (APIT earnings 72,500), E002 with basic 60,000."""

from decimal import Decimal as D

import pytest

from apps.core.models import Company
from apps.payroll import payroll, returns
from apps.payroll.returns import ReturnError

from .test_access import as_user, person
from .test_attendance import upload
from .test_payroll import close_month, director, hr, kamal, present, working_days  # noqa: F401
from .test_payslips import approved  # noqa: F401

pytestmark = pytest.mark.django_db
URL = "/api/v1/payroll-returns/"


def test_the_epf_c_form(hr, approved):  # noqa: F811
    Company.objects.filter(pk=1).update(epf_employer_no="A/12345")
    r = returns.epf(hr, "2026-10")
    assert r.title == "EPF monthly return (C form) – October 2026"
    assert "EPF employer no.: A/12345" in r.lines
    assert "Pay period 21 September – 20 October 2026" in r.lines
    assert [row[0] for row in r.rows] == ["E001", "E002"]
    assert r.rows[0][4:] == [D("67500.00"), D("5400.00"), D("8100.00"), D("13500.00")]
    assert r.rows[1][4:] == [D("60000.00"), D("4800.00"), D("7200.00"), D("12000.00")]
    assert r.totals[4:] == [D("127500.00"), D("10200.00"), D("15300.00"), D("25500.00")]
    assert r.totals[1] == "2 members"


def test_etf_monthly_and_half_year(hr, approved):  # noqa: F811
    month = returns.etf(hr, "2026-10")
    assert month.totals[4:] == [D("127500.00"), D("3825.00")]
    half = returns.etf_half_year(hr, 2026, 2)
    assert half.columns[4:] == ["Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Total"]
    assert half.rows[0][4:] == [D(0), D(0), D(0), D("2025.00"), D(0), D(0), D("2025.00")]
    assert half.totals[-1] == D("3825.00")
    with pytest.raises(ReturnError, match="half"):
        returns.etf_half_year(hr, 2026, 3)


def test_apit_monthly_schedule_year_and_certificates(hr, approved):  # noqa: F811
    month = returns.apit(hr, "2026-10")
    assert month.totals[4:] == [D("132500.00"), D("0.00")]
    assert month.rows[0][3].startswith("Table 01: primary employment")
    year = returns.apit_year(hr, 2026)
    assert year.title == "APIT for the year of assessment 2026/27"
    assert [row[3] for row in year.rows] == [1, 1]
    assert returns.certificates(hr, 2026).startswith(b"%PDF")
    assert returns.certificates(hr, 2026, "e001").startswith(b"%PDF")
    with pytest.raises(ReturnError, match="nobody"):
        returns.certificates(hr, 2025)


def test_a_payroll_not_yet_approved_is_named(hr, director, kamal):  # noqa: F811
    upload(hr, present("E001", working_days()))
    close_month(hr, director, kamal)
    payroll.prepare(hr, "WS", "2026-10")
    r = returns.epf(hr, "2026-10")
    assert r.rows == []
    assert "the payroll of WS is not approved yet" in r.notes[0]


def test_downloads_and_who_sees_them(hr, director, approved):  # noqa: F811
    body = as_user(hr).get(URL + "epf/?month=2026-10").json()
    assert body["totals"][-1] == "25500.00" and body["money_from"] == 4
    xlsx = as_user(director).get(URL + "epf/?month=2026-10&format=xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    assert 'filename="epf-2026-10.xlsx"' in xlsx["Content-Disposition"]
    pdf = as_user(hr).get(URL + "etf-half/?year=2026&half=2&format=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    year = as_user(hr).get(URL + "apit-year/?year=2026")
    assert year.status_code == 200 and year.json()["title"].endswith("2026/27")
    certificates = as_user(hr).get(URL + "apit-certificates/?year=2026")
    assert certificates["Content-Type"] == "application/pdf"
    assert as_user(hr).get(URL + "nonsense/").status_code == 400
    bad = as_user(hr).get(URL + "epf/?month=October")
    assert bad.status_code == 400 and "pay month" in bad.json()["detail"]
    accountant = person("acc@sml.lk", "accountant", all_divisions=True)
    refused = as_user(accountant).get(URL + "epf/?month=2026-10")
    assert refused.status_code == 400 and "Only HR and the Director" in refused.json()["detail"]
