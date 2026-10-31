"""Sales reports and dashboard (backlog P15-11)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounting import services as chart
from apps.accounting.models import DetailType
from apps.core.models import Division
from apps.masters import banking, customers
from apps.sales import advances, orders, reports, services, workflow
from apps.sales.orders import Delivery
from apps.sales.orders import LineInput as OrderLine
from apps.sales.services import LineInput

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
IM = "IM"


@pytest.fixture
def executive():
    return person("sales@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def colleague():
    return person("sales2@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def manager():
    return person("salesmanager@sml.lk", "sales_manager", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def unilever(executive):
    return customers.create_customer(executive, {"name": "Unilever Sri Lanka"})


def quote(user, customer, price="2.35", quantity="10000", **values):
    return services.save(
        user,
        None,
        customer=customer,
        division=Division.objects.get(code=IM),
        lines=[LineInput(description="Cap, PP, white", quantity=quantity, unit_price=price)],
        **values,
    )


def approved(user, director, customer, **values):
    q = quote(user, customer, **values)
    workflow.submit(user, q)
    return workflow.approve(director, q)


# --- Quotation register ----------------------------------------------------------------------


def test_the_register_shows_each_person_their_own_and_the_manager_all(
    executive, colleague, manager, director, unilever
):
    mine = quote(executive, unilever)
    sent = approved(executive, director, unilever, price="3.00")
    theirs = quote(colleague, unilever, price="1.00")

    assert {r["id"] for r in reports.register(executive)} == {mine.pk, sent.pk}
    everything = reports.register(manager)
    assert {r["id"] for r in everything} == {mine.pk, sent.pk, theirs.pk}
    assert [r["label"] for r in reports.register(manager, status="approved")] == [sent.label]
    assert [r["id"] for r in reports.register(manager, salesperson=str(colleague.pk))] == [
        theirs.pk
    ]
    assert reports.register(manager, end=TODAY - timedelta(1)) == []
    summary = {s["status_code"]: s for s in reports.register_summary(everything)}
    assert (summary["draft"]["count"], summary["draft"]["total_lkr"]) == (2, "33500.00")
    assert summary["approved"]["total_lkr"] == "30000.00"
    assert {p["name"] for p in reports.salespeople(manager)} == {
        executive.full_name,
        colleague.full_name,
    }


# --- Win / loss --------------------------------------------------------------------------------


def test_won_and_lost_with_reasons_and_the_win_rate(executive, director, unilever):
    won = approved(executive, director, unilever)
    won = workflow.record_outcome(executive, won, accepted=True, reason="price")
    lost = approved(executive, director, unilever, price="7.65")
    lost = workflow.record_outcome(executive, lost, accepted=False, reason="price", note="Too high")
    other = approved(executive, director, unilever, price="1.00")
    other = workflow.record_outcome(executive, other, accepted=False, reason="lead_time")

    rows = reports.win_loss(executive, start=TODAY, end=TODAY)
    assert {(r["label"], r["outcome"], r["reason"]) for r in rows} == {
        (won.label, "Won", "Price"),
        (lost.label, "Lost", "Price"),
        (other.label, "Lost", "Delivery time"),
    }
    summary = reports.win_loss_summary(rows)
    assert summary["total"]["won"] == 1 and summary["total"]["lost"] == 2
    assert summary["total"]["win_rate"] == "33.3"
    # by value: won 23,500 of 23,500 + 76,500 + 10,000
    assert summary["total"]["value_win_rate"] == "21.4"
    price = next(r for r in summary["by_reason"] if r["reason_code"] == "price")
    assert (price["won"], price["lost"], price["lost_lkr"], price["win_rate"]) == (
        1,
        1,
        "76500.00",
        "50.0",
    )
    assert reports.win_loss(executive, start=TODAY + timedelta(1)) == []


# --- Needing attention -------------------------------------------------------------------------


def test_quotations_awaiting_approval_and_expiring_this_week(executive, director, unilever):
    waiting = quote(executive, unilever)
    workflow.submit(executive, waiting)
    soon = approved(executive, director, unilever, valid_until=TODAY + timedelta(3))
    approved(executive, director, unilever, valid_until=TODAY + timedelta(20))

    rows = reports.attention(executive)
    assert [(r["label"], r["kind"], r["days"]) for r in rows] == [
        (waiting.label, "approval", 0),
        (soon.label, "expiring", 3),
    ]
    assert director.full_name in rows[0]["approvers"]


# --- Open orders and deliveries -----------------------------------------------------------------


def test_open_orders_list_every_delivery_by_date(executive, director, unilever):
    won = approved(executive, director, unilever)
    won = workflow.record_outcome(executive, won, accepted=True, reason="price")
    order = orders.from_quotation(executive, won)
    line = order.lines.get()
    orders.save(
        executive,
        order,
        customer_po="UL/PO/7781",
        lines=[
            OrderLine(
                quantity="10000",
                quotation_line=line.quotation_line,
                schedule=[
                    Delivery(TODAY - timedelta(2), "4000"),
                    Delivery(TODAY + timedelta(30), "6000"),
                ],
            )
        ],
    )
    assert reports.open_orders(executive) == []  # a draft is not open yet
    orders.confirm(executive, order)

    rows = reports.open_orders(executive)
    assert [(r["due_date"], r["quantity"], r["status"], r["value_lkr"]) for r in rows] == [
        (TODAY - timedelta(2), "4,000 pcs", "Overdue", "9400.00"),
        (TODAY + timedelta(30), "6,000 pcs", "", "14100.00"),
    ]
    assert len(reports.open_orders(executive, until=TODAY + timedelta(7))) == 1


# --- Advances not yet set off ------------------------------------------------------------------


def test_advances_not_set_off_are_seen_by_their_salesperson_and_the_manager(
    executive, colleague, manager, director, unilever
):
    won = approved(executive, director, unilever)
    won = workflow.record_outcome(executive, won, accepted=True, reason="price")
    accountant = person("accountant@sml.lk", "accountant", all_divisions=True)
    cashier = person("cashier@sml.lk", "cashier", all_divisions=True)
    ledger = chart.create_account(
        accountant,
        name="Bank",
        account_type="bank",
        detail_type=DetailType.objects.get(name="Current account"),
        number="1030",
    )
    bank = banking.create_account(
        accountant,
        code="bank",
        kind="current",
        name="Bank",
        bank_name="HNB",
        account_number="1000123456",
        ledger_account=ledger.pk,
    )
    advance = advances.record(
        cashier,
        customer=unilever,
        account=bank,
        method="transfer",
        amount="10000",
        receipt_date=TODAY,
        reference="CEFT 1",
        quotation=won,
    )
    assert reports.advances_open(manager) == []  # not approved yet
    advances.approve(accountant, advance)

    rows = reports.advances_open(executive)
    assert [(r["number"], r["against"], r["balance_lkr"]) for r in rows] == [
        (advance.number, won.label, "10000.00")
    ]
    assert len(reports.advances_open(manager)) == 1
    assert len(reports.advances_open(cashier)) == 1
    assert reports.advances_open(colleague) == []


# --- Dashboard and the API ---------------------------------------------------------------------


def test_the_dashboard_agrees_with_the_reports(executive, director, unilever):
    q = quote(executive, unilever)
    workflow.submit(executive, q)
    approved(executive, director, unilever, valid_until=TODAY + timedelta(2))
    won = approved(executive, director, unilever, price="1.00")
    won = workflow.record_outcome(executive, won, accepted=True, reason="relationship")

    board = reports.dashboard(director)
    assert board["waiting_for_me"] == {
        "count": 1,
        "quotations": 1,
        "orders": 0,
        "total": "23500.00",
    }
    assert (board["awaiting_approval"], board["expiring"]) == (1, 1)
    assert board["live"] == {"count": 1, "total": "23500.00"}
    assert (board["this_month"]["won"], board["this_month"]["won_lkr"]) == (1, "10000.00")
    assert board["open_orders"] == {"count": 0, "total": "0.00"}
    assert reports.dashboard(executive)["waiting_for_me"]["count"] == 0
    assert reports.dashboard(director, "WS")["live"]["count"] == 0


def test_the_api_gives_rows_and_downloads(executive, director, unilever):
    approved(executive, director, unilever)
    client = as_user(executive)
    body = client.get("/api/v1/sales/reports/register/?status=approved").json()
    assert [r["status_code"] for r in body["rows"]] == ["approved"]
    assert body["summary"][0]["count"] == 1
    for path in ("register", "win-loss", "attention", "open-orders", "advances"):
        assert client.get(f"/api/v1/sales/reports/{path}/").status_code == 200
        pdf = client.get(f"/api/v1/sales/reports/{path}/?export=pdf")
        assert pdf["Content-Type"] == "application/pdf", path
        xlsx = client.get(f"/api/v1/sales/reports/{path}/?export=xlsx")
        assert xlsx["Content-Disposition"].endswith('.xlsx"'), path
    assert client.get("/api/v1/sales/dashboard/").json()["live"]["count"] == 1


def test_no_sales_access_no_reports():
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    client = as_user(clerk)
    assert client.get("/api/v1/sales/reports/register/").status_code == 403
    assert client.get("/api/v1/sales/dashboard/").status_code == 403
