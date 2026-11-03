"""Reorder levels and purchase requests (backlog P2-13, spec 6 inventory alerts)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core.models import Notification
from apps.inventory import items
from apps.inventory.models import StockMovement, Store
from apps.masters.models import Currency, Supplier
from apps.purchasing import orders
from apps.purchasing import requests as pr
from apps.purchasing.models import PurchaseRequest, PurchaseRequestLine, ReorderLevel
from apps.purchasing.orders import PurchasingError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()
D = Decimal
St = PurchaseRequest.Status


@pytest.fixture
def buyer():
    return person("buyer@sml.lk", "purchasing_officer", all_divisions=True)


@pytest.fixture
def storeman():
    return person("stores@sml.lk", "store_supervisor", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def sdd():
    return Supplier.objects.create(
        code="S0001", name="SDD Polymer (Pvt) Ltd", currency=Currency.objects.get(code="LKR")
    )


@pytest.fixture
def masterbatch(buyer):
    return items.create_item(
        buyer,
        {
            "code": "48-BL-08",
            "name": "Black MB 45% carbon",
            "category": "raw_material",
            "unit": "kg",
        },
    )


def main():
    return Store.objects.get(code="IM-MAIN")


def move(item, quantity, user):
    StockMovement.objects.create(
        item=item,
        store=main(),
        division=main().division,
        lot_no="L1",
        kind="opening",
        movement_date=TODAY,
        quantity=D(quantity),
        value=D("0"),
        created_by=user,
    )


@pytest.fixture
def level(storeman, masterbatch, sdd):
    move(masterbatch, "150", storeman)
    return pr.set_level(
        storeman, item=masterbatch, store=main(), level="100", quantity="500", usual_supplier=sdd
    )


def alerts():
    return Notification.objects.filter(event="reorder_alert")


# --- Reorder levels and alerts ----------------------------------------------------------------


def test_above_the_level_nobody_is_told(level):
    assert pr.check() == 0 and not alerts().exists()
    (position,) = pr.positions([level])
    assert (position.on_hand, position.low) == (D("150"), False)


def test_falling_to_the_level_tells_stores_and_purchasing_once(level, storeman, buyer, masterbatch):
    move(masterbatch, "-70", storeman)  # 80 left
    assert pr.check() == 1
    assert set(alerts().values_list("user__email", flat=True)) >= {"stores@sml.lk", "buyer@sml.lk"}
    assert alerts().first().link == "/reorder"
    assert pr.check() == 0  # told once only
    move(masterbatch, "100", storeman)  # 180: above again, and the next fall tells them again
    assert pr.check() == 0
    assert ReorderLevel.objects.get(pk=level.pk).alerted_at is None
    move(masterbatch, "-100", storeman)
    assert pr.check() == 1


def test_only_a_main_store_and_a_stock_item(storeman, masterbatch):
    with pytest.raises(PurchasingError, match="main store"):
        pr.set_level(
            storeman,
            item=masterbatch,
            store=Store.objects.get(code="IM-QUAR"),
            level="1",
            quantity="5",
        )
    with pytest.raises(PurchasingError, match="more than 0"):
        pr.set_level(storeman, item=masterbatch, store=main(), level="1", quantity="0")


def test_a_clerk_cannot_set_levels_or_raise_requests(masterbatch):
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    with pytest.raises(PurchasingError, match="stores person or purchasing"):
        pr.set_level(clerk, item=masterbatch, store=main(), level="1", quantity="5")


# --- The request ----------------------------------------------------------------------------


def test_one_click_makes_a_draft_request_from_the_usual_supplier(level, storeman, masterbatch):
    move(masterbatch, "-70", storeman)
    pr.check()
    request = pr.from_level(storeman, level)
    assert request.number.startswith(f"PR{TODAY:%y%m}")
    assert (request.status, request.supplier.code, request.from_reorder) == (
        St.DRAFT,
        "S0001",
        True,
    )
    line = request.lines.get()
    assert (line.item, line.quantity) == (masterbatch, D("500"))
    # What is requested counts as coming: the alert is cleared.
    pr.check()
    assert ReorderLevel.objects.get(pk=level.pk).alerted_at is None
    (position,) = pr.positions([level])
    assert position.requested == D("500")


def test_the_author_never_approves_and_the_director_does(level, storeman, director):
    request = pr.from_level(storeman, level)
    pr.submit(storeman, request)
    with pytest.raises(PurchasingError):
        pr.approve(storeman, request)
    request = pr.approve(director, request, "OK")
    assert request.status == St.APPROVED and request.approved_at is not None


def test_a_rejected_request_is_closed(level, storeman, director):
    request = pr.from_level(storeman, level)
    pr.submit(storeman, request)
    request = pr.reject(director, request, "Enough in the other store")
    assert (request.status, request.end_reason) == (St.REJECTED, "Enough in the other store")
    with pytest.raises(DatabaseError, match="closed"), transaction.atomic():
        PurchaseRequest.objects.filter(pk=request.pk).update(reason="changed")


def test_lines_are_kept_once_sent(level, storeman):
    request = pr.from_level(storeman, level)
    pr.submit(storeman, request)
    with pytest.raises(DatabaseError, match="only while it is a draft"), transaction.atomic():
        PurchaseRequestLine.objects.filter(request=request).update(quantity=D("1"))


def test_purchasing_makes_the_order_at_the_last_price(
    level, storeman, buyer, director, sdd, masterbatch
):
    earlier = orders.create(
        buyer,
        supplier=sdd,
        division=main().division,
        lines=[orders.LineInput(masterbatch, "100", "590.00")],
        delivery_date=TODAY + timedelta(days=3),
    )
    orders.submit(buyer, earlier)
    orders.approve(director, earlier)
    request = pr.from_level(storeman, level)
    pr.submit(storeman, request)
    pr.approve(director, request)
    with pytest.raises(PurchasingError, match="Only purchasing"):
        pr.make_order(storeman, request)
    order = pr.make_order(buyer, request)
    line = order.lines.get()
    assert (order.status, order.supplier, line.quantity, line.unit_price) == (
        "draft",
        sdd,
        D("500"),
        D("590.00"),
    )
    request.refresh_from_db()
    assert (request.status, request.purchase_order) == (St.ORDERED, order)
    # The draft order now counts as coming, instead of the request.
    (position,) = pr.positions([level])
    assert (position.on_order, position.requested) == (D("600"), D("0"))


def test_without_an_earlier_price_purchasing_types_it(level, storeman, buyer, director):
    request = pr.from_level(storeman, level)
    pr.submit(storeman, request)
    pr.approve(director, request)
    with pytest.raises(PurchasingError, match="enter the price"):
        pr.make_order(buyer, request)
    order = pr.make_order(buyer, request, prices={1: "610.00"})
    assert order.lines.get().unit_price == D("610.00")


def test_a_draft_is_cancelled_with_a_reason(level, storeman):
    request = pr.from_level(storeman, level)
    with pytest.raises(PurchasingError, match="reason"):
        pr.cancel(storeman, request, " ")
    assert pr.cancel(storeman, request, "Not needed").status == St.CANCELLED


# --- The API ----------------------------------------------------------------------------------


def test_the_reorder_page_and_one_click_through_the_api(level, storeman, director, masterbatch):
    move(masterbatch, "-70", storeman)
    client = as_user(storeman)
    rows = client.get("/api/v1/reorder-levels/?low=1").json()
    assert [(r["item"]["code"], r["on_hand"], r["low"]) for r in rows] == [
        ("48-BL-08", "80.000", True)
    ]
    made = client.post(f"/api/v1/reorder-levels/{level.pk}/request/")
    assert made.status_code == 201, made.content
    pk = made.json()["id"]
    assert client.post(f"/api/v1/purchase-requests/{pk}/submit/").status_code == 200
    body = as_user(director).post(
        f"/api/v1/purchase-requests/{pk}/approve/", {"comment": "OK"}, format="json"
    )
    assert body.status_code == 200 and body.json()["status"] == "approved"


def test_the_stores_person_sets_a_level_through_the_api(storeman, masterbatch, sdd):
    response = as_user(storeman).post(
        "/api/v1/reorder-levels/",
        {
            "item": masterbatch.pk,
            "store": main().pk,
            "level": "50",
            "quantity": "200",
            "usual_supplier": sdd.pk,
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    assert response.json()["level"] == "50.000"
