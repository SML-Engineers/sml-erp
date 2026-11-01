"""Payment vouchers from matched supplier invoices (backlog P16-11, spec 5A.5)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting.models import Account
from apps.core.models import Division
from apps.inventory import items, receipts
from apps.masters.models import Currency, Supplier
from apps.payments.services import cost_pieces
from apps.purchasing import invoices, orders
from apps.purchasing.invoices import LineInput
from apps.purchasing.orders import LineInput as POLine
from apps.vouchers import services
from apps.vouchers.models import Voucher, VoucherLine, VoucherType
from apps.vouchers.services import CodingInput, VoucherError

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
    return person("clerk@sml.lk", "clerk", divisions=("IM",))


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def im():
    return Division.objects.get(code="IM")


def supplier_named(code, name):
    return Supplier.objects.create(
        code=code, name=name, currency=Currency.objects.get(code="LKR"), payment_terms_days=30
    )


@pytest.fixture
def supplier():
    return supplier_named("S0001", "Fasteners Lanka")


def posted_invoice(clerk, director, supplier, qty="1000", price="12.50", no="INV-77"):
    """Goods ordered, received, accepted (no QC needed) and invoiced: a posted invoice."""
    buyer = person(f"buyer-{no}@sml.lk", "purchasing_officer", all_divisions=True)
    stores = person(f"stores-{no}@sml.lk", "store_supervisor", divisions=("IM",))
    item = items.create_item(
        buyer,
        {
            "code": f"IT-{no}"[:20],
            "name": "Brass insert",
            "category": "bought_out",
            "unit": "pcs",
            "inspection_required": False,
        },
    )
    order = orders.create(
        buyer,
        supplier=supplier,
        division=im(),
        delivery_date=TODAY + timedelta(days=7),
        lines=[POLine(item, qty, price)],
    )
    orders.submit(buyer, order)
    orders.approve(director, order)
    line = receipts.confirm(stores, receipts.create(stores, order)).lines.get()
    invoice = invoices.create(
        clerk,
        supplier=supplier,
        division=im(),
        invoice_no=no,
        invoice_date=TODAY,
        lines=[LineInput(line.pk, qty, price)],
    )
    invoice = invoices.save(
        clerk,
        invoice,
        stated_total=str(invoice.total_amount),
        lines=[LineInput(line.pk, qty, price)],
    )
    invoices.add_attachment(clerk, invoice, SimpleUploadedFile("inv.pdf", PDF))
    return invoices.match(clerk, invoice)


@pytest.fixture
def invoice(clerk, director, supplier):
    return posted_invoice(clerk, director, supplier)


def voucher_for(clerk, supplier, *lines, division=None):
    return services.save(
        clerk,
        None,
        voucher_type=VoucherType.objects.get(code="CHQ"),
        division=division or im(),
        payee=supplier,
        description="Inserts",
        lines=list(lines),
    )


def pays(invoice, amount):
    return services.LineInput(amount=amount, supplier_invoice=invoice)


# --- Making the voucher ------------------------------------------------------------------------


def test_a_voucher_pays_a_matched_invoice_through_accounts_payable(clerk, supplier, invoice):
    assert invoices.payable(supplier, im()) == [invoice]
    voucher = voucher_for(clerk, supplier, pays(invoice, "12500.00"))
    line = voucher.lines.get()
    assert (line.invoice_no, line.supplier_invoice, line.tax_amount) == ("INV-77", invoice, 0)
    assert line.account == Account.objects.get(system_role="accounts_payable")
    assert line.division == im()
    pieces = cost_pieces(voucher)
    assert [(p.account.system_role, p.amount) for p in pieces] == [
        ("accounts_payable", Decimal("12500.00"))
    ]
    assert invoices.unpaid(invoice) == 0 and invoices.payable(supplier, im()) == []


def test_an_invoice_is_paid_in_parts_but_never_twice(clerk, supplier, invoice):
    voucher_for(clerk, supplier, pays(invoice, "5000.00"))
    with pytest.raises(VoucherError, match="more than the 7,500.00 still unpaid"):
        voucher_for(clerk, supplier, pays(invoice, "8000.00"))
    second = voucher_for(clerk, supplier, pays(invoice, "7500.00"))
    assert invoices.unpaid(invoice) == 0
    services.delete(clerk, second, "Wrong amount")
    assert invoices.unpaid(invoice) == Decimal("7500.00")  # a deleted voucher frees it


def test_the_database_refuses_paying_an_invoice_twice(clerk, supplier, invoice):
    voucher = voucher_for(clerk, supplier, pays(invoice, "12500.00"))
    other = voucher_for(clerk, supplier, services.LineInput(amount="1.00", invoice_no="X-1"))
    with pytest.raises(DatabaseError, match="paid more than its total"), transaction.atomic():
        VoucherLine.objects.create(
            voucher=other,
            line_no=2,
            amount=Decimal("0.01"),
            invoice_no="INV-77",
            supplier_invoice=invoice,
        )
    assert voucher.pk


def test_only_a_posted_invoice_of_the_payee_and_division(clerk, director, supplier, invoice):
    other = supplier_named("S0002", "Someone else")
    with pytest.raises(VoucherError, match="of another payee"):
        voucher_for(clerk, other, pays(invoice, "1.00"))
    held = invoices.create(
        clerk,
        supplier=supplier,
        division=im(),
        invoice_no="INV-99",
        invoice_date=TODAY,
        lines=[LineInput(invoice.lines.get().grn_line_id, "1", "12.50")],
    )
    with pytest.raises(VoucherError, match="not matched yet"):
        voucher_for(clerk, supplier, pays(held, "1.00"))


def test_the_invoice_number_does_not_clash_but_a_typed_copy_does(clerk, supplier, invoice):
    voucher_for(clerk, supplier, pays(invoice, "100.00"))
    voucher_for(clerk, supplier, pays(invoice, "100.00"))  # paying in parts is fine
    with pytest.raises(VoucherError, match="already entered as supplier invoice"):
        voucher_for(clerk, supplier, services.LineInput(amount="100.00", invoice_no="INV-77"))


# --- Approval --------------------------------------------------------------------------------


def test_the_scan_on_the_invoice_is_enough_and_coding_stays_payable(
    clerk, accountant, supplier, invoice
):
    voucher = voucher_for(clerk, supplier, pays(invoice, "12500.00"))
    services.submit(clerk, voucher)  # no scan on the voucher: it is on the invoice
    expense = Account.objects.filter(account_type="expense", is_active=True).first()
    services.code_lines(accountant, voucher, [CodingInput(1, account=expense, job_ref="J-1")])
    line = voucher.lines.get()
    assert line.account.system_role == "accounts_payable" and line.job_ref == "J-1"
    assert services.uncoded_lines(voucher) == []
    voucher = services.approve(accountant, voucher)
    assert voucher.status == Voucher.Status.ACCOUNTANT_APPROVED


def test_the_approvers_see_po_grn_and_invoice_side_by_side(clerk, director, supplier, invoice):
    client = as_user(clerk)
    payable = client.get(f"/api/v1/supplier-invoices/payable/?supplier={supplier.pk}&division=IM")
    assert [(row["invoice_no"], row["unpaid"]) for row in payable.json()] == [
        ("INV-77", "12500.00")
    ]
    made = client.post(
        "/api/v1/vouchers/",
        {
            "voucher_type": "CHQ",
            "division": "IM",
            "payee": supplier.pk,
            "description": "Inserts",
            "lines": [{"amount": "12500.00", "supplier_invoice": invoice.pk}],
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    line = made.json()["lines"][0]
    paid = line["supplier_invoice"]
    assert (paid["invoice_no"], paid["total_lkr"], paid["on_vouchers"]) == (
        "INV-77",
        "12500.00",
        "12500.00",
    )
    side = paid["lines"][0]
    assert (side["po"]["unit_price"], side["grn"]["accepted"], side["invoice"]["quantity"]) == (
        "12.50",
        "1000.000",
        "1000.000",
    )
    assert side["matches"] is True
    detail = as_user(clerk).get(f"/api/v1/supplier-invoices/{invoice.pk}/").json()
    assert detail["unpaid"] == "0.00" and detail["vouchers"][0]["amount"] == "12500.00"
