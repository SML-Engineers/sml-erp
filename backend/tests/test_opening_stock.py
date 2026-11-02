"""Opening stock from the stores count (backlog P16-15; owner's decision of 2 Nov 2026)."""

import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from apps.accounting.models import Account, JournalEntry
from apps.inventory import items, opening, stock
from apps.inventory.models import OpeningStock, OpeningStockLine, StockMovement
from apps.inventory.opening import OpeningError
from apps.masters.excel import ImportRefused

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
HEADER = ["Item code", "Store", "Quantity", "Cost per unit (LKR)", "Lot or heat no."]


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def stores():
    return person("stores@sml.lk", "store_supervisor", all_divisions=True)


@pytest.fixture
def resin(accountant):
    return items.create_item(
        accountant,
        {"code": "PP-H-25", "name": "PP resin", "category": "raw_material", "unit": "kg"},
    )


@pytest.fixture
def cutter(accountant):
    return items.create_item(
        accountant,
        {"code": "CNMG", "name": "Turning insert", "category": "consumable", "unit": "pcs"},
    )


def sheet(*rows, header=HEADER) -> bytes:
    workbook = Workbook()
    workbook.active.title = "Opening stock"
    workbook.active.append(header)
    for row in rows:
        workbook.active.append(list(row))
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


GOOD = (("PP-H-25", "IM-MAIN", 1250.5, 420, "LOT-7"), ("CNMG", "WS-MAIN", 40, "1850.00", ""))


def load(user, *rows, current=None, dry_run=False):
    return opening.load(
        user, current, content=sheet(*(rows or GOOD)), count_date=TODAY, dry_run=dry_run
    )


# --- Loading the count ---------------------------------------------------------------------


def test_the_template_lists_items_and_main_stores(resin, cutter):
    book = load_workbook(io.BytesIO(opening.template()))
    assert book.sheetnames == ["Opening stock", "Items", "Stores"]
    assert [c.value for c in book["Opening stock"][1]] == HEADER
    assert [r[0] for r in book["Items"].iter_rows(min_row=2, values_only=True)] == [
        "CNMG",
        "PP-H-25",
    ]
    assert [r[0] for r in book["Stores"].iter_rows(min_row=2, values_only=True)] == [
        "IM-MAIN",
        "WS-MAIN",
    ]


def test_the_accountant_loads_a_draft(accountant, resin, cutter):
    checked, summary = load(accountant, dry_run=True)
    assert checked is None
    assert summary == {"rows": 2, "value": "599210.00"}  # 1,250.5 x 420 + 40 x 1,850
    assert not OpeningStock.objects.exists()
    made, _ = load(accountant)
    assert made.number == f"OS{TODAY:%y%m%d}01"
    assert made.status == "draft"
    rows = [
        (x.item.code, x.store.code, x.lot_no, str(x.quantity), str(x.unit_cost), str(x.value))
        for x in made.lines.all()
    ]
    assert rows == [
        ("PP-H-25", "IM-MAIN", f"{made.number}-LOT-7", "1250.500", "420.0000", "525210.00"),
        ("CNMG", "WS-MAIN", f"{made.number}-2", "40.000", "1850.0000", "74000.00"),
    ]
    assert not StockMovement.objects.exists()  # nothing in stock before the Director approves


def test_every_bad_row_is_listed_and_nothing_is_loaded(accountant, resin, cutter):
    rows = [
        ("NOPE", "IM-MAIN", 1, 1, ""),
        ("PP-H-25", "IM-QUAR", 1, 1, ""),
        ("PP-H-25", "IM-MAIN", 0, 1, ""),
        ("PP-H-25", "IM-MAIN", 1, "abc", ""),
        ("PP-H-25", "IM-MAIN", "1.0001", 1, ""),
        ("CNMG", "WS-MAIN", 5, 100, "A"),
        ("CNMG", "WS-MAIN", 5, 100, "a"),
    ]
    with pytest.raises(ImportRefused) as refused:
        load(accountant, *rows)
    assert refused.value.errors == [
        "Row 2: There is no item NOPE.",
        "Row 3: IM-QUAR is not an active main store.",
        "Row 4: The quantity must be more than 0.",
        "Row 5: The cost per unit is not a number.",
        "Row 6: The quantity can have at most 3 decimal places.",
        "Row 8: the same item, store and lot as row 7.",
    ]
    assert not OpeningStock.objects.exists()


def test_only_the_accountant_loads_and_not_twice(accountant, stores, resin, cutter):
    with pytest.raises(ImportRefused, match="Only the Accountant"):
        load(stores)
    load(accountant)
    with pytest.raises(ImportRefused, match="already on opening stock"):
        load(accountant)


def test_a_count_date_in_the_future_is_refused(accountant, resin, cutter):
    with pytest.raises(ImportRefused, match="future"):
        opening.load(accountant, None, content=sheet(*GOOD), count_date=TODAY + timedelta(days=1))


def test_loading_again_replaces_the_draft(accountant, resin, cutter):
    made, _ = load(accountant)
    made, _ = load(accountant, ("PP-H-25", "IM-MAIN", 100, 400, ""), current=made)
    assert [(x.item.code, str(x.quantity)) for x in made.lines.all()] == [("PP-H-25", "100.000")]
    assert OpeningStock.objects.count() == 1


