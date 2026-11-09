"""Profitability reports and production in the report builder (backlog P3-20 part 2):
closed orders' margin by order, customer, part, mould and division; estimate accuracy by
element; moulding runs, downtime, job cards, order costs and closed orders as report builder
sources, with their visibility."""

from decimal import Decimal as D

import pytest

from apps.accounting import report_builder as rb
from apps.inventory.models import Item, StockMovement, Store
from apps.production import closing

from .test_access import as_user
from .test_job_cards import supervisor  # noqa: F401
from .test_job_orders import accountant, manager, planner, shaft, storeman  # noqa: F401
from .test_order_close import deliver, made, shaft_order  # noqa: F401
from .test_sales_orders import director, executive, unilever  # noqa: F401
from .test_shift_reports import TODAY, clock  # noqa: F401

pytestmark = pytest.mark.django_db
URL = "/api/v1/order-profits/closed/"


@pytest.fixture
def closed(executive, accountant, shaft_order, made):  # noqa: F811
    """The 20 shafts delivered in full: the job closes (revenue 7,200, cost 3,080)."""
    deliver(executive, shaft_order, "18")
    store = Store.objects.get(code="WS-MAIN")
    StockMovement.objects.create(
        item=Item.objects.get(code="SH-100"),
        store=store,
        division=store.division,
        lot_no="OLD",
        kind="opening",
        movement_date=TODAY,
        quantity=D("2"),
        value=D("600.00"),
        created_by=accountant,
    )
    deliver(executive, shaft_order, "2")
    made.refresh_from_db()
    assert made.status == "closed"
    return made


def test_margins_of_closed_orders_by_customer_part_and_division(accountant, closed):  # noqa: F811
    found = closing.margins(accountant, TODAY, TODAY, "customer")
    [row] = found["rows"]
    assert (row["key"], row["orders"], row["revenue"], row["cost"], row["margin"]) == (
        "Unilever Sri Lanka",
        1,
        "7200.00",
        "3080.00",
        "4120.00",
    )
    assert row["margin_pct"] == "133.77" and found["total"]["margin"] == "4120.00"
    assert closing.margins(accountant, TODAY, TODAY, "part")["rows"][0]["key"] == "SH-100"
    assert closing.margins(accountant, TODAY, TODAY, "division")["rows"][0]["key"] == "WS"
    assert closing.margins(accountant, TODAY, TODAY, "mould")["rows"] == []  # a machining job
    assert closing.margins(accountant, TODAY, TODAY, "order")["rows"][0]["key"] == closed.number


def test_estimate_accuracy_by_element(accountant, closed):  # noqa: F811
    found = closing.accuracy(accountant, TODAY, TODAY)
    rows = {
        r["key"]: (r["estimate"], r["actual"], r["variance"], r["variance_pct"])
        for r in found["rows"]
    }
    assert found["orders"] == 1
    assert rows["material"] == ("5400.00", "972.00", "-4428.00", "-82.00")
    assert rows["machine"] == ("1800.00", "1800.00", "0.00", "0.00")
    assert rows["rejects"] == ("0.00", "308.00", "308.00", None)
    assert (found["material_price"], found["material_usage"]) == ("-1728.00", "-2700.00")


def test_the_closed_order_reports_page(accountant, planner, closed):  # noqa: F811
    client = as_user(accountant)
    body = client.get(f"{URL}margins/?by=part&start={TODAY}&end={TODAY}").json()
    assert body["rows"][0]["key"] == "SH-100"
    assert client.get(f"{URL}accuracy/?start={TODAY}&end={TODAY}").json()["orders"] == 1
    assert client.get(f"{URL}margins/?by=colour").status_code == 400
    assert client.get(f"{URL}nothing/").status_code == 404
    assert client.get(f"{URL}margins/?start={TODAY}&end=2000-01-01").status_code == 400
    assert as_user(planner).get(f"{URL}margins/").status_code == 403


def test_closed_orders_and_costs_in_the_report_builder(accountant, planner, closed):  # noqa: F811
    keys = {s.key for s in rb.sources_for(accountant)}
    assert {"order_costs", "closed_orders"} <= keys
    assert "closed_orders" not in {s.key for s in rb.sources_for(planner)}  # no money
    found = rb.run(
        accountant,
        rb.parse(
            accountant,
            {"source": "closed_orders", "columns": ["order", "customer", "revenue", "margin"]},
        ),
    )
    line = found["rows"][0]["cells"]
    assert (line["order"], line["customer"], line["revenue"], line["margin"]) == (
        closed.number,
        "Unilever Sri Lanka",
        "7200.00",
        "4120.00",
    )
    costs = rb.run(
        accountant,
        rb.parse(
            accountant,
            {"source": "order_costs", "columns": ["element", "amount"], "group_by": "element"},
        ),
    )
    assert costs["rows"][-1]["cells"]["amount"] == "3080.00"
