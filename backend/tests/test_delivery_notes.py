"""Delivery notes (backlog P2-04, spec 5.3 and 6)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting.models import JournalEntry
from apps.core.models import Division
from apps.masters import customers
from apps.sales import deliveries, delivery_printing, orders, services, workflow
from apps.sales.deliveries import LineInput
from apps.sales.models import DeliveryNote, DeliveryNoteLine, SalesOrder
from apps.sales.orders import Delivery
from apps.sales.orders import LineInput as OrderLine
from apps.sales.services import LineInput as QuoteLine
from apps.sales.services import SalesError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
S = DeliveryNote.Status
OS = SalesOrder.Status
PDF = b"%PDF-1.4\n" + b"0" * 64


@pytest.fixture
def executive():
    return person("sales@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def stores():
    return person("stores@sml.lk", "store_supervisor", divisions=["IM"])


@pytest.fixture
def order(executive, director):
    """Open order for 10,000 caps (two call-offs) and 2 moulds of tooling."""
    customer = customers.create_customer(
        executive, {"name": "Unilever Sri Lanka", "delivery_address": "Grandpass, Colombo 14"}
    )
    q = services.save(
        executive,
        None,
        customer=customer,
        division=Division.objects.get(code="IM"),
        lines=[
            QuoteLine(description="Cap, PP, white", quantity="10000", unit_price="2.35"),
            QuoteLine(description="Cap mould", quantity="2", unit_price="150000"),
        ],
    )
    workflow.submit(executive, q)
    workflow.approve(director, q)
    workflow.record_outcome(executive, q, accepted=True, reason="price")
    o = orders.from_quotation(executive, q)
    caps, moulds = o.lines.order_by("line_no")
    orders.save(
        executive,
        o,
        customer_po="UL/PO/7781",
        lines=[
            OrderLine(
                quantity="10000",
                quotation_line=caps.quotation_line,
                schedule=[Delivery(TODAY, "6000"), Delivery(TODAY + timedelta(days=30), "4000")],
            ),
            OrderLine(quantity="2", quotation_line=moulds.quotation_line),
        ],
    )
    return orders.confirm(executive, o)


def lines(order, *quantities):
    return [
        LineInput(line, q)
        for line, q in zip(order.lines.order_by("line_no"), quantities, strict=False)
        if q
    ]


def deliver(user, order, *quantities, **values):
    note = deliveries.create(user, order, lines=lines(order, *quantities), **values)
    return deliveries.issue(user, note)


def status_of(order):
    order.refresh_from_db()
    return order.status


# --- Making and issuing ----------------------------------------------------------------------


def test_a_delivery_note_moves_the_order_on(order, stores):
    note = deliveries.create(
        stores, order, lines=lines(order, "6000"), vehicle_no="wp lh-4521", driver="Sunil"
    )
    assert note.number == f"DN{TODAY:%y%m%d}01"
    assert (note.status, note.vehicle_no, note.delivery_address) == (
        S.DRAFT,
        "WP LH-4521",
        "Grandpass, Colombo 14",
    )
    assert status_of(order) == OS.OPEN  # a draft delivers nothing
    deliveries.issue(stores, note)
    assert status_of(order) == OS.PARTLY_DELIVERED
    assert deliveries.remaining(order) == {
        order.lines.get(line_no=1).pk: Decimal("4000.000"),
        order.lines.get(line_no=2).pk: Decimal("2.000"),
    }
    deliver(stores, order, "4000", "2")
    assert status_of(order) == OS.DELIVERED
    assert not JournalEntry.objects.exists()  # no finished-goods stock until Phase 3


def test_never_more_than_is_still_to_deliver(order, stores, executive):
    with pytest.raises(SalesError, match="only 10000 pcs is still to deliver"):
        deliveries.create(stores, order, lines=lines(order, "10001"))
    with pytest.raises(SalesError, match="at most 3 decimal places"):
        deliveries.create(stores, order, lines=lines(order, "1.0001"))
    with pytest.raises(SalesError, match="at least one line"):
        deliveries.create(stores, order, lines=[])
    first = deliveries.create(stores, order, lines=lines(order, "7000"))
    second = deliveries.create(executive, order, lines=lines(order, "5000"))
    deliveries.issue(stores, first)
    # Two drafts together came to more than the order: the second is stopped at issue.
    with pytest.raises(SalesError, match="only 3000 pcs is still to deliver"):
        deliveries.issue(executive, second)


def test_the_database_refuses_delivering_too_much(order, stores):
    first = deliver(stores, order, "7000")
    second = deliveries.create(stores, order, lines=lines(order, "3000"))
    first_line = first.lines.get()
    with pytest.raises(DatabaseError, match="cannot be changed"):
        with transaction.atomic():
            DeliveryNoteLine.objects.filter(pk=first_line.pk).update(quantity="1")
    DeliveryNoteLine.objects.filter(note=second).update(quantity="3001")
    with pytest.raises(DatabaseError, match="more than ordered on line 1"):
        with transaction.atomic():
            DeliveryNote.objects.filter(pk=second.pk).update(status="issued")


def test_an_issued_note_never_changes(order, stores):
    note = deliver(stores, order, "6000")
    with pytest.raises(SalesError, match="Only the person who made a draft"):
        deliveries.save(stores, note, lines=lines(order, "1"))
    with pytest.raises(DatabaseError, match="cannot be changed"):
        with transaction.atomic():
            DeliveryNote.objects.filter(pk=note.pk).update(vehicle_no="X")
    with pytest.raises(DatabaseError, match="cannot be deleted"):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM sales_deliverynote WHERE id = %s", [note.pk])
    with pytest.raises(DatabaseError, match="cannot go from issued to draft"):
        with transaction.atomic():
            DeliveryNote.objects.filter(pk=note.pk).update(status="draft")


def test_drafts_are_changed_and_deleted_by_their_maker(order, stores, executive):
    note = deliveries.create(stores, order, lines=lines(order, "100"))
    with pytest.raises(SalesError, match="Only the person who made"):
        deliveries.save(executive, note, lines=lines(order, "200"))
    note = deliveries.save(stores, note, lines=lines(order, "200", "1"), driver="Kamal")
    assert sorted(note.lines.values_list("quantity", flat=True)) == [
        Decimal("1.000"),
        Decimal("200.000"),
    ]
    deliveries.delete(stores, note)
    assert not DeliveryNote.objects.exists()


# --- The customer's signature, cancelling -------------------------------------------------------


def test_the_signed_copy_comes_back(order, stores):
    note = deliver(stores, order, "6000")
    with pytest.raises(SalesError, match="between the delivery date and today"):
        deliveries.record_receipt(
            stores, note, received_by="N. Perera", received_on=TODAY + timedelta(days=1)
        )
    with pytest.raises(SalesError, match="JPG, PNG or PDF"):
        deliveries.record_receipt(
            stores,
            note,
            received_by="N. Perera",
            received_on=TODAY,
            signed_copy=SimpleUploadedFile("x.txt", b"hello"),
        )
    note = deliveries.record_receipt(
        stores,
        note,
        received_by="N. Perera",
        received_on=TODAY,
        signed_copy=SimpleUploadedFile("dn.pdf", PDF),
    )
    assert (note.status, note.received_by, note.signed_copy_type) == (
        S.RECEIVED,
        "N. Perera",
        "application/pdf",
    )
    with pytest.raises(DatabaseError, match="kept as it is"):
        with transaction.atomic():
            DeliveryNote.objects.filter(pk=note.pk).update(received_by="Someone else")


def test_cancelling_reopens_the_quantities(order, stores, executive):
    note = deliver(stores, order, "10000", "2")
    assert status_of(order) == OS.DELIVERED
    with pytest.raises(SalesError, match="Sales Manager or the stores"):
        deliveries.cancel(executive, note, "wrong lot")
    with pytest.raises(SalesError, match="reason"):
        deliveries.cancel(stores, note, " ")
    deliveries.cancel(stores, note, "Lorry turned back: wrong lot")
    assert status_of(order) == OS.OPEN
    assert deliveries.remaining(order)[order.lines.get(line_no=1).pk] == Decimal("10000")
    with pytest.raises(DatabaseError, match="cancelled for good"):
        with transaction.atomic():
            DeliveryNote.objects.filter(pk=note.pk).update(status="issued")


def test_an_order_with_deliveries_is_completed_not_cancelled(order, stores, executive):
    deliver(stores, order, "6000")
    order.refresh_from_db()
    assert not orders.can_cancel(executive, order)  # partly delivered
    order = orders.complete(executive, order)
    assert order.status == OS.COMPLETED
    with pytest.raises(SalesError, match="open sales orders"):
        deliveries.create(stores, order, lines=lines(order, "1"))


def test_who_sees_and_makes_notes(order, stores, executive):
    other = person("sales2@sml.lk", "sales_executive", all_divisions=True)
    ws_stores = person("wsstores@sml.lk", "store_supervisor", divisions=["WS"])
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    note = deliver(stores, order, "6000")
    assert list(deliveries.visible(executive)) == [note]  # their own order
    assert not deliveries.visible(other).exists()
    assert not deliveries.visible(ws_stores).exists()  # another division
    assert not deliveries.visible(clerk).exists()
    with pytest.raises(SalesError, match="open sales orders you may see"):
        deliveries.create(other, order, lines=lines(order, "1"))


# --- Printing and API ------------------------------------------------------------------------


def test_the_printed_note(order, stores):
    note = deliveries.create(stores, order, lines=lines(order, "6000"), vehicle_no="LH-4521")
    text = delivery_printing.render(note, compress=False)
    assert b"DRAFT" in text
    note = deliveries.issue(stores, note)
    text = delivery_printing.render(note, compress=False)
    for expected in (b"DELIVERY NOTE", note.number.encode(), b"UL/PO/7781", b"LH-4521", b"6,000"):
        assert expected in text, expected
    assert b"DRAFT" not in text and b"2.35" not in text  # no prices on a delivery note


def test_the_api(order, stores, executive):
    client = as_user(stores)
    todo = client.get("/api/v1/delivery-notes/orders/").json()
    assert [o["number"] for o in todo] == [order.number]
    form = client.get(f"/api/v1/delivery-notes/orders/?order={order.pk}").json()
    caps, moulds = form["lines"]
    assert (caps["to_deliver"], len(caps["schedule"])) == ("10000.000", 2)
    body = {
        "order": order.pk,
        "vehicle_no": "LH-4521",
        "lines": [
            {"order_line": caps["id"], "quantity": "6000"},
            {"order_line": moulds["id"], "quantity": ""},
        ],
    }
    made = client.post("/api/v1/delivery-notes/", body, format="json")
    assert made.status_code == 201, made.json()
    pk = made.json()["id"]
    assert [x["quantity"] for x in made.json()["lines"]] == ["6000.000", None]
    issued = client.post(f"/api/v1/delivery-notes/{pk}/issue/")
    assert issued.json()["status"] == "issued"
    signed = client.post(
        f"/api/v1/delivery-notes/{pk}/received/",
        {
            "received_by": "N. Perera",
            "received_on": TODAY.isoformat(),
            "signed_copy": SimpleUploadedFile("dn.pdf", PDF),
        },
        format="multipart",
    )
    assert signed.json()["signed_copy"] == "dn.pdf"
    assert client.get(f"/api/v1/delivery-notes/{pk}/signed-copy/").status_code == 200
    assert client.get(f"/api/v1/delivery-notes/{pk}/pdf/")["Content-Type"] == "application/pdf"
    detail = as_user(executive).get(f"/api/v1/sales-orders/{order.pk}/").json()
    assert detail["status"] == "partly_delivered"
    assert detail["lines"][0]["delivered"] == "6000.000"
    assert [d["number"] for d in detail["deliveries"]] == [made.json()["number"]]
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).get("/api/v1/delivery-notes/").status_code == 403
