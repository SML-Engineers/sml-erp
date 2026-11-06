"""Posting an approved payroll (backlog P2B-07)."""

from decimal import Decimal as D

import pytest

from apps.accounting.models import Account
from apps.accounting.sources import paths
from apps.payroll import payroll
from apps.payroll.payroll import PayrollError

from .test_attendance import upload
from .test_payroll import close_month, director, hr, kamal, present, working_days  # noqa: F401

pytestmark = pytest.mark.django_db


def test_approval_numbers_and_posts_the_payroll(hr, director, kamal):  # noqa: F811
    rows = present("E001", working_days(), **{"2026-10-01": {"time_out": "18:00"}})
    upload(hr, rows)
    close_month(hr, director, kamal)
    run = payroll.prepare(hr, "WS", "2026-10")
    payroll.submit(hr, run)
    payroll.approve(director, run, "OK")
    run.refresh_from_db()
    assert run.number.startswith("PR2610")
    entry = run.journal_entry
    assert (entry.source_type, entry.source_id, entry.entry_date.isoformat()) == (
        "payroll",
        run.number,
        "2026-10-20",
    )
    got = {
        line.account.system_role: (line.debit, line.credit, line.division_id)
        for line in entry.lines.select_related("account")
    }
    ws = run.division_id
    # Earnings 73,325; EPF 5,400 + 8,100; ETF 2,025; welfare 250; net 67,675.
    assert got == {
        "salaries_expense": (D("73325.00"), D("0.00"), ws),
        "epf_etf_expense": (D("10125.00"), D("0.00"), ws),
        "epf_payable": (D("0.00"), D("13500.00"), None),
        "etf_payable": (D("0.00"), D("2025.00"), None),
        "payroll_deductions": (D("0.00"), D("250.00"), None),
        "salaries_payable": (D("0.00"), D("67675.00"), None),
    }  # no APIT line: none due
    assert sum(x.debit for x in entry.lines.all()) == sum(x.credit for x in entry.lines.all())
    assert paths([("payroll", run.number)]) == {("payroll", run.number): f"/payroll/{run.pk}"}


def test_the_payroll_roles_are_on_the_starting_accounts():
    assert dict(
        Account.objects.exclude(system_role="")
        .filter(system_role__in=["salaries_expense", "salaries_payable", "payroll_deductions"])
        .values_list("system_role", "number")
    ) == {"salaries_expense": "6000", "salaries_payable": "2160", "payroll_deductions": "2190"}


def test_a_missing_account_is_named():
    with pytest.raises(PayrollError, match="no nothing account; ask the Accountant"):
        payroll._account("nothing")
