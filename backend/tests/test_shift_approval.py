"""Approving shift reports and corrections (backlog P3-09): the Production Manager approves or
returns a submitted report (never the submitter); approval backflushes the order's materials
at their cost, puts the good pieces and the regrind into stock, posts the journal and counts
the mould's shots; a shortage stops it. After the entry time a correction is asked for, kept
with the original, approved by the Production Manager or the Director (never the person who
asked), and either reopens a draft or reverses an approved report's postings."""

from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.models import Sum
from django.db.utils import DatabaseError

from apps.accounting.models import Account, JournalEntry
from apps.core.models import ApprovalState
from apps.inventory.models import Item, StockMovement, Store
from apps.production import orders, shift_approval, shift_reports
from apps.production.models import Mould, ProductionReceipt, ShiftCorrection, ShiftReport
from apps.production.shift_reports import ShiftReportError

from .test_access import as_user, person
from .test_production_orders import cap, for_stock, manager, planner  # noqa: F401
from .test_shift_reports import TODAY, at, clock, press, run, supervisor  # noqa: F401

pytestmark = pytest.mark.django_db
URL = "/api/v1/shift-reports/"


def put_in(code, quantity, value, lot, user):
    store = Store.objects.get(code="IM-MAIN")
    StockMovement.objects.create(
        item=Item.objects.get(code=code),
        store=store,
        division=store.division,
        lot_no=lot,
        kind="opening",
        movement_date=TODAY - timedelta(days=10),
        quantity=D(quantity),
        value=D(value),
        created_by=user,
    )


def on_hand(code, lot=None):
    found = StockMovement.objects.filter(item__code=code, store__code="IM-MAIN")
    if lot:
        found = found.filter(lot_no=lot)
    totals = found.aggregate(q=Sum("quantity"), v=Sum("value"))
    return totals["q"] or D("0"), totals["v"] or D("0")


@pytest.fixture
def ready(clock, planner, manager, cap, supervisor, press):  # noqa: F811
    """A released cap order, stock at cost, and a submitted report: 500 shots × 8 caps,
    40 rejects, 1.2 kg of regrind."""
    Item.objects.filter(category="raw_material").update(
        inventory_account=Account.objects.get(name="Raw materials")
    )
    Item.objects.filter(code__in=["CAP-28", "BAG-1K"]).update(
        inventory_account=Account.objects.get(name="Finished goods")
    )
    put_in("PP-H", "100", "50000", "L1", planner)  # LKR 500 a kg
    put_in("MB-BLK", "10", "15000", "M1", planner)  # LKR 1,500 a kg
    put_in("BAG-1K", "100", "2000", "B1", planner)  # LKR 20 a bag
    order = orders.release(planner, for_stock(planner))
    report = shift_reports.open_report(
        supervisor, {"section": "IM-MLD", "shift": "G", "day": TODAY.isoformat()}
    )
    shift_reports.save(
        supervisor,
        report,
        {
            "runs": [run(order, material_lot="L1")],
            "materials": [{"kind": "regrind", "item": "PP-H", "quantity": "1.2"}],
        },
    )
    shift_reports.submit(supervisor, report)
    report.refresh_from_db()
    return {"order": order, "report": report}


