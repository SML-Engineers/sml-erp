"""Purchasing and stores reports and traceability (backlog P16-13, spec 5A.7)."""

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core.models import Division
from apps.inventory import inspections, items, receipts
from apps.inventory.models import IncomingInspection
from apps.masters.models import Currency, Supplier
from apps.purchasing import invoices, orders, reports, returns
from apps.purchasing.invoices import LineInput
from apps.purchasing.orders import LineInput as POLine
from apps.vouchers import services as vouchers
from apps.vouchers.models import VoucherType

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
PDF = b"%PDF-1.4\n" + b"0" * 64
D = IncomingInspection.Decision


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
        "stores": person("stores@sml.lk", "store_supervisor", divisions=("IM",)),
        "qc": person("qc@sml.lk", "qc_inspector", divisions=("IM",)),
        "clerk": person("clerk@sml.lk", "clerk", divisions=("IM",)),
        "accountant": person("accountant@sml.lk", "accountant", all_divisions=True),
        "director": person("director@sml.lk", "director", all_divisions=True),
    }


@pytest.fixture
def supplier():
    return Supplier.objects.create(
        code="S0001", name="Inserts Lanka", currency=Currency.objects.get(code="LKR")
    )


def po(people, supplier, qty="100", price="100", days=7, code="M8-INSERT"):
    item = items.create_item(
        people["buyer"],
        {"code": code, "name": "Insert", "category": "bought_out", "unit": "pcs"},
    )
    order = orders.create(
        people["buyer"],
        supplier=supplier,
        division=Division.objects.get(code="IM"),
        delivery_date=TODAY + timedelta(days=days),
        lines=[POLine(item, qty, price)],
    )
    orders.submit(people["buyer"], order)
    return orders.approve(people["director"], order)


def receive_and_accept(people, order, accepted="100"):
    line = receipts.confirm(people["stores"], receipts.create(people["stores"], order)).lines.get()
    inspection = inspections.start(people["qc"], line)
    inspections.save(people["qc"], inspection, results=[], accepted_quantity=accepted)
    inspections.decide(people["qc"], inspection, D.ACCEPTED)
    return line


def invoice(people, line, qty="100", price="100", no="INV-1"):
    clerk = people["clerk"]
    made = invoices.create(
        clerk,
        supplier=line.receipt.supplier,
        division=line.receipt.division,
        invoice_no=no,
        invoice_date=TODAY,
        lines=[LineInput(line.pk, qty, price)],
    )
    made = invoices.save(
        clerk, made, stated_total=str(made.total_amount), lines=[LineInput(line.pk, qty, price)]
    )
    invoices.add_attachment(clerk, made, SimpleUploadedFile("inv.pdf", PDF))
    return invoices.match(clerk, made)


# --- Open POs -----------------------------------------------------------------------------------


def test_open_pos_and_overdue_deliveries(people, supplier, monkeypatch):
    order = po(people, supplier, days=3)
    rows = reports.open_orders(people["accountant"])
    assert [(r["label"], r["overdue"], r["outstanding_lkr"]) for r in rows] == [
        (order.label, False, "10000.00")
    ]
    assert reports.open_orders(people["accountant"], overdue_only=True) == []
    monkeypatch.setattr(timezone, "localdate", lambda *a: TODAY + timedelta(days=5))
    late = reports.open_orders(people["accountant"], overdue_only=True)
    assert [(r["label"], r["days_late"]) for r in late] == [(order.label, 2)]


# --- GRNI ---------------------------------------------------------------------------------------


def test_grni_lists_accepted_goods_not_invoiced_and_matches_the_ledger(people, supplier):
    line = receive_and_accept(people, po(people, supplier), accepted="80")
    rows = reports.grni(people["accountant"])
    assert [(r["grn"], r["quantity"], r["value"]) for r in rows] == [
        (line.receipt.number, "80", "8000.00")
    ]
    assert reports.grni_ledger_balance() == "8000.00"
    invoice(people, line, qty="50")
    assert reports.grni(people["accountant"])[0]["value"] == "3000.00"
    assert reports.grni_ledger_balance() == "3000.00"


# --- Held invoices and exceptions ----------------------------------------------------------------


