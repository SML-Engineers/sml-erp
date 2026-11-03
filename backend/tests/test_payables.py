"""Payables aging and supplier statements (backlog P2-10, spec 6)."""

import csv
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone
from openpyxl import Workbook

from apps.masters.models import Supplier
from apps.purchasing import payables
from apps.purchasing.models import SupplierStatement
from apps.purchasing.orders import PurchasingError
from apps.purchasing.payables import LineInput
from apps.vouchers import services as vouchers
from apps.vouchers.models import Voucher

from . import test_invoice_vouchers as po
from .test_access import as_user, person
from .test_payments import bank, pay  # noqa: F401 - the bank fixture is used by name
from .test_voucher_amendments import approved

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()
D = Decimal


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
def voucher(clerk, accountant, director):
    """Lanka Steel's invoice INV-7, LKR 1,000.00, on a voucher approved today."""
    return approved(clerk, accountant, director)


@pytest.fixture
def part_paid(voucher, cashier, bank):  # noqa: F811
    """400.00 paid on it by cheque 000100."""
    return pay(cashier, voucher, bank, "400.00")


def supplier():
    return Supplier.objects.get(code="S0001")


# --- What we owe -------------------------------------------------------------------------------


def test_a_voucher_s_invoice_less_what_was_paid_is_owed_and_aged(part_paid, accountant):
    (item,) = payables.open_items(TODAY)
    assert (item["kind"], item["reference"], item["total"], item["open"]) == (
        "voucher",
        "INV-7",
        D("1000.00"),
        D("600.00"),
    )
    assert (item["due_date"], item["bucket"]) == (TODAY + timedelta(days=30), "current")
    (row,) = payables.aging(accountant, TODAY + timedelta(days=45))
    assert (row["supplier"], row["d30"], row["total"]) == (
        "Lanka Steel (Pvt) Ltd",
        "600.00",
        "600.00",
    )
    # The day before, it was not yet invoiced.
    assert payables.owed(supplier(), TODAY - timedelta(days=1)) == 0  # not yet invoiced
    assert payables.owed(supplier(), TODAY) == D("600.00")


def test_a_paid_voucher_owes_nothing(voucher, cashier, bank):  # noqa: F811
    pay(cashier, voucher, bank, "1000.00")
    assert payables.open_items(TODAY) == []


def test_a_matched_supplier_invoice_is_owed_less_its_paid_part(
    clerk,
    accountant,
    director,
    cashier,
    bank,  # noqa: F811
):
    seller = po.supplier_named("S0009", "Fasteners Lanka")
    invoice = po.posted_invoice(clerk, director, seller)  # 1,000 x 12.50 = 12,500.00
    v = po.voucher_for(clerk, seller, po.pays(invoice, "5000.00"))
    vouchers.submit(clerk, v)
    vouchers.approve(accountant, v, "checked")
    vouchers.approve(director, Voucher.objects.get(pk=v.pk))
    pay(cashier, v, bank, "5000.00")
    (item,) = payables.open_items(TODAY, supplier=seller)
    assert (item["kind"], item["reference"], item["open"], item["division"].code) == (
        "invoice",
        "INV-77",
        D("7500.00"),
        "IM",
    )


# --- Supplier statements ------------------------------------------------------------------------


def statement_lines():
    return [
        LineInput(TODAY, "inv 7", "Steel bars", "1000.00", "0"),
        LineInput(TODAY, "INV-99", "Steel plates", "500.00", "0"),
        LineInput(TODAY, "Chq 000100", "Payment, thank you", "0", "400.00"),
    ]


def test_a_statement_is_matched_to_our_records_and_differences_listed(part_paid, clerk):
    statement = payables.create(
        clerk,
        supplier(),
        statement_date=TODAY,
        closing_balance="1100.00",
        lines=statement_lines(),
    )
    result = payables.reconcile(statement)
    assert [(line.reference, ours["document"], diff) for line, ours, diff in result["matched"]] == [
        ("inv 7", part_paid.voucher.number, 0),
        ("Chq 000100", part_paid.number, 0),
    ]
    assert [line.reference for line in result["theirs_only"]] == ["INV-99"]
    assert result["ours_only"] == []
    assert (result["their_balance"], result["our_balance"], result["difference"]) == (
        D("1100.00"),
        D("600.00"),
        D("500.00"),
    )


def test_a_payment_is_matched_by_its_cheque_number_or_amount(part_paid, clerk):
    statement = payables.create(
        clerk,
        supplier(),
        statement_date=TODAY,
        closing_balance="600.00",
        lines=[
            LineInput(TODAY, "INV-7", "", "1000.00", "0"),
            LineInput(TODAY - timedelta(days=2), "", "Payment received", "0", "400.00"),
        ],
    )
    result = payables.reconcile(statement)
    assert len(result["matched"]) == 2
    assert (result["theirs_only"], result["ours_only"], result["difference"]) == ([], [], 0)


