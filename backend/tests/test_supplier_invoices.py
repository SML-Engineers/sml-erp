"""Supplier invoices and the three-way match (backlog P16-10, spec 5A.4)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import TaxCode, TaxComponent
from apps.core.models import Division, Notification
from apps.inventory import items, receipts
from apps.masters.models import Currency, Supplier
from apps.purchasing import invoices, orders
from apps.purchasing.invoices import InvoiceError, LineInput
from apps.purchasing.models import SupplierInvoice, SupplierInvoiceLine
from apps.purchasing.orders import LineInput as POLine
from apps.vouchers import services as vouchers
from apps.vouchers.models import VoucherType
from apps.vouchers.services import VoucherError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
PDF = b"%PDF-1.4\n" + b"0" * 64
St = SupplierInvoice.Status


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
def clerk():
    return person("clerk@sml.lk", "clerk", divisions=("IM",))


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def supplier():
    return Supplier.objects.create(
        code="S0001",
        name="Fasteners Lanka",
        currency=Currency.objects.get(code="LKR"),
        payment_terms_days=45,
    )


@pytest.fixture
def inserts(buyer):
    return items.create_item(
        buyer,
        {
            "code": "M6-INSERT",
            "name": "Brass insert M6",
            "category": "bought_out",
            "unit": "pcs",
            "inspection_required": False,
        },
    )


@pytest.fixture
def vat(accountant):
    taxes.add_rate(
        accountant,
        TaxComponent.objects.get(code="VAT"),
        effective_from=TODAY - timedelta(days=400),
        rate="18",
    )
    return TaxCode.objects.get(code="VAT")


def received(buyer, director, stores, supplier, item, qty="1000", price="12.50", tax=None):
    """A GRN line of accepted goods (the item needs no QC, so it is accepted on confirming)."""
    order = orders.create(
        buyer,
        supplier=supplier,
        division=Division.objects.get(code="IM"),
        delivery_date=TODAY + timedelta(days=7),
        lines=[POLine(item, qty, price, tax)],
    )
    orders.submit(buyer, order)
    orders.approve(director, order)
    return receipts.confirm(stores, receipts.create(stores, order)).lines.get()


@pytest.fixture
def grn_line(buyer, director, stores, supplier, inserts):
    return received(buyer, director, stores, supplier, inserts)


def enter(clerk, supplier, grn_line, qty="1000", price="12.50", tax=None, total=None, no="INV-77"):
    invoice = invoices.create(
        clerk,
        supplier=supplier,
        division=Division.objects.get(code="IM"),
        invoice_no=no,
        invoice_date=TODAY,
        lines=[LineInput(grn_line.pk, qty, price, tax)],
    )
    if total is None:
        total = invoice.total_amount
    invoice = invoices.save(
        clerk,
        invoice,
        invoice_no=no,
        stated_total=str(total),
        lines=[LineInput(grn_line.pk, qty, price, tax)],
    )
    invoices.add_attachment(clerk, invoice, SimpleUploadedFile("inv.pdf", PDF))
    return invoice


def lines_of(entry):
    return {
        (row.account.system_role or row.account.number, row.debit, row.credit)
        for row in entry.lines.select_related("account")
    }


# --- Entering ----------------------------------------------------------------------------------


def test_the_clerk_sees_accepted_goods_not_yet_invoiced(clerk, supplier, grn_line):
    rows = invoices.open_lines(clerk, supplier, Division.objects.get(code="IM"))
    assert [(r["line"], r["open"]) for r in rows] == [(grn_line, Decimal("1000.000"))]


def test_a_matching_invoice_is_posted_at_once(clerk, supplier, grn_line):
    invoice = enter(clerk, supplier, grn_line)
    assert invoice.number == f"SI{TODAY:%y%m%d}01"
    assert invoice.due_date == TODAY + timedelta(days=45)
    invoice = invoices.match(clerk, invoice)
    assert (invoice.status, invoice.discrepancies, invoice.total_lkr) == (
        St.POSTED,
        [],
        Decimal("12500.00"),
    )
    assert lines_of(invoice.journal_entry) == {
        ("grni", Decimal("12500.00"), Decimal("0")),
        ("accounts_payable", Decimal("0"), Decimal("12500.00")),
    }
    assert invoice.journal_entry.lines.get(credit__gt=0).supplier == supplier
    assert invoices.open_lines(clerk, supplier, Division.objects.get(code="IM")) == []


def test_vat_on_the_invoice_goes_to_vat_input(
    buyer, director, stores, clerk, supplier, inserts, vat
):
    line = received(buyer, director, stores, supplier, inserts, tax=vat)
    invoice = invoices.match(clerk, enter(clerk, supplier, line, tax=vat))
    assert invoice.status == St.POSTED and invoice.total_amount == Decimal("14750.00")
    assert lines_of(invoice.journal_entry) == {
        ("grni", Decimal("12500.00"), Decimal("0")),
        ("vat_receivable", Decimal("2250.00"), Decimal("0")),
        ("accounts_payable", Decimal("0"), Decimal("14750.00")),
    }


def test_matching_needs_the_scan_and_the_printed_total(clerk, supplier, grn_line):
    invoice = invoices.create(
        clerk,
        supplier=supplier,
        division=Division.objects.get(code="IM"),
        invoice_no="INV-1",
        invoice_date=TODAY,
        lines=[LineInput(grn_line.pk, "10", "12.50")],
    )
    with pytest.raises(InvoiceError, match="total printed"):
        invoices.match(clerk, invoice)
    invoices.save(clerk, invoice, stated_total="125", lines=[LineInput(grn_line.pk, "10", "12.50")])
    with pytest.raises(InvoiceError, match="scanned invoice"):
        invoices.match(clerk, invoice)


# --- Differences -------------------------------------------------------------------------------


def test_more_than_accepted_can_never_be_invoiced(clerk, supplier, grn_line):
    invoice = enter(clerk, supplier, grn_line, qty="1001")
    with pytest.raises(InvoiceError, match="only 1000 accepted by QC and not yet invoiced"):
        invoices.match(clerk, invoice)


def test_goods_not_yet_accepted_by_qc_cannot_be_invoiced(buyer, director, stores, clerk, supplier):
    resin = items.create_item(
        buyer, {"code": "PP-1", "name": "PP", "category": "raw_material", "unit": "kg"}
    )
    line = received(buyer, director, stores, supplier, resin, qty="100", price="420")
    assert invoices.open_lines(clerk, supplier, Division.objects.get(code="IM")) == []
    invoice = enter(clerk, supplier, line, qty="100", price="420")
    with pytest.raises(InvoiceError, match="only 0 accepted"):
        invoices.match(clerk, invoice)


def test_the_same_goods_cannot_be_invoiced_twice(clerk, supplier, grn_line):
    invoices.match(clerk, enter(clerk, supplier, grn_line, qty="600"))
    second = enter(clerk, supplier, grn_line, qty="500", no="INV-78")
    with pytest.raises(InvoiceError, match="only 400 accepted"):
        invoices.match(clerk, second)
    third = enter(clerk, supplier, grn_line, qty="400", no="INV-79")
    assert invoices.match(clerk, third).status == St.POSTED


def test_a_price_difference_is_held_and_the_director_approves_it(
    clerk, accountant, director, supplier, grn_line
):
    invoice = invoices.match(clerk, enter(clerk, supplier, grn_line, price="13.00"))
    assert invoice.status == St.HELD
    assert invoice.discrepancies == [
        f"Line 1 (M6-INSERT, {grn_line.receipt.number}): price 13.00, PO price 12.50."
    ]
    assert invoice.journal_entry is None
    with pytest.raises(InvoiceError, match="Accountant"):
        invoices.request_exception(clerk, invoice, "Agreed")
    with pytest.raises(InvoiceError, match="reason"):
        invoices.request_exception(accountant, invoice, "")
    invoice = invoices.request_exception(accountant, invoice, "Brass price rose; agreed by phone")
    assert invoice.status == St.EXCEPTION_REQUESTED
    assert Notification.objects.filter(user=director, event="approval_waiting").exists()
    with pytest.raises(InvoiceError):
        invoices.approve_exception(accountant, invoice)  # never the one who asked
    invoice = invoices.approve_exception(director, invoice, "OK this once")
    assert invoice.status == St.POSTED
    assert lines_of(invoice.journal_entry) == {
        ("grni", Decimal("12500.00"), Decimal("0")),  # stock stays at the PO price
        ("price_variance", Decimal("500.00"), Decimal("0")),
        ("accounts_payable", Decimal("0"), Decimal("13000.00")),
    }


def test_a_lower_price_is_a_credit_to_the_variance(clerk, accountant, director, supplier, grn_line):
    invoice = invoices.match(clerk, enter(clerk, supplier, grn_line, price="12.00"))
    invoices.request_exception(accountant, invoice, "Discount given")
    invoice = invoices.approve_exception(director, invoice)
    assert ("price_variance", Decimal("0"), Decimal("500.00")) in lines_of(invoice.journal_entry)


def test_a_different_printed_total_or_tax_is_held(clerk, supplier, grn_line, vat):
    invoice = invoices.match(clerk, enter(clerk, supplier, grn_line, total="12600", tax=vat))
    assert invoice.status == St.HELD
    assert invoice.discrepancies[0].endswith("tax VAT, PO tax no tax.")
    assert (
        invoice.discrepancies[1] == "Total printed on the invoice 12,600.00, worked out 14,750.00."
    )


def test_a_held_invoice_is_corrected_or_cancelled(clerk, director, accountant, supplier, grn_line):
    invoice = invoices.match(clerk, enter(clerk, supplier, grn_line, price="13.00"))
    invoice = invoices.back_to_draft(clerk, invoice)  # typing mistake
    invoices.save(
        clerk, invoice, stated_total="12500", lines=[LineInput(grn_line.pk, "1000", "12.50")]
    )
    assert invoices.match(clerk, invoice).status == St.POSTED


def test_the_director_sends_an_exception_back(clerk, accountant, director, supplier, grn_line):
    invoice = invoices.match(clerk, enter(clerk, supplier, grn_line, price="13.00"))
    invoices.request_exception(accountant, invoice, "Please approve")
    invoice = invoices.send_back(director, invoice, "Ask for a credit note")
    assert invoice.status == St.HELD
    with pytest.raises(InvoiceError, match="reason"):
        invoices.cancel(clerk, invoice, "")
    invoice = invoices.cancel(clerk, invoice, "Supplier sends a new invoice")
    assert invoice.status == St.CANCELLED
    again = enter(clerk, supplier, grn_line)  # the number is free again
    assert invoices.match(clerk, again).status == St.POSTED


# --- Duplicates and guards ---------------------------------------------------------------------


def test_the_same_invoice_number_is_refused(clerk, supplier, grn_line):
    enter(clerk, supplier, grn_line, qty="1", no="INV-77")
    with pytest.raises(InvoiceError, match="cannot be entered twice"):
        enter(clerk, supplier, grn_line, qty="1", no="inv 77")
    with pytest.raises(DatabaseError, match="already on supplier invoice"), transaction.atomic():
        first = SupplierInvoice.objects.get()
        SupplierInvoice.objects.create(
            number="X",
            supplier=supplier,
            division=first.division,
            invoice_no="INV77",
            invoice_date=TODAY,
            due_date=TODAY,
            currency=first.currency,
            created_by=clerk,
        )


def test_a_voucher_cannot_repeat_an_entered_supplier_invoice(clerk, supplier, grn_line):
    entered = enter(clerk, supplier, grn_line, qty="1", no="INV-77")
    with pytest.raises(VoucherError, match=f"already entered as supplier invoice {entered.number}"):
        vouchers.save(
            clerk,
            None,
            voucher_type=VoucherType.objects.get(code="CHQ"),
            division=Division.objects.get(code="IM"),
            payee=supplier,
            description="Inserts",
            lines=[vouchers.LineInput(amount="10.00", invoice_no="inv77")],
        )


def test_a_posted_invoice_never_changes(clerk, supplier, grn_line):
    invoice = invoices.match(clerk, enter(clerk, supplier, grn_line))
    with pytest.raises(InvoiceError):
        invoices.save(clerk, invoice, lines=[LineInput(grn_line.pk, "1", "1")])
    with pytest.raises(DatabaseError, match="cannot be changed"), transaction.atomic():
        SupplierInvoice.objects.filter(pk=invoice.pk).update(notes="x")
    with pytest.raises(DatabaseError, match="cannot change"), transaction.atomic():
        SupplierInvoiceLine.objects.filter(invoice=invoice).update(quantity=Decimal("1"))


def test_only_accounts_enter_invoices(buyer, stores, supplier, grn_line):
    for user in (buyer, stores):
        with pytest.raises(InvoiceError, match="Only Accounts"):
            enter(user, supplier, grn_line)


# --- Through the API -------------------------------------------------------------------------


def test_the_api_enters_matches_and_posts(clerk, supplier, grn_line):
    client = as_user(clerk)
    open_lines = client.get(
        f"/api/v1/supplier-invoices/open-lines/?supplier={supplier.pk}&division=IM"
    ).json()
    assert [(r["grn_line"], r["open_quantity"], r["po_unit_price"]) for r in open_lines] == [
        (grn_line.pk, "1000.000", "12.50")
    ]
    made = client.post(
        "/api/v1/supplier-invoices/",
        {
            "supplier": supplier.pk,
            "division": "IM",
            "invoice_no": "INV-77",
            "invoice_date": str(TODAY),
            "stated_total": "12500.00",
            "lines": [{"grn_line": grn_line.pk, "quantity": "1000", "unit_price": "12.50"}],
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    pk = made.json()["id"]
    scan = client.post(
        f"/api/v1/supplier-invoices/{pk}/attachments/",
        {"file": SimpleUploadedFile("inv.pdf", PDF)},
        format="multipart",
    )
    assert scan.status_code == 201
    matched = client.post(f"/api/v1/supplier-invoices/{pk}/match/", {}, format="json")
    assert matched.status_code == 200, matched.json()
    body = matched.json()
    assert body["status"] == "posted" and body["journal"]
    assert body["lines"][0]["accepted_quantity"] == "1000.000"


def test_people_without_vouchers_or_accounting_see_nothing(stores):
    assert as_user(stores).get("/api/v1/supplier-invoices/").status_code == 403
