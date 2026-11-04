"""Stock issues, returns, adjustments, write-offs and counts (backlog P2-18)."""

from decimal import Decimal

import pytest
from django.db import transaction
from django.db.models import Sum
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.inventory import adjustments, issues, items
from apps.inventory.adjustments import LineInput
from apps.inventory.issues import IssueLine
from apps.inventory.models import StockAdjustment, StockCount, StockIssue, StockMovement, Store
from apps.inventory.stock import StockError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()
D = Decimal


@pytest.fixture
def stores():
    return person("stores@sml.lk", "store_supervisor", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def main():
    return Store.objects.get(code="IM-MAIN")


@pytest.fixture
def resin(accountant):
    """Two lots in IM-MAIN: A 100 kg at 100.00 (older), B 50 kg at 120.00. Average 106.6667."""
    item = items.create_item(
        accountant,
        {
            "code": "PP-H110",
            "name": "Polypropylene H110",
            "category": "raw_material",
            "unit": "kg",
            "inventory_account": "1210",
        },
    )
    for lot, quantity, value in (("A", "100", "10000.00"), ("B", "50", "6000.00")):
        StockMovement.objects.create(
            item=item,
            store=main(),
            division=main().division,
            lot_no=lot,
            kind="opening",
            movement_date=TODAY,
            quantity=D(quantity),
            value=D(value),
            created_by=accountant,
        )
    return item


def on_hand(item, lot=None):
    rows = StockMovement.objects.filter(item=item, store=main())
    if lot:
        rows = rows.filter(lot_no=lot)
    found = rows.aggregate(q=Sum("quantity"), v=Sum("value"))
    return found["q"] or D("0"), found["v"] or D("0")


def entry_lines(entry):
    return sorted(
        (x.account.number, x.division.code if x.division else None, x.debit, x.credit)
        for x in entry.lines.select_related("account", "division")
    )


def take(user, item, quantity, **extra):
    return issues.issue(
        user, store=main(), issue_date=TODAY, lines=[IssueLine(item, quantity, **extra)]
    )


# --- Issues and returns ------------------------------------------------------------------


def test_an_issue_takes_the_oldest_lot_first_at_the_average_cost(stores, resin):
    made = take(stores, resin, "120")
    assert made.number.startswith(f"MI{TODAY:%y%m}")
    assert [(x.lot_no, x.quantity, x.value) for x in made.lines.order_by("line_no")] == [
        ("A", D("100.000"), D("10666.67")),
        ("B", D("20.000"), D("2133.33")),
    ]
    assert entry_lines(made.journal_entry) == [
        ("1210", "IM", D("0"), D("12800.00")),
        ("5010", "IM", D("12800.00"), D("0")),
    ]
    assert on_hand(resin) == (D("30.000"), D("3200.00"))


def test_the_last_of_an_item_takes_the_value_left(stores, resin):
    take(stores, resin, "120")
    last = take(stores, resin, "30")
    assert last.total_value == D("3200.00")
    assert on_hand(resin) == (D("0"), D("0"))


def test_not_more_than_the_store_holds(stores, resin):
    with pytest.raises(StockError, match="only 150.000 kg"):
        take(stores, resin, "151")
    with pytest.raises(StockError, match="lot Z"):
        take(stores, resin, "1", lot_no="Z")


def test_material_comes_back_against_its_issue(stores, resin):
    made = take(stores, resin, "120")
    line_b = made.lines.get(lot_no="B")
    back = issues.give_back(stores, made, return_date=TODAY, lines=[(line_b, "20")])
    assert (back.kind, back.total_value) == ("return", D("2133.33"))
    assert on_hand(resin, "B") == (D("50.000"), D("6000.00") - D("2133.33") + D("2133.33"))
    with pytest.raises(StockError, match="only 0.000 was issued and not yet returned"):
        issues.give_back(stores, made, return_date=TODAY, lines=[(line_b, "1")])


def test_an_issue_never_changes(stores, resin):
    made = take(stores, resin, "10")
    with pytest.raises(DatabaseError), transaction.atomic():
        StockIssue.objects.filter(pk=made.pk).update(purpose="changed")


# --- Adjustments and write-offs ------------------------------------------------------------


def test_a_write_off_waits_for_the_director(stores, director, resin):
    with pytest.raises(StockError, match="only takes stock out"):
        adjustments.create(
            stores, store=main(), kind="write_off", reason="Wet", lines=[LineInput(resin, "5", "A")]
        )
    draft = adjustments.create(
        stores,
        store=main(),
        kind="write_off",
        reason="Bags torn and wet",
        lines=[LineInput(resin, "-10", "A")],
    )
    adjustments.submit(stores, draft)
    assert on_hand(resin, "A")[0] == D("100.000")  # nothing moves before approval
    with pytest.raises(StockError):
        adjustments.approve(stores, draft)
    adjustments.approve(director, draft, "OK")
    draft.refresh_from_db()
    assert (draft.status, draft.total_value) == ("posted", D("-1066.67"))
    assert entry_lines(draft.journal_entry) == [
        ("1210", "IM", D("0"), D("1066.67")),
        ("5070", "IM", D("1066.67"), D("0")),
    ]
    assert on_hand(resin, "A")[0] == D("90.000")
    with pytest.raises(DatabaseError, match="never changes"), transaction.atomic():
        StockAdjustment.objects.filter(pk=draft.pk).update(reason="changed")


def test_stock_found_of_an_item_never_held_needs_its_cost(stores, director, accountant):
    item = items.create_item(
        accountant,
        {
            "code": "MB-RED",
            "name": "Red masterbatch",
            "category": "raw_material",
            "unit": "kg",
            "inventory_account": "1210",
        },
    )
    draft = adjustments.create(
        stores,
        store=main(),
        kind="adjustment",
        reason="Found in the old store",
        lines=[LineInput(item, "5", "OLD")],
    )
    adjustments.submit(stores, draft)
    with pytest.raises(StockError, match="type the cost"):
        adjustments.approve(director, draft)
    found = adjustments.create(
        stores,
        store=main(),
        kind="adjustment",
        reason="Found",
        lines=[LineInput(item, "5", "OLD", unit_cost="300")],
    )
    adjustments.submit(stores, found)
    adjustments.approve(director, found)
    assert StockMovement.objects.filter(item=item).aggregate(v=Sum("value"))["v"] == D("1500.00")


# --- Stock counts --------------------------------------------------------------------------


def test_a_count_sends_its_differences_to_the_director(stores, director, resin):
    count = adjustments.start_count(stores, store=main())
    assert sorted((x.lot_no, x.system_quantity) for x in count.lines.all()) == [
        ("A", D("100.000")),
        ("B", D("50.000")),
    ]
    adjustments.enter_counts(stores, count, [(resin, "A", "98")])
    with pytest.raises(StockError, match="not counted yet"):
        adjustments.submit_count(stores, count)
    adjustments.enter_counts(stores, count, [(resin, "B", "50")])
    adjustments.submit_count(stores, count)
    count.refresh_from_db()
    adjustment = count.adjustment
    assert (count.status, adjustment.kind, adjustment.status) == (
        "submitted",
        "count",
        "awaiting_approval",
    )
    assert [(x.lot_no, x.quantity) for x in adjustment.lines.all()] == [("A", D("-2.000"))]
    adjustments.approve(director, adjustment)
    assert on_hand(resin, "A")[0] == D("98.000")
    with pytest.raises(DatabaseError, match="closed"), transaction.atomic():
        count.lines.filter(lot_no="A").update(counted_quantity=D("1"))


def test_a_count_with_no_differences_is_agreed(stores, resin):
    count = adjustments.start_count(stores, store=main())
    adjustments.enter_counts(stores, count, [(resin, "A", "100"), (resin, "B", "50")])
    assert adjustments.submit_count(stores, count).status == StockCount.Status.AGREED
    assert not StockAdjustment.objects.exists()


# --- The API -------------------------------------------------------------------------------


def test_issuing_through_the_api(stores, resin):
    client = as_user(stores)
    lots = client.get(f"/api/v1/stock-issues/lots/?item={resin.pk}&store={main().pk}").json()
    assert [x["lot_no"] for x in lots["lots"]] == ["A", "B"]
    made = client.post(
        "/api/v1/stock-issues/",
        {
            "store": main().pk,
            "issue_date": str(TODAY),
            "lines": [{"item": resin.pk, "quantity": "5"}],
        },
        format="json",
    )
    assert made.status_code == 201, made.content
    assert made.json()["lines"][0]["lot_no"] == "A"