def test_held_invoices_and_approved_exceptions(people, supplier):
    line = receive_and_accept(people, po(people, supplier))
    held = invoice(people, line, price="105")
    rows = reports.held_invoices(people["accountant"])
    assert [(r["invoice_no"], r["status"]) for r in rows] == [("INV-1", "Held: discrepancy")]
    assert "PO price 100.00" in rows[0]["differences"]
    invoices.request_exception(people["accountant"], held, "Price list changed in October")
    invoices.approve_exception(people["director"], held, "OK")
    assert reports.held_invoices(people["accountant"]) == []
    found = reports.exceptions(people["accountant"])
    assert [(r["kind"], r["reason"], r["approved_by"]) for r in found] == [
        ("Invoice difference", "Price list changed in October", "Director")
    ]


# --- By supplier --------------------------------------------------------------------------------


def test_receipts_and_rejections_by_supplier(people, supplier):
    receive_and_accept(people, po(people, supplier), accepted="90")
    rows = reports.by_supplier(people["accountant"])
    assert [
        (r["supplier"], r["grns"], r["received_value"], r["rejected_value"], r["rejection_rate"])
        for r in rows
    ] == [("Inserts Lanka", 1, "10000.00", "1000.00", 10.0)]


# --- Trail --------------------------------------------------------------------------------------


def test_the_trail_from_po_to_voucher_both_ways(people, supplier):
    order = po(people, supplier)
    line = receive_and_accept(people, order, accepted="90")
    posted = invoice(people, line, qty="90")
    vouchers.save(
        people["clerk"],
        None,
        voucher_type=VoucherType.objects.get(code="CHQ"),
        division=Division.objects.get(code="IM"),
        payee=supplier,
        lines=[vouchers.LineInput(amount="9000.00", supplier_invoice=posted)],
    )
    ret = returns.confirm(
        people["stores"],
        returns.create(
            people["stores"],
            line.receipt,
            kind="rejected",
            reason="Rejected by QC",
            lines=[returns.LineInput(line.pk, f"{line.receipt.number}-1", "10")],
        ),
    )
    client = as_user(people["accountant"])
    for query in (f"po={order.pk}", f"grn={line.receipt_id}", f"invoice={posted.pk}"):
        trail = client.get(f"/api/v1/purchasing-reports/trail/?{query}").json()
        assert trail["po"]["label"] == order.label
        assert [g["number"] for g in trail["grns"]] == [line.receipt.number]
        assert trail["inspections"][0]["accepted"] == "90"
        assert [(i["invoice_no"], i["unpaid"]) for i in trail["invoices"]] == [("INV-1", "0.00")]
        assert trail["vouchers"][0]["amount"] == "9000.00"
        assert [r["number"] for r in trail["returns"]] == [ret.number]


# --- Dashboard, exports and the return note ------------------------------------------------------


def test_the_dashboard_tiles(people, supplier):
    receive_and_accept(people, po(people, supplier), accepted="80")
    po(people, supplier, code="M10-INSERT")
    tiles = as_user(people["director"]).get("/api/v1/purchasing-reports/dashboard/").json()
    assert (tiles["open_orders"], tiles["grni"]["total"], tiles["stock_value"]) == (
        1,  # the first PO has all its goods
        "8000.00",
        "8000.00",
    )


def test_reports_export_to_excel_and_pdf(people, supplier):
    receive_and_accept(people, po(people, supplier))
    client = as_user(people["accountant"])
    for name in ("open-orders", "grni", "held-invoices", "exceptions", "suppliers"):
        xlsx = client.get(f"/api/v1/purchasing-reports/{name}/?export=xlsx")
        assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK", name
        pdf = client.get(f"/api/v1/purchasing-reports/{name}/?export=pdf")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF"), name
    stock = client.get("/api/v1/stock/?export=xlsx")
    assert stock.status_code == 200 and stock.content[:2] == b"PK"


def test_the_printed_return_note(people, supplier):
    line = receive_and_accept(people, po(people, supplier), accepted="95")
    ret = returns.create(
        people["stores"],
        line.receipt,
        kind="rejected",
        reason="Cracked",
        lines=[returns.LineInput(line.pk, f"{line.receipt.number}-1", "5")],
    )
    printed = as_user(people["stores"]).get(f"/api/v1/supplier-returns/{ret.pk}/pdf/")
    assert printed.status_code == 200 and printed["Content-Type"] == "application/pdf"


def test_reports_need_purchasing_access(people):
    assert as_user(people["clerk"]).get("/api/v1/purchasing-reports/grni/").status_code == 403