def test_the_accountant_marks_it_checked_and_it_never_changes(part_paid, clerk, accountant):
    statement = payables.create(
        clerk, supplier(), statement_date=TODAY, closing_balance="1100.00", lines=statement_lines()
    )
    with pytest.raises(PurchasingError, match="The Accountant marks"):
        payables.check(clerk, statement, "Agrees")
    with pytest.raises(PurchasingError, match="Write what was found"):
        payables.check(accountant, statement, " ")
    statement = payables.check(accountant, statement, "INV-99 not received; asked for a copy")
    assert (statement.status, statement.checked_by) == ("checked", accountant)
    with pytest.raises(PurchasingError, match="never changes"):
        payables.save(
            clerk, statement, statement_date=TODAY, closing_balance="0", lines=statement_lines()
        )
    with pytest.raises(DatabaseError), transaction.atomic():
        SupplierStatement.objects.filter(pk=statement.pk).update(closing_balance=D("1"))
    with pytest.raises(DatabaseError), transaction.atomic():
        statement.lines.all().delete()


def test_wrong_statements_are_refused(voucher, clerk):
    with pytest.raises(PurchasingError, match="either a debit or a credit"):
        payables.create(
            clerk,
            supplier(),
            statement_date=TODAY,
            closing_balance="0",
            lines=[LineInput(TODAY, "X", "", "10", "10")],
        )
    with pytest.raises(PurchasingError, match="not a date"):
        payables.create(
            clerk,
            supplier(),
            statement_date=TODAY,
            closing_balance="0",
            lines=[LineInput("31/31/2026", "X", "", "10", "0")],
        )
    with pytest.raises(PurchasingError, match="cannot be in the future"):
        payables.create(
            clerk,
            supplier(),
            statement_date=TODAY + timedelta(days=1),
            closing_balance="0",
            lines=statement_lines(),
        )


def workbook() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.append(["Lanka Steel (Pvt) Ltd"])
    sheet.append(["Statement of account"])
    sheet.append(["Date", "Ref. No", "Particulars", "Debit", "Credit", "Balance"])
    sheet.append([None, None, "Opening balance", None, None, 0])
    sheet.append([TODAY, "INV-7", "Steel bars", 1000, None, 1000])
    sheet.append([TODAY, "CHQ 000100", "Payment", None, 400.5, 599.5])
    sheet.append(["Total", None, None, 1000, 400.5, None])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_a_statement_is_read_from_excel_or_csv():
    lines = payables.parse(workbook(), "statement.xlsx")
    assert [(x["reference"], x["debit"], x["credit"]) for x in lines] == [
        ("INV-7", "1000.00", "0.00"),
        ("CHQ 000100", "0.00", "400.50"),
    ]
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(["Date", "Reference", "Description", "Dr", "Cr"])
    writer.writerow(["31/10/2026", "INV-7", "Steel", "1,000.00", ""])
    lines = payables.parse(text.getvalue().encode(), "statement.csv")
    assert [(str(x["date"]), x["debit"]) for x in lines] == [("2026-10-31", "1000.00")]
    with pytest.raises(PurchasingError, match="No heading row"):
        payables.parse(b"a,b\n1,2\n", "x.csv")


# --- API ----------------------------------------------------------------------------------------


def test_the_screens_api(part_paid, clerk, accountant):
    staff = as_user(accountant)
    aging = staff.get(f"/api/v1/payables/aging/?supplier={supplier().pk}").json()
    assert aging["rows"][0]["total"] == "600.00"
    assert aging["items"][0]["reference"] == "INV-7"
    assert staff.get("/api/v1/payables/aging/?export=xlsx").status_code == 200
    stores = person("stores@sml.lk", "store_supervisor", all_divisions=True)
    assert as_user(stores).get("/api/v1/payables/aging/").status_code == 403

    entry = as_user(clerk)
    upload = entry.post(
        "/api/v1/supplier-statements/import/",
        {"file": SimpleUploadedFile("s.xlsx", workbook())},
        format="multipart",
    )
    assert upload.status_code == 200, upload.json()
    made = entry.post(
        "/api/v1/supplier-statements/",
        {
            "supplier": supplier().pk,
            "statement_date": TODAY.isoformat(),
            "closing_balance": "599.50",
            "lines": upload.json()["lines"],
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    body = made.json()
    assert body["reconciliation"]["matched"][0]["ours"]["reference"] == "INV-7"
    assert body["can_check"] is False  # the Clerk enters; the Accountant checks
    done = staff.post(
        f"/api/v1/supplier-statements/{body['id']}/check/", {"note": "Agrees"}, format="json"
    )
    assert done.status_code == 200 and done.json()["status"] == "checked"
    assert entry.delete(f"/api/v1/supplier-statements/{body['id']}/").status_code == 400
