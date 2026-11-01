"""Goods receiving notes (backlog P16-06, spec 5A.2)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core import approvals
from apps.core.models import Division, Notification
from apps.inventory import items, receipts
from apps.inventory.models import GoodsReceipt, GoodsReceiptLine, GoodsReceiptPhoto, Store
from apps.inventory.receipts import LineInput, ReceiptError
from apps.masters.models import Currency, Supplier
from apps.purchasing import orders
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.orders import LineInput as POLine

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
St = GoodsReceipt.Status
PO = PurchaseOrder.Status
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def buyer():
    return person("buyer@sml.lk", "purchasing_officer", all_divisions=True)


@pytest.fixture
def stores():
    return person("stores@sml.lk", "store_supervisor", divisions=("IM",))


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def im():
    return Division.objects.get(code="IM")


@pytest.fixture
def po(buyer, director):
    """An approved PO: 300 kg of masterbatch and 1,000 kg of PP."""
    sdd = Supplier.objects.create(
        code="S0001", name="SDD Polymer", currency=Currency.objects.get(code="LKR")
    )
    lines = []
    for code, name in (("48-BL-08", "Black MB"), ("PP-H-WHITE", "PP homopolymer")):
        item = items.create_item(
            buyer, {"code": code, "name": name, "category": "raw_material", "unit": "kg"}
        )
        lines.append(item)
    order = orders.create(
        buyer,
        supplier=sdd,
        division=im(),
        delivery_date=TODAY + timedelta(days=7),
        lines=[POLine(lines[0], "300", "590"), POLine(lines[1], "1000", "420")],
    )
    orders.submit(buyer, order)
    return orders.approve(director, order)


def po_lines(order):
    return list(order.lines.order_by("line_no"))


def receive(user, order, *quantities, **values):
    """A draft GRN with (received, damaged) per PO line."""
    grn = receipts.create(user, order)
    lines = [
        LineInput(line.pk, received, damaged)
        for line, (received, damaged) in zip(po_lines(order), quantities, strict=False)
    ]
    return receipts.save(user, grn, lines=lines, **values)


# --- Making a GRN ----------------------------------------------------------------------------


def test_a_grn_starts_from_what_the_po_still_expects(po, stores):
    grn = receipts.create(stores, po)
    assert grn.number == f"GRN{TODAY:%y%m%d}01" and grn.status == St.DRAFT
    assert grn.store == Store.objects.get(code="IM-QUAR")  # goods wait for QC in quarantine
    assert grn.supplier == po.supplier and grn.division == po.division
    assert [(line.item.code, line.received_quantity) for line in grn.lines.all()] == [
        ("48-BL-08", Decimal("300")),
        ("PP-H-WHITE", Decimal("1000")),
    ]


def test_only_an_approved_po_is_received_by_the_stores_person(po, buyer, stores, director):
    with pytest.raises(ReceiptError, match="stores person"):
        receipts.create(buyer, po)
    with pytest.raises(ReceiptError, match="stores person"):
        receipts.create(director, po)
    draft = orders.revise(buyer, po, "New price")
    with pytest.raises(ReceiptError, match="approved purchase order"):
        receipts.create(stores, draft)
    po.refresh_from_db()
    with pytest.raises(ReceiptError, match="approved purchase order"):
        receipts.create(stores, po)  # replaced by the revision


def test_another_divisions_stores_person_cannot_receive(po):
    ws = person("ws-stores@sml.lk", "store_supervisor", divisions=("WS",))
    with pytest.raises(ReceiptError, match="approved purchase order"):
        receipts.create(ws, po)
    assert not receipts.visible(ws).exists()


@pytest.mark.parametrize(
    "received, damaged, why",
    [
        ("-1", "0", "cannot be negative"),
        ("10", "11", "damaged quantity cannot be more than received"),
        ("1.0001", "0", "3 decimal places"),
        ("x", "0", "not a number"),
        ("0", "0", "at least one line"),
    ],
)
def test_wrong_quantities_are_refused(po, stores, received, damaged, why):
    with pytest.raises(ReceiptError, match=why):
        receive(stores, po, (received, damaged), ("0", "0"))


def test_a_future_receipt_date_is_refused(po, stores):
    with pytest.raises(ReceiptError, match="future"):
        receive(stores, po, ("1", "0"), receipt_date=TODAY + timedelta(days=1))


# --- Confirming: partial deliveries, damage, excess -----------------------------------------


def test_partial_deliveries_update_the_po(po, stores):
    first = receipts.confirm(stores, receive(stores, po, ("100", "0"), ("1000", "0")))
    assert (first.status, first.confirmed_by, first.confirmed_at is not None) == (
        St.CONFIRMED,
        stores,
        True,
    )
    po.refresh_from_db()
    assert po.status == PO.PARTLY_RECEIVED
    assert [line.received_quantity for line in po_lines(po)] == [100, 1000]
    second = receipts.create(stores, po)
    assert [(line.item.code, line.received_quantity) for line in second.lines.all()] == [
        ("48-BL-08", Decimal("200"))
    ]
    receipts.confirm(stores, second)
    po.refresh_from_db()
    assert po.status == PO.RECEIVED
    with pytest.raises(ReceiptError, match="approved purchase order"):
        receipts.create(stores, po)


def test_damaged_goods_are_not_counted_as_received(po, stores):
    grn = receipts.confirm(stores, receive(stores, po, ("300", "20"), ("0", "0")))
    line = grn.lines.get(line_no=1)
    assert (line.good_quantity, line.excess_quantity) == (280, 0)
    po.refresh_from_db()
    assert po_lines(po)[0].received_quantity == 280 and po.status == PO.PARTLY_RECEIVED


def test_an_excess_waits_for_the_director(po, stores, director):
    grn = receipts.confirm(stores, receive(stores, po, ("320", "0"), ("1000", "0")))
    assert grn.status == St.AWAITING_APPROVAL
    assert grn.lines.get(line_no=1).excess_quantity == 20
    po.refresh_from_db()
    assert po.status == PO.APPROVED  # nothing is added yet
    assert Notification.objects.filter(user=director, event="approval_waiting").exists()
    with pytest.raises(ReceiptError):
        receipts.approve_excess(stores, grn)  # the stores person never approves
    grn = receipts.approve_excess(director, grn, "Supplier rounds to full bags")
    assert grn.status == St.CONFIRMED and grn.confirmed_by == stores
    po.refresh_from_db()
    assert po.status == PO.RECEIVED
    assert [line.received_quantity for line in po_lines(po)] == [320, 1000]


def test_a_refused_excess_goes_back_to_be_corrected(po, stores, director):
    grn = receipts.confirm(stores, receive(stores, po, ("320", "0")))
    with pytest.raises(ReceiptError, match="reason"):
        receipts.send_back(director, grn, "")
    grn = receipts.send_back(director, grn, "Return the extra 20 kg")
    assert grn.status == St.DRAFT and grn.confirmed_by is None
    grn = receive_again(stores, grn, po, ("300", "0"))
    assert receipts.confirm(stores, grn).status == St.CONFIRMED


def receive_again(user, grn, order, *quantities):
    lines = [
        LineInput(line.pk, received, damaged)
        for line, (received, damaged) in zip(po_lines(order), quantities, strict=False)
    ]
    return receipts.save(user, grn, lines=lines)


def test_only_the_person_who_made_the_grn_changes_or_confirms_it(po, stores):
    other = person("stores2@sml.lk", "store_supervisor", divisions=("IM",))
    grn = receive(stores, po, ("10", "0"))
    with pytest.raises(ReceiptError, match="Only the person"):
        receipts.confirm(other, grn)
    with pytest.raises(ReceiptError, match="Only the person"):
        receipts.save(other, grn, lines=[])


# --- After confirming: never changed; reversed with the Director ---------------------------


def test_a_confirmed_grn_never_changes(po, stores):
    grn = receipts.confirm(stores, receive(stores, po, ("100", "0")))
    with pytest.raises(ReceiptError, match="Only the person who made a draft"):
        receipts.save(stores, grn, lines=[LineInput(po_lines(po)[0].pk, "1")])
    with pytest.raises(ReceiptError):
        receipts.delete(stores, grn)
    with pytest.raises(DatabaseError, match="cannot be changed"), transaction.atomic():
        GoodsReceipt.objects.filter(pk=grn.pk).update(delivery_note_no="X")
    with pytest.raises(DatabaseError, match="cannot change"), transaction.atomic():
        GoodsReceiptLine.objects.filter(receipt=grn).update(received_quantity=Decimal("1"))
    # Deleting directly in the database is refused too (the stock movements also hold on).
    with pytest.raises(DatabaseError, match="cannot change"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM inventory_goodsreceiptline WHERE receipt_id = %s", [grn.pk])
    with pytest.raises(DatabaseError, match="cannot be deleted"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM inventory_goodsreceipt WHERE id = %s", [grn.pk])


def test_a_reversal_needs_a_reason_and_the_director(po, stores, director):
    grn = receipts.confirm(stores, receive(stores, po, ("100", "0"), ("1000", "0")))
    with pytest.raises(ReceiptError, match="reason"):
        receipts.request_reversal(stores, grn, " ")
    grn = receipts.request_reversal(stores, grn, "Entered against the wrong PO")
    assert grn.status == St.REVERSAL_REQUESTED
    with pytest.raises(ReceiptError):
        receipts.approve_reversal(stores, grn)
    grn = receipts.refuse_reversal(director, grn, "Check the delivery note first")
    assert grn.status == St.CONFIRMED
    grn = receipts.request_reversal(stores, grn, "Checked: wrong PO")
    grn = receipts.approve_reversal(director, grn, "Agreed")
    assert grn.status == St.REVERSED and grn.reversed_at is not None
    po.refresh_from_db()
    assert po.status == PO.APPROVED  # nothing received any more
    assert [line.received_quantity for line in po_lines(po)] == [0, 0]
    with pytest.raises(DatabaseError, match="for good"), transaction.atomic():
        GoodsReceipt.objects.filter(pk=grn.pk).update(status=St.CONFIRMED)
    actions = [row.action for row in approvals.history("goods_receipt_reversal", grn.pk)]
    assert actions[-1] == "approve"


def test_a_reversal_leaves_other_grns_received(po, stores, director):
    receipts.confirm(stores, receive(stores, po, ("100", "0")))
    second = receipts.confirm(stores, receive(stores, po, ("50", "0")))
    receipts.request_reversal(stores, second, "Counted twice")
    receipts.approve_reversal(director, second)
    po.refresh_from_db()
    assert po.status == PO.PARTLY_RECEIVED and po_lines(po)[0].received_quantity == 100


def test_the_director_cannot_approve_a_reversal_they_asked_for(po, director):
    both = person("both@sml.lk", "store_supervisor", "director", all_divisions=True)
    grn = receipts.confirm(both, receive(both, po, ("10", "0")))
    receipts.request_reversal(both, grn, "Mistake")
    with pytest.raises(ReceiptError):
        receipts.approve_reversal(both, grn)


# --- Photos ---------------------------------------------------------------------------------


def test_photos_are_checked_and_kept_once_confirmed(po, stores):
    grn = receive(stores, po, ("10", "0"))
    photo = receipts.add_photo(stores, grn, SimpleUploadedFile("bag.png", PNG))
    assert (photo.content_type, photo.size) == ("image/png", len(PNG))
    with pytest.raises(ReceiptError, match="JPG, PNG and PDF"):
        receipts.add_photo(stores, grn, SimpleUploadedFile("x.png", b"not an image"))
    receipts.confirm(stores, grn)
    receipts.add_photo(stores, grn, SimpleUploadedFile("note.png", PNG))  # still allowed
    with pytest.raises(ReceiptError, match="draft"):
        receipts.remove_photo(stores, photo)
    with pytest.raises(DatabaseError, match="cannot change"), transaction.atomic():
        GoodsReceiptPhoto.objects.filter(pk=photo.pk).delete()


# --- Through the API -------------------------------------------------------------------------


def test_the_api_receives_confirms_and_lists(po, stores, director):
    client = as_user(stores)
    receivable = client.get("/api/v1/goods-receipts/receivable/").json()
    assert [row["label"] for row in receivable] == [po.label]
    made = client.post(
        "/api/v1/goods-receipts/",
        {"purchase_order": po.pk, "delivery_note_no": "DN-551", "vehicle_no": "LH-4521"},
        format="json",
    )
    assert made.status_code == 201, made.json()
    grn = made.json()
    assert grn["delivery_note_no"] == "DN-551" and len(grn["lines"]) == 2
    lines = [
        {"po_line": row["po_line"], "received_quantity": "330", "damaged_quantity": "0"}
        for row in grn["lines"][:1]
    ]
    changed = client.put(
        f"/api/v1/goods-receipts/{grn['id']}/",
        {"delivery_note_no": "DN-551", "lines": lines},
        format="json",
    )
    assert changed.status_code == 200, changed.json()
    photo = client.post(
        f"/api/v1/goods-receipts/{grn['id']}/photos/",
        {"file": SimpleUploadedFile("bag.png", PNG)},
        format="multipart",
    )
    assert photo.status_code == 201 and len(photo.json()["photos"]) == 1
    shown = client.get(
        f"/api/v1/goods-receipts/{grn['id']}/photos/{photo.json()['photos'][0]['id']}/"
    )
    assert shown.status_code == 200
    confirmed = client.post(f"/api/v1/goods-receipts/{grn['id']}/confirm/", {}, format="json")
    assert confirmed.json()["status"] == "awaiting_approval"
    assert confirmed.json()["lines"][0]["excess_quantity"] == "30.000"

    boss = as_user(director)
    waiting = boss.get("/api/v1/goods-receipts/?waiting=me").json()
    assert [row["id"] for row in waiting] == [grn["id"]]
    detail = boss.get(f"/api/v1/goods-receipts/{grn['id']}/").json()
    assert detail["can_approve_excess"] and not detail["can_edit"]
    approved = boss.post(
        f"/api/v1/goods-receipts/{grn['id']}/approve/", {"comment": "OK"}, format="json"
    )
    assert approved.status_code == 200 and approved.json()["status"] == "confirmed"
    reversal = client.post(
        f"/api/v1/goods-receipts/{grn['id']}/reverse/", {"reason": "Wrong"}, format="json"
    )
    assert reversal.json()["status"] == "reversal_requested"
    done = boss.post(f"/api/v1/goods-receipts/{grn['id']}/reversal/approve/", {}, format="json")
    assert done.json()["status"] == "reversed"


def test_people_without_stores_access_see_no_grns(po, stores):
    grn = receipts.create(stores, po)
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    client = as_user(clerk)
    assert client.get("/api/v1/goods-receipts/").status_code == 403
    assert client.post(f"/api/v1/goods-receipts/{grn.pk}/confirm/").status_code == 403
