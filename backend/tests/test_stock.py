"""Stock movements and valuation (backlog P16-09, spec 5A.3, IAS 2)."""

import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.models import Sum
from django.db.utils import DatabaseError
from django.utils import timezone
from openpyxl import load_workbook

from apps.accounting.models import Account, JournalEntry
from apps.core.models import Division
from apps.inventory import inspections, items, receipts, stock
from apps.inventory.inspections import ResultInput
from apps.inventory.models import IncomingInspection, StockMovement, Store
from apps.inventory.packages import PackageInput
from apps.masters.models import Currency, Supplier
from apps.purchasing import orders
from apps.purchasing.orders import LineInput as POLine

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
D = IncomingInspection.Decision


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
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def resin(buyer):
    return items.create_item(
        buyer,
        {
            "code": "PP-H-WHITE",
            "name": "PP homopolymer",
            "category": "raw_material",
            "unit": "kg",
            "package_type": "bag",
            "package_tare": "0.1",
        },
    )


def store(code):
    return Store.objects.get(code=code)


def on_hand(item, code):
    return stock.on_hand(item, store(code))


def value(item, code):
    rows = StockMovement.objects.filter(item=item, store=store(code))
    return rows.aggregate(v=Sum("value"))["v"] or Decimal("0")


def approved_po(buyer, director, item, qty="100", price="420"):
    supplier = Supplier.objects.create(
        code=f"S{Supplier.objects.count() + 1:04d}",
        name="SDD Polymer",
        currency=Currency.objects.get(code="LKR"),
    )
    order = orders.create(
        buyer,
        supplier=supplier,
        division=Division.objects.get(code="IM"),
        delivery_date=TODAY + timedelta(days=7),
        lines=[POLine(item, qty, price)],
    )
    orders.submit(buyer, order)
    return orders.approve(director, order)


def bags(buyer, director, stores, item, count=4, damaged=0, price="420"):
    order = approved_po(buyer, director, item, str(count * 25), price)
    grn = receipts.create(stores, order)
    receipts.set_packages(
        stores,
        grn,
        1,
        [PackageInput(gross_weight="25.1", damaged=n < damaged) for n in range(count)],
    )
    return receipts.confirm(stores, grn).lines.get()


def inspect(qc, line, decision=D.ACCEPTED, reason="", **values):
    inspection = inspections.start(qc, line)
    inspections.save(qc, inspection, results=[], **values)
    return inspections.decide(qc, inspection, decision, reason)


# --- Receiving -------------------------------------------------------------------------------


def test_received_goods_wait_in_quarantine_at_no_value(buyer, director, stores, resin):
    line = bags(buyer, director, stores, resin, damaged=1)
    assert on_hand(resin, "IM-QUAR") == Decimal("75.000")
    assert on_hand(resin, "IM-REJ") == Decimal("25.000")  # the damaged bag
    assert value(resin, "IM-QUAR") == 0 and on_hand(resin, "IM-MAIN") == 0
    lots = StockMovement.objects.filter(receipt_line=line).values_list("lot_no", flat=True)
    assert sorted(lots) == [f"{line.receipt.number}-1-00{n}" for n in range(1, 5)]
    assert not JournalEntry.objects.filter(source_type="goods_receipt").exists()


# --- QC decisions ------------------------------------------------------------------------------


def test_accepted_goods_go_to_the_main_store_at_the_po_price(buyer, director, stores, qc, resin):
    line = bags(buyer, director, stores, resin)
    inspect(qc, line, rejected_packages=[2])
    assert on_hand(resin, "IM-QUAR") == 0
    assert (on_hand(resin, "IM-MAIN"), value(resin, "IM-MAIN")) == (
        Decimal("75.000"),
        Decimal("31500.00"),  # 75 kg × LKR 420
    )
    assert on_hand(resin, "IM-REJ") == Decimal("25.000") and value(resin, "IM-REJ") == 0
    entry = JournalEntry.objects.get(source_type="goods_receipt")
    lines = {
        (row.account.number or row.account.system_role, row.debit, row.credit)
        for row in entry.lines.select_related("account")
    }
    grni = Account.objects.get(system_role="grni")
    assert lines == {
        ("1210", Decimal("31500.00"), Decimal("0")),
        (grni.number, Decimal("0"), Decimal("31500.00")),
    }
    assert entry.lines.get(account=grni).supplier == line.receipt.supplier


