"""Purchase orders (backlog P16-04, spec 5A.1)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import TaxCode, TaxComponent
from apps.core import approvals
from apps.core.models import Division, Notification
from apps.inventory import items
from apps.masters.models import Currency, Supplier
from apps.purchasing import orders
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.purchasing.orders import LineInput, PurchasingError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
St = PurchaseOrder.Status


@pytest.fixture
def buyer():
    return person("buyer@sml.lk", "purchasing_officer", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def sdd():
    return Supplier.objects.create(
        code="S0001",
        name="SDD Polymer (Pvt) Ltd",
        currency=Currency.objects.get(code="LKR"),
        payment_terms_days=30,
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


def im():
    return Division.objects.get(code="IM")


def raise_po(buyer, sdd, masterbatch, qty="300", price="590.00", **values):
    values.setdefault("delivery_date", TODAY + timedelta(days=7))
    return orders.create(
        buyer, supplier=sdd, division=im(), lines=[LineInput(masterbatch, qty, price)], **values
    )


@pytest.fixture
def draft(buyer, sdd, masterbatch):
    return raise_po(buyer, sdd, masterbatch)


@pytest.fixture
def approved(draft, buyer, director):
    orders.submit(buyer, draft)
    return orders.approve(director, draft, "Price as agreed")


# --- Raising -----------------------------------------------------------------------------


def test_the_buyer_raises_a_numbered_po_like_the_sample(draft, masterbatch):
    assert draft.number == f"PO{TODAY:%y%m%d}01" and draft.label == draft.number
    assert (draft.status, draft.currency.code, draft.payment_terms) == ("draft", "LKR", "Net 30")
    line = draft.lines.get()
    assert (line.description, line.unit, line.quantity) == ("Black MB 45% carbon", "kg", 300)
    assert (line.amount, draft.total_amount, draft.total_lkr) == (
        Decimal("177000.00"),
        Decimal("177000.00"),
        Decimal("177000.00"),
    )


def test_vat_is_added_as_on_the_sample(buyer, sdd, masterbatch):
    accountant = person("accountant@sml.lk", "accountant", all_divisions=True)
    taxes.add_rate(
        accountant,
        TaxComponent.objects.get(code="VAT"),
        effective_from=TODAY - timedelta(days=400),
        rate="18",
    )
    vat = TaxCode.objects.get(code="VAT")
    po = orders.create(
        buyer,
        supplier=sdd,
        division=im(),
        lines=[LineInput(masterbatch, "300", "590", vat)],
    )
    assert (po.subtotal, po.tax_total, po.total_amount) == (
        Decimal("177000.00"),
        Decimal("31860.00"),
        Decimal("208860.00"),
    )


@pytest.mark.parametrize(
    "qty, price, why",
    [
        ("0", "590", "quantity must be more than 0"),
        ("1.0001", "1", "3 decimal places"),
        ("1", "-5", "unit price must be more than 0"),
        ("x", "1", "not a number"),
    ],
)
def test_wrong_lines_are_refused(buyer, sdd, masterbatch, qty, price, why):
    with pytest.raises(PurchasingError, match=why):
        raise_po(buyer, sdd, masterbatch, qty=qty, price=price)


def test_only_the_buyer_raises_pos_for_active_suppliers_and_items(
    buyer, director, sdd, masterbatch
):
    with pytest.raises(PurchasingError, match="Only the Purchasing Officer"):
        raise_po(director, sdd, masterbatch)
    with pytest.raises(PurchasingError, match="production division"):
        orders.create(buyer, supplier=sdd, division=Division.objects.get(code="HO"), lines=[])
    items.set_active(buyer, masterbatch, False, reason="Not used")
    masterbatch.refresh_from_db()
    with pytest.raises(PurchasingError, match="active item"):
        raise_po(buyer, sdd, masterbatch)
    sdd.is_active = False
    sdd.save()
    with pytest.raises(PurchasingError, match="active supplier"):
        raise_po(buyer, sdd, masterbatch)


# --- Approval ------------------------------------------------------------------------------


def test_every_po_goes_to_the_director(draft, buyer, director, sdd, masterbatch):
    with pytest.raises(PurchasingError, match="delivery date"):
        orders.submit(buyer, raise_po(buyer, sdd, masterbatch, delivery_date=None))
    po = orders.submit(buyer, draft, "Urgent for the cap job")
    assert po.status == St.AWAITING_APPROVAL
    state = approvals.state_of("purchase_order", po.pk)
    assert [step["role"] for step in state.route] == ["director"]
    assert Notification.objects.filter(user=director, event="approval_waiting").exists()
    with pytest.raises(PurchasingError):
        orders.approve(buyer, po)  # not the Director
    po = orders.approve(director, po, "Price as agreed")
    assert po.status == St.APPROVED and po.approved_at is not None
    sdd.refresh_from_db()
    masterbatch.refresh_from_db()
    assert sdd.first_used_at and masterbatch.first_used_at  # codes now fixed


def test_the_director_cannot_approve_a_po_they_raised(sdd, masterbatch):
    both = person("both@sml.lk", "purchasing_officer", "director", all_divisions=True)
    po = raise_po(both, sdd, masterbatch)
    orders.submit(both, po)
    with pytest.raises(PurchasingError):
        orders.approve(both, po)


def test_a_returned_po_is_a_draft_again(draft, buyer, director):
    orders.submit(buyer, draft)
    with pytest.raises(PurchasingError):
        orders.send_back(director, draft, "")
    po = orders.send_back(director, draft, "Ask for a better price")
    assert po.status == St.DRAFT and orders.can_edit(buyer, po)


# --- After approval: never changed; revised, cancelled or closed ----------------------------


def test_an_approved_po_never_changes(approved, buyer, masterbatch):
    with pytest.raises(PurchasingError, match="Only the person who raised a draft"):
        orders.save(buyer, approved, lines=[LineInput(masterbatch, "1", "1")])
    with pytest.raises(DatabaseError, match="cannot be changed"), transaction.atomic():
        PurchaseOrder.objects.filter(pk=approved.pk).update(total_amount=Decimal("1"))
    with pytest.raises(DatabaseError, match="cannot change"), transaction.atomic():
        PurchaseOrderLine.objects.filter(order=approved).update(unit_price=Decimal("1"))
    with pytest.raises(DatabaseError, match="cannot"), transaction.atomic():
        PurchaseOrder.objects.filter(pk=approved.pk).delete()
    # Goods receipts (P16-06) may record what arrived.
    PurchaseOrderLine.objects.filter(order=approved).update(received_quantity=Decimal("100"))


def test_a_revision_replaces_the_po_and_is_approved_again(approved, buyer, director):
    with pytest.raises(PurchasingError, match="reason"):
        orders.revise(buyer, approved, "")
    rev = orders.revise(buyer, approved, "Supplier raised the price")
    approved.refresh_from_db()
    assert approved.status == St.REVISED
    assert (rev.number, rev.revision, rev.label, rev.status) == (
        approved.number,
        1,
        f"{approved.number} Rev 1",
        St.DRAFT,
    )
    assert rev.lines.get().quantity == 300
    with pytest.raises(DatabaseError, match="for good"), transaction.atomic():
        PurchaseOrder.objects.filter(pk=approved.pk).update(status=St.APPROVED)


def test_cancel_before_receipt_close_short_after(approved, buyer):
    with pytest.raises(PurchasingError, match="Only a partly received"):
        orders.close(buyer, approved, "Rest not needed")
    PurchaseOrderLine.objects.filter(order=approved).update(received_quantity=Decimal("100"))
    PurchaseOrder.objects.filter(pk=approved.pk).update(status=St.PARTLY_RECEIVED)
    approved.refresh_from_db()
    with pytest.raises(PurchasingError, match="closed short instead"):
        orders.cancel(buyer, approved, "Changed our mind")
    with pytest.raises(PurchasingError, match="nothing received"):
        orders.revise(buyer, approved, "New price")
    closed = orders.close(buyer, approved, "Supplier out of stock")
    assert (closed.status, closed.end_reason) == (St.CLOSED, "Supplier out of stock")


def test_a_draft_or_approved_po_is_cancelled_with_a_reason(approved, buyer, sdd, masterbatch):
    with pytest.raises(PurchasingError, match="reason"):
        orders.cancel(buyer, approved, " ")
    assert orders.cancel(buyer, approved, "Order placed elsewhere").status == St.CANCELLED
    draft = raise_po(buyer, sdd, masterbatch)
    assert orders.cancel(buyer, draft, "Duplicate").status == St.CANCELLED


# --- Through the API -----------------------------------------------------------------------


def test_the_api_raises_sends_and_approves(buyer, director, sdd, masterbatch):
    client = as_user(buyer)
    made = client.post(
        "/api/v1/purchase-orders/",
        {
            "supplier": sdd.pk,
            "division": "IM",
            "delivery_date": str(TODAY + timedelta(days=7)),
            "pay_mode": "online",
            "lines": [{"item": masterbatch.pk, "quantity": "300", "unit_price": "590.00"}],
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    po = made.json()
    assert po["total_amount"] == "177000.00" and po["can_edit"]
    url = f"/api/v1/purchase-orders/{po['id']}/"
    sent = client.post(f"{url}submit/", {}, format="json").json()
    assert sent["status"] == "awaiting_approval"
    assert client.post(f"{url}approve/", {}, format="json").status_code == 403
    boss = as_user(director)
    waiting = boss.get("/api/v1/purchase-orders/?waiting=me").json()
    assert [w["id"] for w in waiting] == [po["id"]]
    done = boss.post(f"{url}approve/", {"comment": "OK"}, format="json").json()
    assert done["status"] == "approved" and not done["can_approve"]
    assert done["approval"]["history"][-1]["by"] == director.full_name
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).get("/api/v1/purchase-orders/").status_code == 403
