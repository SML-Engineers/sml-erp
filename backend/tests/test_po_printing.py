"""Printing and emailing purchase orders (backlog P16-05), in the layout of the owner's
sample PO26061701."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import TaxCode, TaxComponent
from apps.core import document_email
from apps.core.models import Company
from apps.inventory import items
from apps.masters.models import Currency, Supplier
from apps.purchasing import emails, orders, printing
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.orders import LineInput, PurchasingError

from .test_access import as_user, person
from .test_purchase_orders import im

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


@pytest.fixture
def buyer():
    return person("buyer@sml.lk", "purchasing_officer", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def po(buyer):
    accountant = person("accountant@sml.lk", "accountant", all_divisions=True)
    taxes.add_rate(
        accountant,
        TaxComponent.objects.get(code="VAT"),
        effective_from=TODAY - timedelta(days=400),
        rate="18",
    )
    sdd = Supplier.objects.create(
        code="S0001",
        name="SDD Polymer (Pvt) Ltd",
        address="608-1/1, Dr. Danister De Silva Mawatha,\nColombo 9",
        email="sales@sddpolymer.lk",
        currency=Currency.objects.get(code="LKR"),
        payment_terms_days=30,
    )
    black = items.create_item(
        buyer,
        {
            "code": "48/bl/08",
            "name": "Black MB - 45% Carbon Black - 48/BL/08",
            "category": "raw_material",
            "unit": "kg",
        },
    )
    return orders.create(
        buyer,
        supplier=sdd,
        division=im(),
        lines=[LineInput(black, "300", "590", TaxCode.objects.get(code="VAT"))],
        delivery_date=TODAY + timedelta(days=7),
    )


@pytest.fixture
def approved(po, buyer, director):
    orders.submit(buyer, po)
    return orders.approve(director, po)


def text(order) -> bytes:
    pdf = printing.render(PurchaseOrder.objects.get(pk=order.pk), compress=False)
    return pdf.replace(b"\\(", b"(").replace(b"\\)", b")")


def test_item_codes_can_have_slashes_like_the_owners(po):
    assert po.lines.get().item.code == "48/BL/08"


def test_the_po_prints_like_the_owners_sample(approved):
    Company.objects.filter(pk=1).update(name="SML Engineers & Manufacturers (Pvt) Ltd")
    pdf = text(approved)
    for words in (
        b"PURCHASE ORDER",
        b"SDD Polymer (Pvt) Ltd",
        b"P.O. No.",
        approved.number.encode(),
        b"Pay Mode",
        b"Online",
        b"Net 30",
        b"Delivery Date",
        b"Deliver to:",
        b"48/BL/08",
        b"Black MB - 45% Carbon Black",
        b"177,000.00",
        b"Grand Total",
        b"LKR 208,860.00",
        b"VAT Total (18%)",
        b"LKR 31,860.00",
        b"Please indicate our P.O. No",
        b"Payment will be made strictly up to the quantity",
        b"Yours Faithfully",
        b"Managing Director",
        b"Checked By",
    ):
        assert words in pdf, words
    assert b"DRAFT" not in pdf


def test_a_po_not_approved_is_marked_draft(po):
    assert b"NOT APPROVED" in text(po)


def test_only_an_approved_po_is_emailed_by_the_buyer(po, buyer, director):
    document_email.update_account(
        person("admin@sml.lk", "system_admin", all_divisions=True),
        {
            "from_address": "purchasing@smlengineers.lk",
            "host": "smtp.hostinger.com",
            "port": 465,
            "security": "ssl",
            "username": "purchasing@smlengineers.lk",
            "password": "Mailbox-Secret-1",
        },
        reason="go-live",
    )
    with pytest.raises(PurchasingError, match="Only an approved"):
        emails.draft(buyer, po)
    orders.submit(buyer, po)
    approved = orders.approve(director, po)
    with pytest.raises(PurchasingError, match="Purchasing Officer"):
        emails.draft(director, approved)
    message = emails.draft(buyer, approved)
    assert message["to"] == ["sales@sddpolymer.lk"]
    assert approved.number in message["subject"]
    record = emails.send(
        buyer, approved, to=message["to"], subject=message["subject"], body=message["body"]
    )
    assert record.status == "sent"
    (sent,) = mail.outbox
    assert sent.attachments[0][0] == f"PO-{approved.number}.pdf"
    assert sent.attachments[0][1].startswith(b"%PDF")
    assert emails.history(approved)[0]["to"] == "sales@sddpolymer.lk"


def test_the_api_prints_and_emails(approved, buyer):
    client = as_user(buyer)
    pdf = client.get(f"/api/v1/purchase-orders/{approved.pk}/pdf/")
    assert pdf["Content-Type"] == "application/pdf"
    assert f"PO-{approved.number}.pdf" in pdf["Content-Disposition"]
    detail = client.get(f"/api/v1/purchase-orders/{approved.pk}/").json()
    assert detail["can_email"] is True and detail["emails"] == []
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).get(f"/api/v1/purchase-orders/{approved.pk}/pdf/").status_code == 403
