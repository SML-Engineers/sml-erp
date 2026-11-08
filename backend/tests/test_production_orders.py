"""Moulding production orders (backlog P3-06): for stock or for a sales order line's delivery
schedule, numbered from the number series, the BOM in force copied on release and never
changed, material requirements against stock, purchase orders, requests and other orders, a
draft purchase request for the shortage, family moulds by the shot, statuses that only move
forward, where-used and open orders per part."""

from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core.models import Division, Notification
from apps.inventory.models import StockMovement, Store
from apps.production import boms, moulds, orders
from apps.production.models import OrderBomLine, ProductionOrder, ProductionOrderDue
from apps.production.orders import OrderError
from apps.purchasing.models import PurchaseRequest
from apps.sales import orders as sales_orders
from apps.sales.models import SalesOrder

from .test_access import as_user, person
from .test_boms import item
from .test_sales_orders import (  # noqa: F401
    call_offs,
    director,
    executive,
    from_quote,
    unilever,
    won,
)

pytestmark = pytest.mark.django_db
URL = "/api/v1/production-orders/"
TODAY = timezone.localdate()
St = ProductionOrder.Status


@pytest.fixture
def planner():
    return person("planner@sml.lk", "production_planner", divisions=["IM"])


@pytest.fixture
def manager():
    return person("pm@sml.lk", "production_manager", divisions=["IM"])


@pytest.fixture
def storeman():
    return person("stores@sml.lk", "store_supervisor", all_divisions=True)


LINES = [
    {"line_type": "raw", "component": "PP-H"},
    {"line_type": "masterbatch", "component": "MB-BLK", "pct_of_resin": "2"},
    {"line_type": "packing", "component": "BAG-1K", "quantity": "1"},
]


def approve(planner, manager, bom):
    boms.submit(planner, bom)
    return boms.decide(manager, bom, "approve")


@pytest.fixture
def cap(planner, manager):
    """Caps from an 8-cavity mould: 4.725 g of PP a cap, 2% black, a bag per 1,000."""
    part = item(planner, "CAP-28", "Cap 28 mm")
    item(planner, "PP-H", "PP homopolymer", "raw_material", "kg")
    item(planner, "MB-BLK", "Black masterbatch", "raw_material", "kg")
    item(planner, "BAG-1K", "Polybag 1000", "packing")
    base = {"cycle_time_s": "12", "shot_weight_g": "40", "runner_weight_g": "4"}
    moulds.create(planner, base | {"code": "MD-001", "name": "Cap", "parts": "CAP-28 x 8"})
    bom = boms.create(
        planner,
        {
            "item": "CAP-28",
            "kind": "moulding",
            "mould": "MD-001",
            "base_quantity": "1000",
            "reject_pct": "5",
            "outputs": [{"item": "CAP-28", "cavities": 8, "part_weight_g": "4"}],
            "lines": LINES,
        },
    )
    approve(planner, manager, bom)
    return part


def stock(code, quantity, user):
    store = Store.objects.get(code="IM-MAIN")
    StockMovement.objects.create(
        item=boms.Item.objects.get(code=code),
        store=store,
        division=store.division,
        lot_no="L1",
        kind="opening",
        movement_date=TODAY,
        quantity=D(quantity),
        value=D("0"),
        created_by=user,
    )


def for_stock(planner, quantity="10000", **more):
    values = {"item": "CAP-28", "quantity": quantity, "due_date": TODAY + timedelta(days=10)}
    return orders.create(planner, values | more)


def delete_row(order):
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM production_productionorder WHERE id = %s", [order.pk])


def need(order) -> dict:
    return {r["code"]: r for r in orders.requirements(order)}