def test_rejected_goods_are_not_valued(buyer, director, stores, qc, resin):
    line = bags(buyer, director, stores, resin)
    inspect(qc, line, D.REJECTED, "Wet bags")
    assert (on_hand(resin, "IM-REJ"), on_hand(resin, "IM-MAIN")) == (Decimal("100.000"), 0)
    assert not JournalEntry.objects.filter(source_type="goods_receipt").exists()


def test_part_of_an_item_without_packages(buyer, director, stores, qc):
    inserts = items.create_item(
        buyer, {"code": "M6-INSERT", "name": "Insert", "category": "bought_out", "unit": "pcs"}
    )
    order = approved_po(buyer, director, inserts, "1000", "12.50")
    line = receipts.confirm(stores, receipts.create(stores, order)).lines.get()
    inspect(qc, line, accepted_quantity="980")
    assert (on_hand(inserts, "IM-MAIN"), value(inserts, "IM-MAIN")) == (
        Decimal("980.000"),
        Decimal("12250.00"),
    )
    assert on_hand(inserts, "IM-REJ") == 20


def test_the_weighted_average_cost(buyer, director, stores, qc, resin):
    inspect(qc, bags(buyer, director, stores, resin, count=4, price="400"))  # 100 kg at 400
    inspect(qc, bags(buyer, director, stores, resin, count=2, price="460"))  # 50 kg at 460
    costs = stock.average_costs(StockMovement.objects.all())
    assert costs[resin.pk] == Decimal("420.0000")


def test_a_deviation_is_valued_when_the_director_approves(buyer, director, stores, resin):
    qc = person("qc@sml.lk", "qc_inspector", divisions=("IM",))
    plan = inspections.save_plan(
        qc,
        None,
        {"name": "PP", "item": resin, "sampling": "all"},
        [inspections.ParameterInput("MFI", "number", "10", "14", critical=True)],
    )
    assert plan.pk
    line = bags(buyer, director, stores, resin)
    inspection = inspections.start(qc, line)
    inspections.save(qc, inspection, results=[ResultInput(1, value="15")])
    inspections.decide(qc, inspection, D.DEVIATION, "Trial OK")
    assert on_hand(resin, "IM-MAIN") == 0  # not yet
    inspections.approve_deviation(director, inspection)
    assert on_hand(resin, "IM-MAIN") == 100


# --- No inspection, reversal, immutability -------------------------------------------------


def test_an_item_needing_no_inspection_is_valued_on_confirming_and_reversed(
    buyer, director, stores
):
    grease = items.create_item(
        buyer,
        {
            "code": "GREASE",
            "name": "Grease",
            "category": "consumable",
            "unit": "kg",
            "inspection_required": False,
        },
    )
    order = approved_po(buyer, director, grease, "5", "900")
    grn = receipts.confirm(stores, receipts.create(stores, order))
    assert (on_hand(grease, "IM-MAIN"), value(grease, "IM-MAIN")) == (5, Decimal("4500.00"))
    entry = JournalEntry.objects.get(source_type="goods_receipt")
    assert entry.lines.get(debit__gt=0).account.number == "1240"
    receipts.request_reversal(stores, grn, "Wrong PO")
    receipts.approve_reversal(director, grn)
    assert (on_hand(grease, "IM-MAIN"), value(grease, "IM-MAIN")) == (0, 0)
    assert JournalEntry.objects.filter(reversal_of=entry).exists()


