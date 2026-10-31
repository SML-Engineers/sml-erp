"""Items and stores (backlog P16-03, spec 5A.3, 6A)."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError, IntegrityError
from openpyxl import Workbook, load_workbook

from apps.core.models import AuditEvent
from apps.inventory import items
from apps.inventory.models import Item, Store
from apps.masters.services import MastersError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db


@pytest.fixture
def buyer():
    return person("buyer@sml.lk", "purchasing_officer", all_divisions=True)


@pytest.fixture
def stores():
    return person("stores@sml.lk", "store_supervisor", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


RESIN = {
    "code": "pp-h-white",
    "name": "Polypropylene homopolymer, white",
    "category": "raw_material",
    "unit": "kg",
    "package_type": "bag",
}


@pytest.fixture
def resin(buyer):
    return items.create_item(buyer, RESIN)


# --- Items ------------------------------------------------------------------------------


def test_the_buyer_adds_an_item_with_its_category_account(resin):
    assert resin.code == "PP-H-WHITE"
    assert (resin.unit, resin.package_type, resin.is_stock) == ("kg", "bag", True)
    assert resin.inspection_required is True
    assert resin.inventory_account.number == "1210"  # raw materials
    assert AuditEvent.objects.filter(event="item_created").exists()


def test_a_consumable_goes_to_consumables_and_a_non_stock_item_has_no_stock_details(stores):
    gloves = items.create_item(
        stores, {"code": "GLV-01", "name": "Cotton gloves", "category": "consumable"}
    )
    assert gloves.inventory_account.number == "1240"
    service = items.create_item(
        stores,
        {
            "code": "CAL-01",
            "name": "Calibration service",
            "category": "consumable",
            "is_stock": False,
            "package_type": "bag",
        },
    )
    assert service.inventory_account is None
    assert (service.package_type, service.inspection_required) == ("none", False)


def test_only_the_accountant_chooses_accounts(buyer, accountant, resin):
    with pytest.raises(MastersError, match="Only the Accountant"):
        items.update_item(buyer, resin, {"inventory_account": "1240"})
    changed = items.update_item(accountant, resin, {"inventory_account": "1240"})
    assert changed.inventory_account.number == "1240"
    with pytest.raises(MastersError, match="cannot be the inventory account"):
        items.update_item(accountant, resin, {"inventory_account": "1010"})  # cash
    # The buyer can still change other details, keeping the Accountant's choice.
    renamed = items.update_item(buyer, changed, {"name": "PP homopolymer, white"})
    assert renamed.inventory_account.number == "1240"


@pytest.mark.parametrize(
    "values, why",
    [
        ({"code": "", "name": "X", "category": "spare"}, "code"),
        ({"code": "A B", "name": "X", "category": "spare"}, "code"),
        ({"code": "X1", "name": "", "category": "spare"}, "name"),
        ({"code": "X1", "name": "X", "category": "food"}, "category"),
        ({"code": "X1", "name": "X", "category": "spare", "unit": "bucket"}, "unit"),
        ({"code": "X1", "name": "X", "category": "spare", "division": "ZZ"}, "division"),
        ({"code": "X1", "name": "X", "category": "spare", "material": "NOPE"}, "material"),
    ],
)
def test_wrong_details_are_refused(buyer, values, why):
    with pytest.raises(MastersError, match=why):
        items.create_item(buyer, values)


def test_codes_are_unique_and_fixed_once_used(buyer, resin):
    with pytest.raises(MastersError, match="already an item"):
        items.create_item(buyer, {**RESIN, "name": "Other"})
    items.update_item(buyer, resin, {"code": "PP-H-WHT"})  # not used yet: allowed
    items.mark_used(resin)
    resin.refresh_from_db()
    with pytest.raises(MastersError, match="its code cannot change"):
        items.update_item(buyer, resin, {"code": "PP-1"})
    with pytest.raises(DatabaseError, match="code cannot change"), transaction.atomic():
        Item.objects.filter(pk=resin.pk).update(code="PP-2")
    with pytest.raises(MastersError, match="deactivate it instead"):
        items.delete_item(buyer, resin)
    with pytest.raises(DatabaseError, match="cannot be deleted"), transaction.atomic():
        Item.objects.filter(pk=resin.pk).delete()


def test_deactivating_needs_a_reason(buyer, resin):
    with pytest.raises(MastersError, match="reason"):
        items.set_active(buyer, resin, False)
    assert items.set_active(buyer, resin, False, reason="Grade discontinued").is_active is False


def test_people_without_purchasing_stores_or_accounts_cannot_change_items(resin):
    cashier = person("cashier@sml.lk", "cashier", all_divisions=True)
    with pytest.raises(MastersError, match="cannot"):
        items.create_item(cashier, {**RESIN, "code": "X2"})
    assert as_user(cashier).get("/api/v1/items/").status_code == 403


# --- Stores -----------------------------------------------------------------------------


def test_each_production_division_has_its_three_stores():
    codes = set(Store.objects.values_list("code", flat=True))
    assert {"WS-MAIN", "WS-QUAR", "WS-REJ", "IM-MAIN", "IM-QUAR", "IM-REJ"} <= codes
    assert not Store.objects.filter(division__code="HO").exists()


def test_the_admin_adds_main_stores_but_one_quarantine_per_division(admin, buyer):
    store = items.create_store(
        admin, {"code": "im-resin", "name": "Resin store", "division": "IM", "kind": "main"}
    )
    assert store.code == "IM-RESIN"
    with pytest.raises(MastersError, match="already has its quarantine"):
        items.create_store(
            admin, {"code": "IM-Q2", "name": "Q2", "division": "IM", "kind": "quarantine"}
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        Store.objects.create(code="IM-Q3", name="Q3", division=store.division, kind="quarantine")
    with pytest.raises(MastersError, match="production division"):
        items.create_store(admin, {"code": "HO-1", "name": "Office", "division": "HO"})
    with pytest.raises(MastersError, match="Only the Admin"):
        items.create_store(buyer, {"code": "WS-2", "name": "Store 2", "division": "WS"})
    quarantine = Store.objects.get(code="IM-QUAR")
    with pytest.raises(MastersError, match="needs its quarantine"):
        items.update_store(admin, quarantine, {"is_active": False}, reason="Not used")
    items.update_store(admin, store, {"is_active": False}, reason="Merged into main")


# --- API and Excel ----------------------------------------------------------------------


def test_the_api_lists_searches_adds_and_changes_items(buyer, resin):
    client = as_user(buyer)
    options = client.get("/api/v1/items/options/").json()
    assert options["can_enter"] and not options["can_set_accounts"]
    assert {"number": "1210", "name": "Raw materials"} in options["inventory_accounts"]
    made = client.post(
        "/api/v1/items/",
        {"code": "INS-M6", "name": "Brass insert M6", "category": "bought_out"},
        format="json",
    )
    assert made.status_code == 201, made.json()
    found = client.get("/api/v1/items/?q=white").json()
    assert [i["code"] for i in found] == ["PP-H-WHITE"]
    changed = client.patch(f"/api/v1/items/{resin.pk}/", {"name": "PP white"}, format="json").json()
    assert changed["name"] == "PP white" and changed["inventory_account"]["number"] == "1210"
    off = client.post(f"/api/v1/items/{resin.pk}/active/", {"active": False}, format="json")
    assert off.status_code == 400
    assert client.delete(f"/api/v1/items/{made.json()['id']}/").status_code == 204


def book(*rows):
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheet = workbook.create_sheet("Items")
    sheet.append(items.COLUMNS)
    for row in rows:
        values = dict.fromkeys(items.COLUMNS, None) | row
        sheet.append([values[c] for c in items.COLUMNS])
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def upload(user, content, reason="Item list from the stores register", dry_run=False):
    return as_user(user).post(
        "/api/v1/items/import/",
        {
            "file": SimpleUploadedFile("items.xlsx", content),
            "reason": reason,
            "dry_run": "1" if dry_run else "",
        },
        format="multipart",
    )


def test_items_are_exported_and_imported_all_or_nothing(stores, resin):
    exported = as_user(stores).get("/api/v1/items/export/")
    sheet = load_workbook(io.BytesIO(exported.content))["Items"]
    first = [c.value for c in sheet[2]]
    assert (first[0], first[1], first[3], first[4]) == (
        "PP-H-WHITE",
        "Polypropylene homopolymer, white",
        "Raw material",
        "kg",
    )
    rows = (
        {
            "Code": "EN8-40",
            "Name": "EN8 round bar 40 mm",
            "Category": "Raw material",
            "Unit": "kg",
            "Arrives as": "Bars, rods, tubes",
        },
        {"Code": "PP-H-WHITE", "Name": "PP white (renamed)", "Category": "raw_material"},
    )
    checked = upload(stores, book(*rows), dry_run=True)
    assert checked.json() == {"dry_run": True, "created": 1, "updated": 1}
    assert not Item.objects.filter(code="EN8-40").exists()
    assert upload(stores, book(*rows)).json()["created"] == 1
    assert Item.objects.get(code="EN8-40").package_type == "bar"
    refused = upload(
        stores,
        book(
            {"Code": "OK-1", "Name": "Fine", "Category": "Spare part"},
            {"Code": "BAD 1", "Name": "Bad code", "Category": "Spare part"},
            {"Code": "BAD-2", "Name": "Bad category", "Category": "Food"},
        ),
    )
    assert refused.status_code == 400
    assert [e.split(":")[0] for e in refused.json()["errors"]] == ["Row 3", "Row 4"]
    assert not Item.objects.filter(code="OK-1").exists()
