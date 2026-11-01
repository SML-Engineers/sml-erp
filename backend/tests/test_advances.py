"""Advance payments on a purchase order (backlog P16-11a, spec 5A.5)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import services as chart
from apps.accounting.models import DetailType, JournalEntry
from apps.core.models import Division
from apps.inventory import items, receipts
from apps.masters import banking
from apps.masters.models import Currency, Supplier
from apps.payments import services as payments
from apps.purchasing import advances, invoices, orders
from apps.purchasing.advances import AdvanceError
from apps.purchasing.invoices import LineInput
from apps.purchasing.models import AdvanceSetOff, PurchaseOrder
from apps.purchasing.orders import LineInput as POLine
from apps.vouchers import services
from apps.vouchers.models import Voucher, VoucherLine, VoucherType
from apps.vouchers.services import VoucherError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
PDF = b"%PDF-1.4\n" + b"0" * 64


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def clerk():
    return person("clerk@sml.lk", "clerk", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def cashier():
    return person("cashier@sml.lk", "cashier", all_divisions=True)


@pytest.fixture
def buyer():
    return person("buyer@sml.lk", "purchasing_officer", all_divisions=True)


@pytest.fixture
def stores():
    return person("stores@sml.lk", "store_supervisor", divisions=("IM",))


@pytest.fixture
def bank(accountant):
    ledger = chart.create_account(
        accountant,
        name="Commercial Bank current",
        account_type="bank",
        detail_type=DetailType.objects.get(name="Current account"),
        number="1030",
    )
    account = banking.create_account(
        accountant,
        code="com-cur",
        kind="current",
        name="Commercial Bank current",
        bank_name="Commercial Bank",
        account_number="1000234567",
        ledger_account=ledger.pk,
    )
    banking.add_cheque_book(accountant, account, first=100, last=150)
    return account


@pytest.fixture
def supplier():
    return Supplier.objects.create(
        code="S0001", name="Moulds Lanka", currency=Currency.objects.get(code="LKR")
    )


def im():
    return Division.objects.get(code="IM")


@pytest.fixture
def order(buyer, director, supplier):
    """An approved PO: 100 inserts at LKR 100 = 10,000.00."""
    item = items.create_item(
        buyer,
        {
            "code": "M8-INSERT",
            "name": "Insert",
            "category": "bought_out",
            "unit": "pcs",
            "inspection_required": False,
        },
    )
    po = orders.create(
        buyer,
        supplier=supplier,
        division=im(),
        delivery_date=TODAY + timedelta(days=7),
        lines=[POLine(item, "100", "100")],
    )
    orders.submit(buyer, po)
    return orders.approve(director, po)


def advance(clerk, supplier, order, amount="3000.00", reason="Supplier asks 30% to start"):
    voucher = services.save(
        clerk,
        None,
        voucher_type=VoucherType.objects.get(code="CHQ"),
        division=im(),
        payee=supplier,
        description="Advance",
        lines=[services.LineInput(amount=amount, description=reason, advance_order=order)],
    )
    services.add_attachment(clerk, voucher, SimpleUploadedFile("proforma.pdf", PDF))
    return voucher


def approve_and_pay(clerk, accountant, director, cashier, bank, voucher):
    services.submit(clerk, voucher)
    services.approve(accountant, voucher)
    services.approve(director, voucher)
    voucher = Voucher.objects.get(pk=voucher.pk)
    return payments.record(
        cashier,
        voucher,
        account=bank,
        method="cheque",
        amount=str(voucher.total_amount),
        payment_date=TODAY,
    )


def invoice_goods(clerk, stores, order, no="INV-1"):
    line = receipts.confirm(stores, receipts.create(stores, order)).lines.get()
    invoice = invoices.create(
        clerk,
        supplier=order.supplier,
        division=im(),
        invoice_no=no,
        invoice_date=TODAY,
        lines=[LineInput(line.pk, "100", "100")],
    )
    invoice = invoices.save(
        clerk, invoice, stated_total="10000", lines=[LineInput(line.pk, "100", "100")]
    )
    invoices.add_attachment(clerk, invoice, SimpleUploadedFile("inv.pdf", PDF))
    return invoices.match(clerk, invoice)


# --- The advance --------------------------------------------------------------------------------


def test_an_advance_is_coded_to_advances_to_suppliers(clerk, supplier, order):
    voucher = advance(clerk, supplier, order)
    line = voucher.lines.get()
    assert line.account.system_role == "supplier_advances" and line.account.number == "1320"
    assert line.advance_order == order and line.tax_amount == 0
    assert line.description == f"Advance on PO {order.label}: Supplier asks 30% to start"


def test_the_advances_on_a_po_never_exceed_it(clerk, supplier, order):
    advance(clerk, supplier, order, "6000.00")
    with pytest.raises(VoucherError, match="more than the 4,000.00 of purchase order"):
        advance(clerk, supplier, order, "4000.01")
    voucher = advance(clerk, supplier, order, "4000.00")
    with pytest.raises(DatabaseError, match="more than the order"), transaction.atomic():
        VoucherLine.objects.create(
            voucher=voucher, line_no=2, amount=Decimal("0.01"), advance_order=order
        )


def test_an_advance_needs_a_reason_and_an_open_po_of_the_payee(clerk, supplier, order):
    with pytest.raises(VoucherError, match="say why"):
        advance(clerk, supplier, order, reason=" ")
    other = Supplier.objects.create(
        code="S0002", name="Other", currency=Currency.objects.get(code="LKR")
    )
    with pytest.raises(VoucherError, match="another supplier"):
        advance(clerk, other, order)
    PurchaseOrder.objects.filter(pk=order.pk).update(status="received")
    order.refresh_from_db()
    with pytest.raises(VoucherError, match="still waiting for goods"):
        advance(clerk, supplier, order)


# --- Setting it off -----------------------------------------------------------------------------


def test_a_paid_advance_is_set_off_when_the_invoice_is_posted(
    clerk, accountant, director, cashier, bank, stores, supplier, order
):
    payment = approve_and_pay(
        clerk, accountant, director, cashier, bank, advance(clerk, supplier, order)
    )
    debit = payment.journal_entry.lines.get(debit__gt=0)
    assert debit.account.system_role == "supplier_advances"
    invoice = invoice_goods(clerk, stores, order)
    set_off = AdvanceSetOff.objects.get(invoice=invoice)
    assert set_off.amount == Decimal("3000.00")
    lines = {
        (row.account.system_role, row.debit, row.credit)
        for row in set_off.journal_entry.lines.select_related("account")
    }
    assert lines == {
        ("accounts_payable", Decimal("3000.00"), Decimal("0")),
        ("supplier_advances", Decimal("0"), Decimal("3000.00")),
    }
    assert invoices.unpaid(invoice) == Decimal("7000.00")
    with pytest.raises(VoucherError, match="more than the 7,000.00 still unpaid"):
        services.save(
            clerk,
            None,
            voucher_type=VoucherType.objects.get(code="CHQ"),
            division=im(),
            payee=supplier,
            lines=[services.LineInput(amount="7000.01", supplier_invoice=invoice)],
        )


def test_an_unpaid_advance_waits_and_is_set_off_later(
    clerk, accountant, director, cashier, bank, stores, supplier, order
):
    voucher = advance(clerk, supplier, order)
    invoice = invoice_goods(clerk, stores, order)
    assert not AdvanceSetOff.objects.exists()  # not paid yet
    with pytest.raises(AdvanceError, match="no paid advance"):
        advances.set_off_later(accountant, invoice)
    approve_and_pay(clerk, accountant, director, cashier, bank, voucher)
    with pytest.raises(AdvanceError, match="Accountant"):
        advances.set_off_later(clerk, invoice)
    client = as_user(accountant)
    detail = client.get(f"/api/v1/supplier-invoices/{invoice.pk}/").json()
    assert detail["advances_waiting"] == "3000.00" and detail["can_set_off"]
    done = client.post(f"/api/v1/supplier-invoices/{invoice.pk}/set-off/", {}, format="json")
    assert done.status_code == 200, done.json()
    assert done.json()["unpaid"] == "7000.00" and done.json()["set_offs"][0]["amount"] == "3000.00"
    assert JournalEntry.objects.filter(source_type="advance_set_off").count() == 1


def test_set_offs_never_change(clerk, accountant, director, cashier, bank, stores, supplier, order):
    approve_and_pay(clerk, accountant, director, cashier, bank, advance(clerk, supplier, order))
    invoice_goods(clerk, stores, order)
    with pytest.raises(DatabaseError, match="never changed"), transaction.atomic():
        AdvanceSetOff.objects.update(amount=Decimal("1"))


def test_the_clerk_sees_pos_open_for_an_advance(clerk, supplier, order):
    advance(clerk, supplier, order, "2500.00")
    rows = (
        as_user(clerk)
        .get(f"/api/v1/supplier-invoices/advance-orders/?supplier={supplier.pk}&division=IM")
        .json()
    )
    assert [(r["label"], r["advanced"], r["left"]) for r in rows] == [
        (order.label, "2500.00", "7500.00")
    ]
