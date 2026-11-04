# ruff: noqa: F811 - the fixtures of test_export_invoices are imported and used by name
"""Invoice tracking (backlog P2-27; owner, 3 Nov 2026): the customer link in the emailed
invoice, its views, OnePay card links sent, and where the invoice stands."""

from datetime import timedelta

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.test import Client
from django.utils import timezone

from apps.sales import receipts, tracking
from apps.sales.models import CardPaymentLink, InvoiceView
from apps.sales.services import SalesError

from .test_access import as_user, person
from .test_export_invoices import (  # noqa: F401 - fixtures used by name
    accountant,
    buyer,
    cashier,
    director,
    executive,
    invoice,
    order,
    pay,
    setup,
    stores,
    usd_bank,
)

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def kinds(invoice):
    return [e["kind"] for e in tracking.history(invoice)["events"]]


def test_the_emailed_invoice_links_to_the_customer_page(invoice, accountant, usd_bank):
    message = as_user(accountant).get(f"/api/v1/tax-invoices/{invoice.pk}/email/").json()
    link = message["link"]
    assert link.startswith("http://testserver/api/v1/public/invoices/")
    assert message["body"].endswith(link)
    path = link.replace("http://testserver", "")
    page = Client().get(path)  # the customer: not signed in
    assert page.status_code == 200
    html = page.content.decode()
    assert invoice.number in html and "USD 2,500.00" in html
    assert usd_bank.account_number in html  # the dollar account for a transfer
    pdf = Client().get(path + "pdf/")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf"
    assert list(InvoiceView.objects.values_list("what", flat=True)) == ["page", "pdf"]
    h = tracking.history(invoice)
    assert h["viewed"] and "viewed" in kinds(invoice)
    assert any(e["text"] == "Viewed by the customer (2 times)" for e in h["events"])
    # The same link each time.
    again = as_user(accountant).get(f"/api/v1/tax-invoices/{invoice.pk}/email/").json()
    assert again["link"] == link


def test_an_unknown_link_shows_nothing(invoice):
    assert Client().get("/api/v1/public/invoices/not-a-real-token/").status_code == 404
    assert not InvoiceView.objects.exists()


def test_a_onepay_link_sent_is_recorded(invoice, accountant):
    with pytest.raises(SalesError, match="https://"):
        tracking.add_card_link(
            accountant, invoice, url="onepay.lk/pay/1", amount="2500", sent_on=TODAY
        )
    with pytest.raises(SalesError, match="to the cent"):
        tracking.add_card_link(
            accountant, invoice, url="https://onepay.lk/p/1", amount="0", sent_on=TODAY
        )
    with pytest.raises(SalesError, match="future"):
        tracking.add_card_link(
            accountant,
            invoice,
            url="https://onepay.lk/p/1",
            amount="2500",
            sent_on=TODAY + timedelta(days=1),
        )
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    with pytest.raises(SalesError, match="Sales or the Accountant"):
        tracking.add_card_link(
            clerk, invoice, url="https://onepay.lk/p/1", amount="1", sent_on=TODAY
        )
    done = as_user(accountant).post(
        f"/api/v1/tax-invoices/{invoice.pk}/card-links/",
        {"url": "https://onepay.lk/p/AB12", "amount": "2,500.00", "sent_on": TODAY.isoformat()},
        format="json",
    )
    assert done.status_code == 200, done.json()
    events = done.json()["tracking"]["events"]
    card = next(e for e in events if e["kind"] == "card_link")
    assert card["url"] == "https://onepay.lk/p/AB12" and "USD 2,500.00" in card["text"]
    with transaction.atomic(), pytest.raises(DatabaseError):
        CardPaymentLink.objects.update(amount=1)


def test_where_the_invoice_stands(invoice, cashier, accountant, usd_bank):
    assert tracking.history(invoice)["state"] in ("open", "overdue")
    receipts.approve(accountant, pay(cashier, usd_bank, invoice, "1000.00"))
    assert tracking.history(invoice)["state"] == "partly_paid"
    receipts.approve(accountant, pay(cashier, usd_bank, invoice, "1500.00"))
    h = tracking.history(invoice)
    assert h["state"] == "paid" and kinds(invoice).count("paid") == 2
    assert "issued" in kinds(invoice)