def test_a_reversal_before_qc_empties_quarantine(buyer, director, stores, resin):
    line = bags(buyer, director, stores, resin, damaged=1)
    receipts.request_reversal(stores, line.receipt, "Counted twice")
    receipts.approve_reversal(director, line.receipt)
    assert on_hand(resin, "IM-QUAR") == 0 and on_hand(resin, "IM-REJ") == 0


def test_non_stock_items_have_no_movements(buyer, director, stores):
    service = items.create_item(
        buyer,
        {"code": "CALIBRATION", "name": "Calibration", "category": "consumable", "is_stock": False},
    )
    order = approved_po(buyer, director, service, "1", "15000")
    receipts.confirm(stores, receipts.create(stores, order))
    assert not StockMovement.objects.exists()


def test_movements_are_never_changed_or_deleted(buyer, director, stores, resin):
    bags(buyer, director, stores, resin)
    with pytest.raises(DatabaseError, match="never changed"), transaction.atomic():
        StockMovement.objects.update(quantity=Decimal("1"))
    with pytest.raises(DatabaseError, match="never changed"), transaction.atomic():
        StockMovement.objects.all().delete()


def test_a_missing_main_store_stops_qc(buyer, director, stores, qc, resin):
    line = bags(buyer, director, stores, resin)
    Store.objects.filter(code="IM-MAIN").update(is_active=False)
    inspection = inspections.start(qc, line)
    with pytest.raises(inspections.InspectionError, match="no active main store"):
        inspections.decide(qc, inspection, D.ACCEPTED)
    assert on_hand(resin, "IM-MAIN") == 0


# --- Through the API -------------------------------------------------------------------------


def test_the_api_shows_stock_on_hand_and_movements(buyer, director, stores, qc, resin):
    inspect(qc, bags(buyer, director, stores, resin, damaged=1))
    accountant = person("accountant@sml.lk", "accountant", all_divisions=True)
    client = as_user(accountant)
    body = client.get("/api/v1/stock/").json()
    rows = {(r["item"]["code"], r["store"]["code"]): r for r in body["rows"]}
    assert rows[("PP-H-WHITE", "IM-MAIN")]["quantity"] == "75.000"
    assert rows[("PP-H-WHITE", "IM-MAIN")]["value"] == "31500.00"
    assert rows[("PP-H-WHITE", "IM-MAIN")]["average_cost"] == "420.0000"
    assert rows[("PP-H-WHITE", "IM-REJ")]["quantity"] == "25.000"
    assert ("PP-H-WHITE", "IM-QUAR") not in rows
    assert body["total_value"] == "31500.00"
    lots = client.get("/api/v1/stock/?lots=1").json()["rows"]
    assert len(lots) == 4
    moves = client.get("/api/v1/stock/movements/").json()
    assert {m["kind"] for m in moves} == {"received", "damaged", "accepted"}
    ws = person("ws@sml.lk", "store_supervisor", divisions=("WS",))
    assert as_user(ws).get("/api/v1/stock/").json()["rows"] == []
    # Owner, 12 Nov 2026: the Planner (no cost access) sees quantities, never values.
    planner = person("planner@sml.lk", "production_planner", all_divisions=True)
    seen = as_user(planner).get("/api/v1/stock/").json()
    assert seen["sees_values"] is False and seen["total_value"] is None
    row = next(r for r in seen["rows"] if r["store"]["code"] == "IM-MAIN")
    assert (row["quantity"], row["value"], row["average_cost"]) == ("75.000", None, None)
    assert {m["value"] for m in as_user(planner).get("/api/v1/stock/movements/").json()} == {None}
    sheet = as_user(planner).get("/api/v1/stock/?export=xlsx")
    assert sheet.status_code == 200
    content = b"".join(sheet.streaming_content) if sheet.streaming else sheet.content
    cells = {
        str(c.value) for row in load_workbook(io.BytesIO(content)).active.iter_rows() for c in row
    }
    assert "Quantity" in cells and not {"Average cost (LKR)", "Value (LKR)"} & cells
    assert body["sees_values"] is True