def test_the_production_manager_approves_and_stock_moves(ready, manager, supervisor):  # noqa: F811
    report, order = ready["report"], ready["order"]
    assert ApprovalState.objects.get(document_type="shift_report", document_id=report.pk)
    # The supervisor who submitted cannot approve.
    with pytest.raises(ShiftReportError):
        shift_approval.decide(supervisor, report, "approve")
    seen = as_user(manager).get(f"{URL}{report.pk}/").json()
    assert seen["can_decide"] is True and seen["can_ask"] is False
    done = as_user(manager).post(f"{URL}{report.pk}/decide/", {"action": "approve"}, format="json")
    assert done.status_code == 200, done.json()
    body = done.json()
    assert body["status"] == "approved" and body["approved_by"] == "Pm"
    report.refresh_from_db()
    # Backflush for 4,000 moulded caps (without the BOM's 5% allowance): 18 kg of PP,
    # 0.36 kg of black; 3.96 bags for the 3,960 good caps.
    issued = {x.item.code: (x.quantity, x.value) for x in report.stock_issue.lines.all()}
    assert issued == {
        "PP-H": (D("18"), D("9000")),
        "MB-BLK": (D("0.36"), D("540")),
        "BAG-1K": (D("3.96"), D("79.20")),
    }
    assert report.stock_issue.lines.get(item__code="PP-H").lot_no == "L1"
    assert body["stock_issue"] == report.stock_issue.number
    # The good caps at their material less the regrind credit (1.2 kg at LKR 500).
    caps = ProductionReceipt.objects.get(item__code="CAP-28")
    assert (caps.quantity, caps.material_value, caps.regrind_credit, caps.value) == (
        D("3960"),
        D("9619.20"),
        D("600"),
        D("9019.20"),
    )
    assert on_hand("CAP-28", order.number) == (D("3960"), D("9019.20"))
    assert on_hand("PP-H", f"RG{report.pk:06d}") == (D("1.2"), D("600"))
    assert on_hand("PP-H") == (D("83.2"), D("41600"))
    entry = report.receipt_entry
    assert sum(x.debit for x in entry.lines.all()) == D("9619.20")
    assert entry.lines.get(account__name="Raw materials used").credit == D("9619.20")
    assert Mould.objects.get(code="MD-001").shot_count == 500
    assert [r["value"] for r in body["receipts"]] == ["9019.20", "600.00"]
    assert orders.payload(order, manager)["made"] == "3960"
    # Approved: locked, and receipts never change (database).
    with pytest.raises(DatabaseError, match="locked"), transaction.atomic():
        ShiftReport.objects.filter(pk=report.pk).update(notes="x")
    with pytest.raises(DatabaseError, match="never"), transaction.atomic():
        ProductionReceipt.objects.filter(pk=caps.pk).update(value=D("1"))


def test_returned_with_a_reason_then_resubmitted(ready, manager, supervisor):  # noqa: F811
    report = ready["report"]
    with pytest.raises(ShiftReportError, match="reason"):
        shift_approval.decide(manager, report, "send_back", "")
    shift_approval.decide(manager, report, "send_back", "Rejects look low")
    report.refresh_from_db()
    assert (report.status, report.return_reason) == ("returned", "Rejects look low")
    assert not ProductionReceipt.objects.exists()
    shift_reports.save(supervisor, report, {"runs": [run(ready["order"], material_lot="L1")]})
    shift_reports.submit(supervisor, report)
    shift_approval.decide(manager, report, "approve")
    report.refresh_from_db()
    assert report.status == "approved"
    state = ApprovalState.objects.get(document_type="shift_report", document_id=report.pk)
    assert state.round == 2


def test_a_shortage_stops_the_approval(ready, manager, planner):  # noqa: F811
    store = Store.objects.get(code="IM-MAIN")
    StockMovement.objects.create(
        item=Item.objects.get(code="PP-H"),
        store=store,
        division=store.division,
        lot_no="L1",
        kind="adjusted",
        movement_date=TODAY,
        quantity=D("-95"),
        value=D("-47500"),
        created_by=planner,
    )
    with pytest.raises(ShiftReportError, match="Backflush: Line .* only 5.000 kg of PP-H"):
        shift_approval.decide(manager, ready["report"], "approve")
    ready["report"].refresh_from_db()
    assert ready["report"].status == "submitted"
    assert Mould.objects.get(code="MD-001").shot_count == 0


def test_a_finished_part_needs_its_inventory_account(ready, manager):  # noqa: F811
    Item.objects.filter(code="CAP-28").update(inventory_account=None)
    with pytest.raises(ShiftReportError, match="CAP-28 has no inventory account"):
        shift_approval.decide(manager, ready["report"], "approve")


