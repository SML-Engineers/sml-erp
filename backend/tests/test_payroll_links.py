"""Payroll in the rest of the system (backlog P2B-13): the cash flow planner, the month-end
checklist, the report builder and the labour cost per hour. The approved payroll of pay month
October 2026 (21 Sep to 20 Oct, posted on 20 October) is paid on 31 October; its EPF and ETF
by 30 November and its APIT by 15 November."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.accounting import close, planner
from apps.accounting import report_builder as rb
from apps.payroll import cashflow, labour

from .test_access import as_user, person
from .test_payroll import close_month, director, hr, kamal, present, working_days  # noqa: F401
from .test_payslips import approved  # noqa: F401

pytestmark = pytest.mark.django_db
TODAY = date(2026, 11, 6)
END = date(2027, 2, 4)  # 13 weeks


def test_due_dates():
    october = date(2026, 10, 1)
    assert cashflow.due(october, "net") == date(2026, 10, 31)
    assert cashflow.due(october, "apit") == date(2026, 11, 15)
    assert cashflow.due(october, "epf") == cashflow.due(october, "etf") == date(2026, 11, 30)
    assert cashflow.due(date(2026, 12, 1), "epf") == date(2027, 1, 31)


def test_the_planner_pays_what_is_owed_and_estimates_the_coming_months(approved):  # noqa: F811
    figures = cashflow.amounts(approved)
    assert figures["net"] > 0 and figures["epf"] > 0 and figures["etf"] > 0
    paid = cashflow.payments(TODAY, END)
    owed = {p.label.split(":")[0]: p for p in paid if "estimate" not in p.label}
    # The October net pay was due on 31 October: overdue, so today.
    assert owed["Net pay"].day == TODAY and owed["Net pay"].amount == figures["net"]
    assert owed["Net pay"].kind == "payroll"
    assert owed["EPF 8% + 12%"].day == date(2026, 11, 30)
    assert (
        owed["EPF 8% + 12%"].amount == figures["epf"] and owed["EPF 8% + 12%"].kind == "statutory"
    )
    assert owed["ETF 3%"].day == date(2026, 11, 30)
    assert "APIT" not in owed or owed["APIT"].day == date(2026, 11, 15)
    estimates = [p for p in paid if "estimate" in p.label and p.kind == "payroll"]
    assert [p.day for p in estimates] == [date(2026, 11, 30), date(2026, 12, 31), date(2027, 1, 31)]
    assert all(p.amount == figures["net"] for p in estimates)
    assert "WS November 2026 (estimate, as October 2026)" in estimates[0].label
    # Statutory payments falling after the 13 weeks are left out.
    assert max(p.day for p in paid) <= END


def test_the_planner_shows_payroll_without_naming_anyone(director, approved):  # noqa: F811
    result = planner.projection(director, TODAY)
    mine = [f for f in result["flows"] if f.kind in ("payroll", "statutory")]
    assert mine and all(f.amount < 0 for f in mine)
    assert not any("Kamal" in f.label or "E001" in f.label for f in mine)


def test_the_month_end_checklist_waits_for_the_payroll(approved):  # noqa: F811
    october = {i.key: i for i in close.checklist(date(2026, 10, 1))}["payroll"]
    assert october.done and october.detail == "Approved: WS."
    november = {i.key: i for i in close.checklist(date(2026, 11, 1))}["payroll"]
    assert not november.done and "Not approved yet: WS" in november.detail


def test_payroll_is_a_report_builder_source_for_hr_and_the_director_only(
    hr,  # noqa: F811
    director,  # noqa: F811
    approved,  # noqa: F811
):
    definition = {"source": "payroll_lines", "columns": ["number", "employee", "gross", "net"]}
    result = rb.run(hr, rb.parse(hr, definition))
    numbers = sorted(r["cells"]["number"] for r in result["rows"] if r["kind"] == "line")
    assert numbers == ["E001", "E002"]
    assert "payroll_lines" in [s.key for s in rb.sources_for(director)]
    pivot = rb.run(
        director,
        rb.parse(
            director,
            {
                "source": "payroll_lines",
                "columns": ["division", "gross"],
                "group_by": "division",
                "period": "division",
                "measure": "gross",
            },
        ),
    )
    assert [c["key"] for c in pivot["columns"]] == ["division", "WS", "total"]
    accountant = person("acc@sml.lk", "accountant", all_divisions=True)
    assert "payroll_lines" not in [s.key for s in rb.sources_for(accountant)]
    with pytest.raises(rb.ReportError, match="do not have access"):
        rb.parse(accountant, definition)


def test_labour_cost_per_hour(hr, approved):  # noqa: F811
    c = labour.cost(approved)
    lines = list(approved.lines.all())
    paid = sum((x.gross + x.epf_employer + x.etf for x in lines), D("0"))
    # 26 working days of 8 hours each, for two employees.
    assert c["hours"] == D("416.00") and c["cost"] == paid
    assert c["per_hour"] == (paid / 416).quantize(D("0.01"))
    assert labour.rate(approved.division, approved.month) == c["per_hour"]
    assert labour.rate(approved.division, date(2026, 11, 1)) is None
    body = as_user(hr).get(f"/api/v1/payroll/{approved.pk}/").json()
    assert body["labour"]["per_hour"] == f"{c['per_hour']:.2f}"
    assert body["labour"]["sections"][0]["hours"] == "416.00"