# --- Approval -------------------------------------------------------------------------------


def test_the_director_approves_and_the_stock_goes_in(accountant, director, resin, cutter):
    made = opening.submit(accountant, load(accountant)[0])
    assert made.status == "awaiting_approval"
    with pytest.raises(OpeningError, match="approved by the Director"):
        opening.approve(accountant, made)
    made = opening.approve(director, made, "Counted with the auditors")
    made.refresh_from_db()
    assert made.status == "posted"
    entry = made.journal_entry
    assert (entry.source_type, entry.entry_date) == ("opening_stock", TODAY)
    lines = [
        (x.account.number, str(x.debit), str(x.credit), x.division.code) for x in entry.lines.all()
    ]
    equity = Account.objects.get(system_role="opening_balance_equity").number
    assert lines == [
        ("1210", "525210.00", "0.00", "IM"),
        ("1240", "74000.00", "0.00", "WS"),
        (equity, "0.00", "525210.00", "IM"),
        (equity, "0.00", "74000.00", "WS"),
    ]
    moves = StockMovement.objects.order_by("pk")
    assert [(m.kind, m.store.code, str(m.quantity), str(m.value)) for m in moves] == [
        ("opening", "IM-MAIN", "1250.500", "525210.00"),
        ("opening", "WS-MAIN", "40.000", "74000.00"),
    ]
    assert stock.average_costs(StockMovement.objects.all())[resin.pk] == Decimal("420.0000")
    # Opening stock is only for stock that has not moved yet.
    with pytest.raises(ImportRefused, match="already moved"):
        load(accountant, ("PP-H-25", "IM-MAIN", 1, 1, "X"))


def test_returned_and_rejected(accountant, director, resin, cutter):
    made = opening.submit(accountant, load(accountant)[0])
    made = opening.send_back(director, made, "Recount the resin")
    assert made.status == "draft"
    made = opening.submit(accountant, made)
    made = opening.reject(director, made, "Wrong costs")
    assert made.status == "rejected"
    assert not JournalEntry.objects.exists()
    load(accountant)  # a rejected opening stock frees its items again


def test_the_database_refuses_changes_once_sent(accountant, director, resin, cutter):
    made = opening.submit(accountant, load(accountant)[0])
    with pytest.raises(DatabaseError, match="sent for approval"):
        with transaction.atomic():
            OpeningStockLine.objects.filter(opening=made).update(quantity="1")
    with pytest.raises(DatabaseError, match="cannot be deleted"):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM inventory_openingstock WHERE id = %s", [made.pk])
    opening.approve(director, made)
    with pytest.raises(DatabaseError, match="for good"):
        with transaction.atomic():
            OpeningStock.objects.filter(pk=made.pk).update(status="draft")


def test_only_the_author_deletes_a_draft(accountant, resin, cutter):
    made, _ = load(accountant)
    other = person("accountant2@sml.lk", "accountant", all_divisions=True)
    with pytest.raises(OpeningError, match="Only the person who made"):
        opening.delete(other, made)
    opening.delete(accountant, made)
    assert not OpeningStock.objects.exists()


# --- API -------------------------------------------------------------------------------------


def test_the_api(accountant, director, stores, resin, cutter):
    client = as_user(accountant)
    upload = {
        "file": SimpleUploadedFile("count.xlsx", sheet(*GOOD)),
        "count_date": TODAY.isoformat(),
        "dry_run": "1",
    }
    checked = client.post("/api/v1/opening-stock/", upload, format="multipart")
    assert checked.status_code == 200, checked.content
    assert checked.json() == {"dry_run": True, "rows": 2, "value": "599210.00"}
    upload["file"] = SimpleUploadedFile("count.xlsx", sheet(*GOOD))
    upload["dry_run"] = ""
    made = client.post("/api/v1/opening-stock/", upload, format="multipart")
    assert made.status_code == 201, made.content
    pk = made.json()["id"]
    bad = client.post(
        "/api/v1/opening-stock/",
        {
            "file": SimpleUploadedFile("x.xlsx", sheet(("NOPE", "IM-MAIN", 1, 1, ""))),
            "count_date": TODAY.isoformat(),
        },
        format="multipart",
    )
    assert bad.status_code == 400
    assert bad.json()["errors"] == ["Row 2: There is no item NOPE."]
    assert as_user(stores).post(f"/api/v1/opening-stock/{pk}/submit/").status_code == 400
    assert client.post(f"/api/v1/opening-stock/{pk}/submit/").status_code == 200
    boss = as_user(director)
    assert [o["id"] for o in boss.get("/api/v1/opening-stock/?waiting=me").json()] == [pk]
    approved = boss.post(f"/api/v1/opening-stock/{pk}/approve/", {"comment": "OK"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "posted"
    template = client.get("/api/v1/opening-stock/template/")
    assert template.status_code == 200
    moves = as_user(stores).get("/api/v1/stock/movements/").json()
    assert {m["opening"]["number"] for m in moves} == {approved.json()["number"]}
    assert as_user(person("clerk@sml.lk", "clerk")).get("/api/v1/opening-stock/").status_code == 403