def test_a_correction_reverses_an_approved_report(ready, manager, supervisor, clock):  # noqa: F811
    report = ready["report"]
    shift_approval.decide(manager, report, "approve")
    clock["now"] = at(10, day=TODAY + timedelta(days=2))
    asked = as_user(supervisor).post(
        f"{URL}{report.pk}/corrections/", {"reason": "Counter misread"}, format="json"
    )
    assert asked.status_code == 201, asked.json()
    fix = ShiftCorrection.objects.get()
    assert fix.original["runs"][0]["end_counter"] == 1500
    assert fix.original["summary"]["good"] == "3960"
    assert asked.json()["corrections"][0]["status"] == "awaiting"
    with pytest.raises(ShiftReportError, match="one at a time"):
        shift_approval.ask(supervisor, report, "Again")
    # Never the person who asked.
    with pytest.raises(ShiftReportError):
        shift_approval.decide_fix(supervisor, fix, "approve")
    decided = as_user(manager).post(
        f"{URL}corrections/{fix.pk}/decide/", {"action": "approve"}, format="json"
    )
    assert decided.status_code == 200, decided.json()
    report.refresh_from_db()
    assert (report.status, report.return_reason) == ("returned", "Correction: Counter misread")
    # Everything approval posted is reversed; the receipts stay, marked undone.
    assert on_hand("CAP-28") == (D("0"), D("0"))
    assert on_hand("PP-H") == (D("100"), D("50000"))
    assert on_hand("BAG-1K") == (D("100"), D("2000"))
    assert Mould.objects.get(code="MD-001").shot_count == 0
    assert set(ProductionReceipt.objects.values_list("undone", flat=True)) == {True}
    assert JournalEntry.objects.filter(reversal_of=report.receipt_entry).exists()
    assert JournalEntry.objects.filter(reversal_of=report.stock_issue.journal_entry).exists()
    # The supervisor corrects it (any time, as it was returned) and it is approved again.
    shift_reports.save(
        supervisor,
        report,
        {"runs": [run(ready["order"], material_lot="L1", end_counter="1400", rejects=[])]},
    )
    shift_reports.submit(supervisor, report)
    shift_approval.decide(manager, report, "approve")
    assert on_hand("CAP-28") == (D("3200"), on_hand("CAP-28")[1])
    assert Mould.objects.get(code="MD-001").shot_count == 400
    with pytest.raises(DatabaseError, match="never changes once decided"), transaction.atomic():
        ShiftCorrection.objects.filter(pk=fix.pk).update(reason="x")


def test_a_correction_of_delivered_goods_is_refused(ready, manager, supervisor, planner):  # noqa: F811
    report = ready["report"]
    shift_approval.decide(manager, report, "approve")
    store = Store.objects.get(code="IM-MAIN")
    StockMovement.objects.create(
        item=Item.objects.get(code="CAP-28"),
        store=store,
        division=store.division,
        lot_no=ready["order"].number,
        kind="adjusted",
        movement_date=TODAY,
        quantity=D("-1000"),
        value=D("-1000"),
        created_by=planner,
    )
    fix = shift_approval.ask(supervisor, report, "Wrong order")
    with pytest.raises(ShiftReportError, match="has been used or delivered"):
        shift_approval.decide_fix(manager, fix, "approve")
    report.refresh_from_db()
    assert report.status == "approved"


def test_a_late_draft_is_reopened_by_the_director(clock, supervisor, press, cap, planner):  # noqa: F811
    order = orders.release(planner, for_stock(planner))
    report = shift_reports.open_report(
        supervisor, {"section": "IM-MLD", "shift": "G", "day": TODAY.isoformat()}
    )
    clock["now"] = at(22)
    with pytest.raises(ShiftReportError, match="grace period are over"):
        shift_reports.save(supervisor, report, {"runs": [run(order)]})
    fix = shift_approval.ask(supervisor, report, "Forgot to submit")
    director = person("dir@sml.lk", "director", all_divisions=True)
    shift_approval.decide_fix(director, fix, "approve")
    report.refresh_from_db()
    assert report.reopened_until == at(22) + timedelta(hours=4)
    shift_reports.save(supervisor, report, {"runs": [run(order)]})
    shift_reports.submit(supervisor, report)
    report.refresh_from_db()
    assert report.status == "submitted"


def test_who_may_ask_and_reject(ready, manager, supervisor, clock):  # noqa: F811
    report = ready["report"]
    with pytest.raises(ShiftReportError, match="asks for a correction"):
        shift_approval.ask(supervisor, report, "Submitted reports are returned instead")
    shift_approval.decide(manager, report, "approve")
    with pytest.raises(ShiftReportError, match="Say what needs correcting"):
        shift_approval.ask(supervisor, report, " ")
    with pytest.raises(ShiftReportError, match="asks for a correction"):
        shift_approval.ask(manager, report, "Not a supervisor")
    fix = shift_approval.ask(supervisor, report, "Typo")
    with pytest.raises(ShiftReportError, match="reason"):
        shift_approval.decide_fix(manager, fix, "reject", "")
    shift_approval.decide_fix(manager, fix, "reject", "It is right")
    fix.refresh_from_db()
    report.refresh_from_db()
    assert fix.status == "rejected" and report.status == "approved"
    assert Mould.objects.get(code="MD-001").shot_count == 500
