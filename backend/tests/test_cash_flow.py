# ruff: noqa: F811 - the fixtures of test_journal are imported and used by name
"""Cash flow statement (indirect method) and the financial tiles of the home page (backlog
P2-24)."""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting import cash_flow, journal
from apps.accounting.journal import Line
from apps.accounting.models import Account
from apps.assets.models import AssetClass

from .test_access import as_user, person
from .test_journal import LAST_MONTH, acc, accountant, cost, div, sale  # noqa: F401

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
THIS_MONTH = TODAY.replace(day=1)
D = Decimal


def of_type(account_type, *, exclude=()):
    return (
        Account.objects.filter(account_type=account_type, system_role="", is_active=True)
        .exclude(pk__in=exclude)
        .order_by("number")
        .first()
    )


def post(user, on, debit, credit, amount, division=None):
    return journal.post(
        user,
        entry_date=on,
        narration="Test",
        lines=[
            Line(account=debit, debit=amount, division=division),
            Line(account=credit, credit=amount, division=division),
        ],
    )


@pytest.fixture
def month(accountant):
    """Cash 100,000 brought in last month; this month a cash sale of 1,000, repairs of 400,
    depreciation of 300, a prepayment of 2,000, a machine of 50,000 and a loan of 30,000."""
    cash = acc("1010")
    assert cash.account_type == "bank"
    equity = Account.objects.get(system_role="opening_balance_equity")
    post(accountant, LAST_MONTH, cash, equity, "100000.00")
    sale(accountant, "1000.00", "WS")
    cost(accountant, "400.00", "WS")
    machines = AssetClass.objects.exclude(code="LAND").first()
    post(
        accountant,
        TODAY,
        machines.expense_account,
        machines.accumulated_account,
        "300.00",
        div("WS"),
    )
    accumulated = set(AssetClass.objects.values_list("accumulated_account_id", flat=True))
    post(accountant, TODAY, of_type("other_current_asset"), cash, "2000.00")
    post(accountant, TODAY, of_type("fixed_asset", exclude=accumulated), cash, "50000.00")
    post(accountant, TODAY, cash, of_type("long_term_liability"), "30000.00")


def test_the_statement_explains_the_change_in_cash(month):
    st = cash_flow.statement(THIS_MONTH, TODAY)
    assert st.profit == D("300.00")
    labels = [(r.label, r.amount) for r in st.operating.rows]
    assert labels[0] == ("Profit for the period", D("300.00"))
    assert labels[1] == ("Depreciation added back", D("300.00"))
    assert [r.amount for r in st.operating.rows[2:]] == [D("-2000.00")]
    assert (st.operating.total, st.investing.total, st.financing.total) == (
        D("-1400.00"),
        D("-50000.00"),
        D("30000.00"),
    )
    assert (st.opening_cash, st.closing_cash, st.net_change) == (
        D("100000.00"),
        D("78600.00"),
        D("-21400.00"),
    )
    assert st.difference == 0


def test_the_cash_flow_api_and_its_export(month, accountant):
    url = f"/api/v1/reports/cash-flow/?from={THIS_MONTH}&to={TODAY}"
    body = as_user(accountant).get(url).json()
    assert (body["net_change"], body["closing_cash"], body["difference"]) == (
        "-21400.00",
        "78600.00",
        "0.00",
    )
    assert body["rows"][0] == {
        "section": "operating",
        "label": "Operating activities",
        "kind": "heading",
        "amount": "",
    }
    assert as_user(accountant).get(url + "&export=xlsx").status_code == 200
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).get(url).status_code == 403
    ws_only = person("ws@sml.lk", "accountant", divisions=["WS"])
    refused = as_user(ws_only).get(url)
    assert refused.status_code == 400 and "whole company" in refused.json()["detail"]


def test_the_home_page_tiles(month, accountant):
    body = as_user(accountant).get("/api/v1/reports/dashboard/").json()
    assert body["division"] is None and body["company"] is True
    assert (body["this_month"]["income"], body["this_month"]["profit"]) == ("1000.00", "300.00")
    assert body["cash"]["balance"] == "78600.00"
    assert body["receivables"] == {"total": "0.00", "overdue": "0.00", "count": 0}
    assert body["year_to_date"]["budget_profit"] is None
    ws = as_user(accountant).get("/api/v1/reports/dashboard/?division=WS").json()
    assert ws["division"] == "WS" and ws["this_month"]["costs"] == "700.00"
    assert ws["cash"]["balance"] == "0.00"  # no bank account is set up for WS
    assert as_user(accountant).get("/api/v1/reports/dashboard/?division=XX").status_code == 400