def test_an_order_for_stock_is_numbered_released_and_keeps_its_bom(planner, manager, cap):
    made = as_user(planner).post(
        URL,
        {
            "item": "CAP-28",
            "quantity": "10000",
            "purpose": "stock",
            "due_date": (TODAY + timedelta(days=10)).isoformat(),
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    body = made.json()
    assert body["number"].startswith(f"MO{TODAY:%y%m}") and body["status"] == "draft"
    assert (body["division"], body["mould"], body["can_release"]) == ("IM", "MD-001", True)
    # A draft shows what the BOM in force would need: 10 × 4.725 kg of PP, 2% black, 10 bags.
    preview = {r["code"]: r["required"] for r in body["requirements"]}
    assert preview == {"PP-H": "47.25", "MB-BLK": "0.945", "BAG-1K": "10"}
    order = ProductionOrder.objects.get(pk=body["id"])
    assert not order.bom_lines.exists()

    released = as_user(planner).post(f"{URL}{order.pk}/release/")
    assert released.status_code == 200, released.json()
    assert released.json()["status"] == "released" and released.json()["released_by"] == "Planner"
    order.refresh_from_db()
    copied = {x.component.code: x.required for x in order.bom_lines.all()}
    assert copied == {"PP-H": D("47.25"), "MB-BLK": D("0.945"), "BAG-1K": D("10")}
    assert order.bom.revision == 1 and order.mould.code == "MD-001"

    # A new BOM revision never alters the released order.
    new = boms.copy(planner, order.bom)
    boms.update(planner, new, {"reject_pct": "0", "lines": LINES})
    approve(planner, manager, new)
    order.refresh_from_db()
    assert order.bom.revision == 1
    assert need(order)["PP-H"]["required"] == D("47.25")

    # The database keeps a released order, its due dates and its BOM copy.
    for change, message in [
        (lambda: ProductionOrder.objects.filter(pk=order.pk).update(quantity=D("1")), "released"),
        (lambda: delete_row(order), "never deleted"),
        (lambda: ProductionOrder.objects.filter(pk=order.pk).update(status="draft"), "cannot go"),
        (lambda: ProductionOrder.objects.filter(pk=order.pk).update(number="X1"), "number"),
        (lambda: OrderBomLine.objects.filter(order=order).update(required=D("1")), "never"),
        (lambda: OrderBomLine.objects.filter(order=order).delete(), "never changes"),
        (lambda: ProductionOrderDue.objects.filter(order=order).update(quantity=D("1")), "due"),
    ]:
        with pytest.raises(DatabaseError, match=message), transaction.atomic():
            change()
    # Saving it unchanged is allowed.
    order.save()


@pytest.mark.parametrize(
    "values, message",
    [
        ({"item": "NONE-1"}, "no item NONE-1"),
        ({"item": "PP-H"}, "not an active finished part"),
        ({"quantity": "0"}, "quantity is more than 0"),
        ({"quantity": "abc"}, "Give the quantity"),
        ({"quantity": "1.2345"}, "at most 3 decimal places"),
        ({"purpose": "gift"}, "for a sales order or for stock"),
        ({"purpose": "sales", "sales_line": "999999"}, "Choose the sales order line"),
        ({"due_date": "", "dues": []}, "Give the due date"),
        ({"due_date": "soon"}, "Give the due date 1"),
        (
            {"dues": [{"due_date": "2026-12-01", "quantity": "6000"}]},
            "add up to 6000, not the order's 10000",
        ),
    ],
)
def test_orders_are_checked(planner, cap, values, message):
    with pytest.raises(OrderError, match=message):
        for_stock(planner, **values)
    assert not ProductionOrder.objects.exists()


def test_only_the_planner_makes_orders_and_the_stores_read_them(planner, cap, storeman):
    with pytest.raises(OrderError, match="Only the Production Planner"):
        for_stock(storeman)
    order = for_stock(planner)
    seen = as_user(storeman).get(URL)
    assert seen.status_code == 200 and seen.json()["can_plan"] is False
    assert [o["number"] for o in seen.json()["results"]] == [order.number]
    refused = as_user(storeman).post(f"{URL}{order.pk}/release/")
    assert refused.status_code == 400 and "Only the Production Planner" in refused.json()["detail"]
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).get(URL).status_code == 403
    # Another division's planner does not see it.
    ws = person("ws@sml.lk", "production_planner", divisions=["WS"])
    assert as_user(ws).get(f"{URL}{order.pk}/").status_code == 404


def test_an_order_for_a_sales_order_line_takes_its_delivery_schedule(
    planner,
    cap,
    executive,  # noqa: F811
    from_quote,  # noqa: F811
):
    with pytest.raises(OrderError, match="is not open"):
        for_stock(planner, purpose="sales", sales_line=from_quote.lines.get().pk)
    sales_orders.save(
        executive,
        from_quote,
        lines=call_offs(from_quote, (14, "6000"), (28, "4000")),
        customer_po="P1",
    )
    sales_orders.confirm(executive, from_quote)
    line = from_quote.lines.get()
    first = orders.create(
        planner, {"item": "CAP-28", "quantity": "7000", "purpose": "sales", "sales_line": line.pk}
    )
    assert [(d.due_date, d.quantity) for d in first.dues.all()] == [
        (TODAY + timedelta(days=14), D("6000")),
        (TODAY + timedelta(days=28), D("1000")),
    ]
    with pytest.raises(OrderError, match="has 3000 pcs left to plan; make the rest for stock"):
        for_stock(planner, quantity="4000", purpose="sales", sales_line=line.pk)
    listed = as_user(planner).get(f"{URL}sales-lines/").json()["results"]
    assert (listed[0]["order"], listed[0]["planned"], listed[0]["left"]) == (
        from_quote.number,
        "7000",
        "3000",
    )
    assert listed[0]["customer"] == "Unilever Sri Lanka"
    # A cancelled order frees its quantity.
    orders.cancel(planner, first, "Customer moved the call-off")
    second = for_stock(planner, quantity="10000", purpose="sales", sales_line=line.pk)
    body = as_user(planner).get(f"{URL}{second.pk}/").json()
    assert body["sales_line"]["order"] == from_quote.number
    assert body["customer"] == "Unilever Sri Lanka"
    # A draft can change; a released order cannot.
    orders.update(planner, second, {"quantity": "9000"})
    second.refresh_from_db()
    assert second.quantity == D("9000") and sum(d.quantity for d in second.dues.all()) == 9000
    orders.release(planner, second)
    with pytest.raises(OrderError, match="is released"):
        orders.update(planner, second, {"quantity": "8000"})
    SalesOrder.objects.filter(pk=from_quote.pk).update(status="cancelled")
    with pytest.raises(OrderError, match="is not open"):
        for_stock(planner, quantity="1", purpose="sales", sales_line=line.pk)


def test_shortages_are_shown_told_and_requested(
    planner, cap, storeman, django_capture_on_commit_callbacks
):
    stock("PP-H", "60", storeman)
    stock("BAG-1K", "100", storeman)
    stock("MB-BLK", "1", storeman)
    first = for_stock(planner)  # needs 47.25 kg PP
    orders.release(planner, first)
    second = for_stock(planner)
    short = need(second)
    # 60 kg in the store, 47.25 kg for the first order: 12.75 free, 34.5 short.
    assert (short["PP-H"]["on_hand"], short["PP-H"]["other_orders"]) == (D("60"), D("47.25"))
    assert short["PP-H"]["shortage"] == D("34.5")
    assert short["MB-BLK"]["shortage"] == D("0.89")  # 1 kg less 0.945 for the first order
    assert short["BAG-1K"]["shortage"] == D("0")
    told = Notification.objects.filter(event="material_shortage")
    told.delete()
    with django_capture_on_commit_callbacks(execute=True):
        orders.release(planner, second)
    assert told.filter(user=storeman, title__contains=second.number).exists()

    # The planner cannot raise purchase requests; the stores person can, from the order.
    refused = as_user(planner).post(f"{URL}{second.pk}/purchase-request/")
    assert refused.status_code == 400 and "stores person or purchasing" in refused.json()["detail"]
    made = as_user(storeman).post(f"{URL}{second.pk}/purchase-request/")
    assert made.status_code == 200, made.json()
    request = PurchaseRequest.objects.get(number=made.json()["purchase_request"]["number"])
    assert request.status == "draft" and request.division.code == "IM"
    assert {(x.item.code, x.quantity) for x in request.lines.all()} == {
        ("PP-H", D("34.5")),
        ("MB-BLK", D("0.89")),
    }
    assert second.number in request.reason
    assert request.needed_by == TODAY + timedelta(days=10)
    # What is requested counts as coming: nothing is short now.
    assert need(second)["PP-H"]["shortage"] == D("0")
    with pytest.raises(OrderError, match="not short of anything to buy"):
        orders.raise_request(storeman, second)


def test_customer_supplied_material_is_never_bought(planner, manager, cap, storeman):
    new = boms.copy(planner, boms.in_force(cap))
    supplied = [dict(LINES[0], customer_supplied=True), *LINES[1:]]
    boms.update(planner, new, {"lines": supplied})
    approve(planner, manager, new)
    order = for_stock(planner)
    orders.release(planner, order)
    resin = need(order)["PP-H"]
    assert resin["customer_supplied"] and not resin["buy"] and resin["shortage"] > 0
    request = orders.raise_request(storeman, order)
    assert "PP-H" not in {x.item.code for x in request.lines.all()}


def test_a_family_mould_order_is_worked_out_in_shots(planner, manager):
    item(planner, "CAP-28", "Cap 28 mm")
    item(planner, "LID-90", "Lid 90 mm")
    item(planner, "PP-H", "PP homopolymer", "raw_material", "kg")
    base = {"cycle_time_s": "12", "shot_weight_g": "40", "runner_weight_g": "6"}
    moulds.create(
        planner, base | {"code": "MD-002", "name": "Family", "parts": "CAP-28 x 4; LID-90 x 2"}
    )
    family = boms.create(
        planner,
        {
            "item": "LID-90",
            "kind": "moulding",
            "mould": "MD-002",
            "reject_pct": "2",
            "outputs": [
                {"item": "CAP-28", "cavities": 4, "part_weight_g": "4"},
                {"item": "LID-90", "cavities": 2, "part_weight_g": "10"},
            ],
            "lines": LINES[:1],
        },
    )
    approve(planner, manager, family)
    # 1,001 lids at 2 a shot: 501 shots of 42.84 g.
    lids = orders.create(
        planner, {"item": "LID-90", "quantity": "1001", "due_date": TODAY.isoformat()}
    )
    assert orders.payload(lids, planner)["family_shots"] == "501"
    assert need(lids)["PP-H"]["required"] == D("21.46284")
    # Caps from the same family BOM: 1,000 caps at 4 a shot is 250 shots.
    caps = orders.create(
        planner, {"item": "CAP-28", "quantity": "1000", "due_date": TODAY.isoformat()}
    )
    orders.release(planner, caps)
    caps.refresh_from_db()
    assert caps.bom == family and caps.mould.code == "MD-002"
    assert caps.bom_lines.get().required == D("10.71")
    assert orders.payload(caps, planner)["family_shots"] == "250"


def test_statuses_move_forward_and_where_used(planner, manager, cap):
    order = for_stock(planner)
    with pytest.raises(OrderError, match="cannot be completed"):
        orders.complete(planner, order)
    orders.release(planner, order)
    with pytest.raises(OrderError, match="Only a draft is released"):
        orders.release(planner, order)
    with pytest.raises(OrderError, match="Give the reason"):
        orders.cancel(planner, order, " ")
    other = for_stock(planner, quantity="2000")

    used = as_user(planner).get(f"{URL}where-used/?item=PP-H").json()
    assert [(x["number"], x["required"]) for x in used["needing"]] == [(order.number, "47.25")]
    made = as_user(planner).get(f"{URL}where-used/?item=CAP-28").json()
    assert {o["number"] for o in made["making"]} == {order.number, other.number}
    assert made["making_total"] == "12000"
    opened = as_user(planner).get(f"{URL}?status=open&item=CAP-28").json()["results"]
    assert len(opened) == 2

    for action, status in [("complete", "completed"), ("close", "closed")]:
        done = as_user(planner).post(f"{URL}{order.pk}/{action}/")
        assert done.status_code == 200 and done.json()["status"] == status
    with pytest.raises(OrderError, match="cannot be cancelled"):
        orders.cancel(planner, order, "Too late")
    with pytest.raises(DatabaseError, match="closed: it never changes"), transaction.atomic():
        ProductionOrder.objects.filter(pk=order.pk).update(notes="x")
    cancelled = as_user(planner).post(f"{URL}{other.pk}/cancel/", {"reason": "Not needed"})
    assert cancelled.json()["status"] == "cancelled"
    assert as_user(planner).post(f"{URL}{other.pk}/explode/").status_code == 404


def test_a_part_needs_an_approved_moulding_bom_to_be_released(planner, manager):
    part = item(planner, "CAP-30", "Cap 30 mm")
    with pytest.raises(OrderError, match="no approved BOM yet"):
        orders.create(planner, {"item": "CAP-30", "quantity": "10", "due_date": TODAY})
    part.division = Division.objects.get(code="IM")
    part.save()
    order = orders.create(planner, {"item": "CAP-30", "quantity": "10", "due_date": TODAY})
    assert orders.payload(order, planner)["can_release"] is False
    with pytest.raises(OrderError, match="has no approved BOM"):
        orders.release(planner, order)
    item(planner, "INS-1", "Brass insert", "bought_out")
    general = boms.create(
        planner,
        {
            "item": "CAP-30",
            "division": "IM",
            "lines": [{"line_type": "bought", "component": "INS-1", "quantity": "1"}],
        },
    )
    approve(planner, manager, general)
    with pytest.raises(OrderError, match="not a moulding BOM with a mould"):
        orders.release(planner, order)
