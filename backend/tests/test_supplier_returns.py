"""Supplier returns and debit notes (backlog P16-12)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core.models import Division
from apps.inventory import inspections, items, receipts, stock
from apps.inventory.models import IncomingInspection, Store
from apps.masters.models import Currency, Supplier
from apps.purchasing import invoices, orders, returns
from apps.purchasing.invoices import LineInput as InvoiceLine
from apps.purchasing.models import DebitNote, PurchaseOrder, SupplierReturn
from apps.purchasing.orders import LineInput as POLine
from apps.purchasing.returns import LineInput, ReturnError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
PDF = b"%PDF-1.4\n" + b"0" * 64
D = IncomingInspection.Decision
St = SupplierReturn.Status


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
def qc():
    return person("qc@sml.lk", "qc_inspector", divisions=("IM",))


@pytest.fixture
def clerk():
    return person("clerk@sml.lk", "clerk", divisions=("IM",))


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def line(buyer, director, stores):
    """A confirmed GRN line: 100 inserts at LKR 100, waiting for QC."""
    supplier = Supplier.objects.create(
        code="S0001", name="Inserts Lanka", currency=Currency.objects.get(code="LKR")
    )
    item = items.create_item(
        buyer, {"code": "M8-INSERT", "name": "Insert", "category": "bought_out", "unit": "pcs"}
    )
    order = orders.create(
        buyer,
        supplier=supplier,
        division=Division.objects.get(code="IM"),
        delivery_date=TODAY + timedelta(days=7),
        lines=[POLine(item, "100", "100")],
    )
    orders.submit(buyer, order)
    orders.approve(director, order)
    return receipts.confirm(stores, receipts.create(stores, order)).lines.get()


def lot(line):
    return f"{line.receipt.number}-1"


def inspect(qc, line, accepted="100"):
    inspection = inspections.start(qc, line)
    inspections.save(qc, inspection, results=[], accepted_quantity=accepted)
    decision = D.ACCEPTED if Decimal(accepted) else D.REJECTED
    return inspections.decide(qc, inspection, decision, "Faulty threads")


def invoice(clerk, line, qty, no="INV-1"):
    made = invoices.create(
        clerk,
        supplier=line.receipt.supplier,
        division=line.receipt.division,
        invoice_no=no,
        invoice_date=TODAY,
        lines=[InvoiceLine(line.pk, qty, "100")],
    )
    made = invoices.save(
        clerk, made, stated_total=str(made.total_amount), lines=[InvoiceLine(line.pk, qty, "100")]
    )
    invoices.add_attachment(clerk, made, SimpleUploadedFile("inv.pdf", PDF))
    return invoices.match(clerk, made)


def give_back(stores, line, kind, qty, reason="Threads stripped"):
    return returns.create(
        stores, line.receipt, kind=kind, reason=reason, lines=[LineInput(line.pk, lot(line), qty)]
    )


def on_hand(line, kind):
    return stock.on_hand(line.item, Store.objects.get(code=f"IM-{kind}"))


def entry_lines(entry):
    return {
        (row.account.system_role or row.account.number, row.debit, row.credit)
        for row in entry.lines.select_related("account")
    }


# --- Rejected goods -------------------------------------------------------------------------


def test_rejected_goods_go_back_and_the_po_expects_them_again(stores, qc, line):
    inspect(qc, line, accepted="80")
    assert on_hand(line, "REJ") == 20
    ret = returns.confirm(stores, give_back(stores, line, "rejected", "20"))
    assert ret.number == f"RTN{TODAY:%y%m%d}01"
    assert (ret.status, ret.journal_entry) == (St.CONFIRMED, None)  # no value: nothing posted
    assert on_hand(line, "REJ") == 0
    order = PurchaseOrder.objects.get(pk=line.receipt.purchase_order_id)
    assert order.status == PurchaseOrder.Status.PARTLY_RECEIVED
    assert order.lines.get().received_quantity == 80


def test_only_what_is_in_the_store_is_returned(stores, qc, line):
    inspect(qc, line, accepted="80")
    with pytest.raises(ReturnError, match="only 20 of lot"):
        give_back(stores, line, "rejected", "21")
    with pytest.raises(ReturnError, match="reason"):
        give_back(stores, line, "rejected", "5", reason=" ")
    with pytest.raises(ReturnError, match="not in the store"):
        returns.create(
            stores,
            line.receipt,
            kind="rejected",
            reason="x",
            lines=[LineInput(line.pk, "NOPE", "1")],
        )


def test_only_the_stores_person_returns_goods(qc, line, director):
    inspect(qc, line, accepted="80")
    with pytest.raises(ReturnError, match="stores person"):
        give_back(director, line, "rejected", "20")


# --- Accepted goods ---------------------------------------------------------------------------


def test_accepted_goods_not_yet_invoiced_go_back_against_grni(stores, qc, clerk, director, line):
    inspect(qc, line)
    ret = returns.confirm(stores, give_back(stores, line, "accepted", "10"))
    assert ret.status == St.AWAITING_APPROVAL and on_hand(line, "MAIN") == 100
    with pytest.raises(ReturnError):
        returns.approve(stores, ret)
    ret = returns.approve(director, ret, "Agreed with supplier")
    assert ret.status == St.CONFIRMED and on_hand(line, "MAIN") == 90
    assert entry_lines(ret.journal_entry) == {
        ("grni", Decimal("1000.00"), Decimal("0")),
        ("1210", Decimal("0"), Decimal("1000.00")),
    }
    assert ret.lines.get().uninvoiced_quantity == 10
    # Only the 90 kept can be invoiced now.
    rows = invoices.open_lines(clerk, line.receipt.supplier, line.receipt.division)
    assert rows[0]["open"] == 90


def test_invoiced_goods_go_back_with_a_debit_note(stores, qc, clerk, director, line):
    inspect(qc, line)
    posted = invoice(clerk, line, "100")
    ret = returns.approve(
        director, returns.confirm(stores, give_back(stores, line, "accepted", "10"))
    )
    note = DebitNote.objects.get()
    assert (note.invoice, note.quantity, note.total_lkr) == (posted, 10, Decimal("1000.00"))
    assert note.number == f"DN{TODAY:%y%m%d}01"
    assert entry_lines(ret.journal_entry) == {
        ("accounts_payable", Decimal("1000.00"), Decimal("0")),
        ("1210", Decimal("0"), Decimal("1000.00")),
    }
    assert invoices.unpaid(posted) == Decimal("9000.00")


def test_a_return_split_between_invoiced_and_not(stores, qc, clerk, director, line):
    inspect(qc, line)
    posted = invoice(clerk, line, "60")
    ret = returns.approve(
        director, returns.confirm(stores, give_back(stores, line, "accepted", "50"))
    )
    returned = ret.lines.get()
    assert (returned.uninvoiced_quantity, returned.invoiced_quantity) == (40, 10)
    assert entry_lines(ret.journal_entry) == {
        ("grni", Decimal("4000.00"), Decimal("0")),
        ("accounts_payable", Decimal("1000.00"), Decimal("0")),
        ("1210", Decimal("0"), Decimal("5000.00")),
    }
    assert invoices.unpaid(posted) == Decimal("5000.00")
    rows = invoices.open_lines(clerk, line.receipt.supplier, line.receipt.division)
    assert rows == []  # 100 accepted, 50 returned, 50 invoiced (60 less the 10 debited)


def test_the_director_sends_a_return_back(stores, qc, director, line):
    inspect(qc, line)
    ret = returns.confirm(stores, give_back(stores, line, "accepted", "10"))
    ret = returns.send_back(director, ret, "Check with QC first")
    assert ret.status == St.DRAFT and on_hand(line, "MAIN") == 100


def test_a_confirmed_return_and_its_debit_notes_never_change(stores, qc, clerk, director, line):
    inspect(qc, line)
    invoice(clerk, line, "100")
    ret = returns.approve(
        director, returns.confirm(stores, give_back(stores, line, "accepted", "5"))
    )
    with pytest.raises(DatabaseError, match="cannot be changed"), transaction.atomic():
        SupplierReturn.objects.filter(pk=ret.pk).update(reason="x")
    with pytest.raises(DatabaseError, match="never changed"), transaction.atomic():
        DebitNote.objects.update(total_lkr=Decimal("1"))


# --- Through the API --------------------------------------------------------------------------


def test_the_api_lists_lots_and_returns_goods(stores, qc, line):
    inspect(qc, line, accepted="80")
    client = as_user(stores)
    lots = client.get(f"/api/v1/supplier-returns/lots/?grn={line.receipt_id}&kind=rejected").json()
    assert [(r["lot_no"], r["quantity"]) for r in lots] == [(lot(line), "20.000")]
    made = client.post(
        "/api/v1/supplier-returns/",
        {
            "grn": line.receipt_id,
            "kind": "rejected",
            "reason": "Rejected by QC",
            "vehicle_no": "LB-1234",
            "lines": [{"grn_line": line.pk, "lot_no": lot(line), "quantity": "20"}],
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    done = client.post(f"/api/v1/supplier-returns/{made.json()['id']}/confirm/", {}, format="json")
    assert done.json()["status"] == "confirmed"
