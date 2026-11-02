"""Foreign-currency purchases at each transaction date's rate (backlog P16-19, IAS 21)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core.models import Division
from apps.inventory import items, receipts, stock
from apps.inventory.models import StockMovement
from apps.masters import currencies
from apps.masters.models import Currency, Supplier
from apps.purchasing import invoices, orders
from apps.purchasing.invoices import LineInput
from apps.purchasing.orders import LineInput as POLine

from .test_access import person

pytestmark = pytest.mark.django_db

DAY0 = timezone.localdate()
PDF = b"%PDF-1.4\n" + b"0" * 64


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def people():
    return {
        "buyer": person("buyer@sml.lk", "purchasing_officer", all_divisions=True),
        "stores": person("stores@sml.lk", "store_supervisor", all_divisions=True),
        "clerk": person("clerk@sml.lk", "clerk", all_divisions=True),
        "director": person("director@sml.lk", "director", all_divisions=True),
    }


def usd():
    return Currency.objects.get(code="USD")


def on(monkeypatch, days, rate):
    """Move to DAY0 + days, with the USD rate of that day."""
    day = DAY0 + timedelta(days=days)
    monkeypatch.setattr(timezone, "localdate", lambda *a: day)
    currencies.set_rate(currency=usd(), on_date=day, rate=rate)
    return day


def lines_of(entry):
    return {
        (row.account.system_role or row.account.number, row.debit, row.credit)
        for row in entry.lines.select_related("account")
    }


def purchase(people, monkeypatch, invoice_rate):
    """100 dies at USD 10.00: ordered at 300, received at 305, invoiced at `invoice_rate`."""
    supplier = Supplier.objects.create(code="S0009", name="Dies Inc", currency=usd())
    item = items.create_item(
        people["buyer"],
        {
            "code": "DIE-1",
            "name": "Die",
            "category": "spare",
            "unit": "pcs",
            "inspection_required": False,
        },
    )
    on(monkeypatch, 0, "300")
    order = orders.create(
        people["buyer"],
        supplier=supplier,
        division=Division.objects.get(code="WS"),
        delivery_date=DAY0 + timedelta(days=3),
        lines=[POLine(item, "100", "10.00")],
    )
    orders.submit(people["buyer"], order)
    order = orders.approve(people["director"], order)
    on(monkeypatch, 1, "305")
    grn = receipts.confirm(people["stores"], receipts.create(people["stores"], order))
    on(monkeypatch, 2, invoice_rate)
    line = grn.lines.get()
    made = invoices.create(
        people["clerk"],
        supplier=supplier,
        division=grn.division,
        invoice_no="D-1",
        lines=[LineInput(line.pk, "100", "10.00")],
    )
    made = invoices.save(
        people["clerk"], made, stated_total="1000.00", lines=[LineInput(line.pk, "100", "10.00")]
    )
    invoices.add_attachment(people["clerk"], made, SimpleUploadedFile("d.pdf", PDF))
    return order, grn, invoices.match(people["clerk"], made)


def test_goods_at_the_receipt_rate_and_the_invoice_at_its_own(people, monkeypatch):
    order, grn, invoice = purchase(people, monkeypatch, "310")
    assert order.exchange_rate == Decimal("300")
    assert (grn.exchange_rate, grn.rate_date) == (Decimal("305"), DAY0 + timedelta(days=1))
    # Into stock at the receipt date's rate.
    moves = StockMovement.objects.filter(store__kind="main")
    assert sum(m.value for m in moves) == Decimal("305000.00")
    assert stock.average_costs(StockMovement.objects.all())[grn.lines.get().item_id] == Decimal(
        "3050.0000"
    )
    # The invoice: GRNI cleared at 305, payable at 310, the 5,000 an exchange loss.
    assert invoice.status == "posted"
    assert (invoice.exchange_rate, invoice.total_lkr) == (Decimal("310"), Decimal("310000.00"))
    assert lines_of(invoice.journal_entry) == {
        ("grni", Decimal("305000.00"), Decimal("0")),
        ("exchange_loss", Decimal("5000.00"), Decimal("0")),
        ("accounts_payable", Decimal("0"), Decimal("310000.00")),
    }


def test_a_lower_rate_on_the_invoice_is_an_exchange_gain(people, monkeypatch):
    _, _, invoice = purchase(people, monkeypatch, "302")
    assert lines_of(invoice.journal_entry) == {
        ("grni", Decimal("305000.00"), Decimal("0")),
        ("exchange_gain", Decimal("0"), Decimal("3000.00")),
        ("accounts_payable", Decimal("0"), Decimal("302000.00")),
    }


def test_the_receipt_date_rate_is_used_even_when_confirmed_later(people, monkeypatch):
    supplier = Supplier.objects.create(code="S0010", name="Dies Ltd", currency=usd())
    item = items.create_item(
        people["buyer"], {"code": "DIE-2", "name": "Die", "category": "spare", "unit": "pcs"}
    )
    on(monkeypatch, 0, "300")
    order = orders.create(
        people["buyer"],
        supplier=supplier,
        division=Division.objects.get(code="WS"),
        delivery_date=DAY0 + timedelta(days=3),
        lines=[POLine(item, "1", "10.00")],
    )
    orders.submit(people["buyer"], order)
    order = orders.approve(people["director"], order)
    grn = receipts.create(people["stores"], order)
    # Confirmed four days later: the rate of the receipt date (DAY0) still applies.
    monkeypatch.setattr(timezone, "localdate", lambda *a: DAY0 + timedelta(days=4))
    confirmed = receipts.confirm(people["stores"], grn)
    assert (confirmed.exchange_rate, confirmed.rate_date) == (Decimal("300"), DAY0)


def test_lkr_purchases_are_unchanged(people):
    supplier = Supplier.objects.create(
        code="S0011", name="Local", currency=Currency.objects.get(code="LKR")
    )
    item = items.create_item(
        people["buyer"],
        {
            "code": "LOC-1",
            "name": "Local part",
            "category": "spare",
            "unit": "pcs",
            "inspection_required": False,
        },
    )
    order = orders.create(
        people["buyer"],
        supplier=supplier,
        division=Division.objects.get(code="WS"),
        delivery_date=DAY0 + timedelta(days=3),
        lines=[POLine(item, "10", "100.00")],
    )
    orders.submit(people["buyer"], order)
    order = orders.approve(people["director"], order)
    grn = receipts.confirm(people["stores"], receipts.create(people["stores"], order))
    assert grn.exchange_rate == Decimal("1")
