"""Package-by-package receiving (backlog P16-07, spec 6A.2)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core.models import Division
from apps.inventory import items, labels, receipts
from apps.inventory.items import ItemError
from apps.inventory.models import ReceiptPackage
from apps.inventory.packages import PackageInput
from apps.inventory.receipts import LineInput, ReceiptError
from apps.masters.models import Currency, Supplier
from apps.purchasing import orders
from apps.purchasing.orders import LineInput as POLine

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


@pytest.fixture
def buyer():
    return person("buyer@sml.lk", "purchasing_officer", all_divisions=True)


@pytest.fixture
def stores():
    return person("stores@sml.lk", "store_supervisor", divisions=("IM", "WS"))


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def item(buyer, code, unit, package_type, **extra):
    return items.create_item(
        buyer,
        {
            "code": code,
            "name": code.title(),
            "category": "raw_material",
            "unit": unit,
            "package_type": package_type,
            **extra,
        },
    )


def approved_po(buyer, director, *lines, division="IM"):
    supplier = Supplier.objects.get_or_create(
        code="S0001", defaults={"name": "SDD Polymer", "currency": Currency.objects.get(code="LKR")}
    )[0]
    order = orders.create(
        buyer,
        supplier=supplier,
        division=Division.objects.get(code=division),
        delivery_date=TODAY + timedelta(days=7),
        lines=[POLine(i, qty, "100") for i, qty in lines],
    )
    orders.submit(buyer, order)
    return orders.approve(director, order)


@pytest.fixture
def resin(buyer):
    return item(buyer, "PP-H-WHITE", "kg", "bag", package_tare="0.1")


@pytest.fixture
def grn(buyer, director, stores, resin):
    return receipts.create(stores, approved_po(buyer, director, (resin, "75")))


def bag(gross=None, declared="25", **extra):
    return PackageInput(gross_weight=gross, declared_weight=declared, **extra)


# --- Bags ------------------------------------------------------------------------------------


def test_bags_are_weighed_one_by_one(grn, stores):
    line = receipts.set_packages(
        stores, grn, 1, [bag("25.15", supplier_lot="L-881"), bag("25.10"), bag("24.80")]
    )
    rows = list(line.packages.all())
    assert [p.lot_no for p in rows] == [
        f"{grn.number}-1-001",
        f"{grn.number}-1-002",
        f"{grn.number}-1-003",
    ]
    assert [p.net_weight for p in rows] == [Decimal("25.05"), Decimal("25.00"), Decimal("24.70")]
    assert rows[0].tare_weight == Decimal("0.1")  # the item's usual bag weight
    assert line.received_quantity == Decimal("74.75") and line.damaged_quantity == 0
    assert line.weight_tolerance_pct == Decimal("0.5")


def test_a_bag_outside_the_tolerance_is_highlighted(grn, stores):
    from apps.inventory import packages

    line = receipts.set_packages(stores, grn, 1, [bag("25.15"), bag("24.80")])
    first, second = line.packages.all()
    assert packages.check(first, line)["variance_pct"] == Decimal("0.20")
    assert not packages.check(first, line)["outside"]
    assert packages.check(second, line)["variance_pct"] == Decimal("-1.20")
    assert packages.check(second, line)["outside"]


def test_fast_entry_waits_for_every_weight_before_confirming(grn, stores):
    line = receipts.set_packages(stores, grn, 1, [bag() for _ in range(3)])
    assert line.packages.count() == 3 and line.received_quantity == 0
    with pytest.raises(ReceiptError, match="at least one line"):
        receipts.confirm(stores, grn)  # nothing weighed yet
    receipts.set_packages(stores, grn, 1, [bag("25.1"), bag("25.1"), bag()])
    with pytest.raises(ReceiptError, match="package 3: enter the gross weight"):
        receipts.confirm(stores, grn)


def test_a_bag_item_cannot_be_confirmed_without_its_bags(grn, stores):
    with pytest.raises(ReceiptError, match="enter the bags received, one by one"):
        receipts.confirm(stores, grn)


def test_damaged_bags_count_as_damaged(grn, stores):
    line = receipts.set_packages(stores, grn, 1, [bag("25.1"), bag("25.1", damaged=True)])
    assert (line.received_quantity, line.damaged_quantity, line.good_quantity) == (
        Decimal("50.0"),
        Decimal("25.0"),
        Decimal("25.0"),
    )


@pytest.mark.parametrize(
    "given, why",
    [
        (bag("0.05"), "more than the tare"),
        (bag("x"), "gross weight is not a number"),
        (bag("25.0001"), "3 decimal places"),
        (bag("25", tare_weight="-1"), "cannot be negative"),
    ],
)
def test_wrong_weights_are_refused(grn, stores, given, why):
    with pytest.raises(ReceiptError, match=f"Package 1: .*{why}"):
        receipts.set_packages(stores, grn, 1, [given])


def test_saving_the_grn_keeps_the_packages_and_lot_numbers(grn, stores):
    line = receipts.set_packages(stores, grn, 1, [bag("25.1"), bag("25.1")])
    receipts.save(stores, grn, lines=[LineInput(line.po_line_id, "999")], delivery_note_no="DN-1")
    line.refresh_from_db()
    assert line.received_quantity == Decimal("50.0")  # the bags decide, not the typed figure
    assert [p.lot_no for p in line.packages.all()][-1] == f"{grn.number}-1-002"


def test_packages_never_change_after_confirming(grn, stores):
    receipts.set_packages(stores, grn, 1, [bag("25.1"), bag("25.1")])
    receipts.confirm(stores, grn)
    with pytest.raises(ReceiptError, match="draft"):
        receipts.set_packages(stores, grn, 1, [bag("1")])
    with pytest.raises(DatabaseError, match="cannot change"), transaction.atomic():
        ReceiptPackage.objects.filter(line__receipt=grn).update(gross_weight=Decimal("1"))
    with pytest.raises(DatabaseError, match="cannot change"), transaction.atomic():
        ReceiptPackage.objects.filter(line__receipt=grn).delete()


def test_only_items_received_by_package_take_packages(buyer, director, stores):
    plain = item(buyer, "GREASE", "kg", "none")
    grn = receipts.create(stores, approved_po(buyer, director, (plain, "5")))
    with pytest.raises(ReceiptError, match="not received by package"):
        receipts.set_packages(stores, grn, 1, [bag("5")])


# --- Bars, plates, coils, boxes --------------------------------------------------------------


def test_bars_by_length_are_checked_against_kg_per_metre(buyer, director, stores):
    from apps.inventory import packages

    bar = item(buyer, "EN8-40", "m", "bar", standard_kg_per_m="9.86")
    grn = receipts.create(stores, approved_po(buyer, director, (bar, "60"), division="WS"))
    line = receipts.set_packages(
        stores,
        grn,
        1,
        [
            PackageInput(supplier_lot="H-5521", pieces="10", piece_length="3", gross_weight="296"),
            PackageInput(supplier_lot="H-5521", pieces="10", piece_length="3", gross_weight="300"),
        ],
    )
    first, second = line.packages.all()
    assert line.received_quantity == Decimal("60.000")  # 2 bundles × 10 bars × 3 m
    assert packages.check(first, line)["actual"] == Decimal("9.8667")
    assert not packages.check(first, line)["outside"]
    assert packages.check(second, line)["outside"]  # 10.00 kg/m is 1.42% heavy


def test_plates_are_checked_against_their_theoretical_weight(buyer, director, stores):
    from apps.inventory import packages

    plate = item(buyer, "MS-PLATE-10", "kg", "plate", density="7.85")
    grn = receipts.create(stores, approved_po(buyer, director, (plate, "40"), division="WS"))
    line = receipts.set_packages(
        stores,
        grn,
        1,
        [PackageInput(length_mm="1000", width_mm="500", thickness_mm="10", gross_weight="39.5")],
    )
    found = packages.check(line.packages.get(), line)
    assert (found["expected"], found["variance_pct"], found["outside"]) == (
        Decimal("39.250"),
        Decimal("0.64"),
        True,
    )


def test_coils_and_boxes(buyer, director, stores):
    coil = item(buyer, "GI-COIL-0.5", "kg", "coil")
    inserts = item(buyer, "M6-INSERT", "pcs", "counted")
    grn = receipts.create(
        stores, approved_po(buyer, director, (coil, "500"), (inserts, "2000"), division="WS")
    )
    line = receipts.set_packages(
        stores, grn, 1, [PackageInput(gross_weight="512", tare_weight="12")]
    )
    assert line.received_quantity == 500
    line = receipts.set_packages(stores, grn, 2, [PackageInput(pieces="500") for _ in range(4)])
    assert line.received_quantity == 2000
    assert receipts.confirm(stores, grn).status == "confirmed"


# --- Labels and the API ---------------------------------------------------------------------


def test_one_label_per_package(grn, stores):
    receipts.set_packages(stores, grn, 1, [bag("25.1"), bag("25.1"), bag("25.1")])
    pdf = labels.render(grn)
    assert pdf.startswith(b"%PDF") and b"/Count 3" in pdf


def test_the_api_saves_packages_and_prints_labels(grn, stores):
    client = as_user(stores)
    saved = client.put(
        f"/api/v1/goods-receipts/{grn.pk}/lines/1/packages/",
        {
            "packages": [
                {"gross_weight": "25.15", "declared_weight": "25", "supplier_lot": "L-1"},
                {"gross_weight": "24.80", "declared_weight": "25", "damaged": True},
            ]
        },
        format="json",
    )
    assert saved.status_code == 200, saved.json()
    line = saved.json()["lines"][0]
    assert line["received_quantity"] == "49.750" and line["damaged_quantity"] == "24.700"
    assert line["package_totals"]["outside"] == 1
    assert line["packages"][1]["check"]["variance_pct"] == "-1.20"
    printed = client.get(f"/api/v1/goods-receipts/{grn.pk}/labels/?line=1")
    assert printed.status_code == 200 and printed["Content-Type"] == "application/pdf"
    refused = client.put(
        f"/api/v1/goods-receipts/{grn.pk}/lines/1/packages/",
        {"packages": [{"gross_weight": "0.01"}]},
        format="json",
    )
    assert refused.status_code == 400 and "tare" in refused.json()["detail"]


# --- Item settings -----------------------------------------------------------------------------


def test_items_keep_the_receiving_checks(buyer, resin):
    assert (resin.package_tare, resin.weight_tolerance_pct) == (Decimal("0.1"), Decimal("0.5"))
    changed = items.update_item(buyer, resin, {"weight_tolerance_pct": "1", "density": ""})
    assert changed.weight_tolerance_pct == 1 and changed.density is None
    with pytest.raises(ItemError, match="up to 100"):
        items.update_item(buyer, resin, {"weight_tolerance_pct": "150"})
    with pytest.raises(ItemError, match="usual tare cannot be negative"):
        items.update_item(buyer, resin, {"package_tare": "-1"})
