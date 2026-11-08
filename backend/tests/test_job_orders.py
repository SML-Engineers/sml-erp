"""Machining job orders and their material (backlog P3-11): for a sales order line or an
internal job, numbered from the number series, the approved routing and BOM copied and
changeable while a draft, material issued by Stores within what the job may use, more only
with the Production Manager's approval, returns credited, statuses that only move forward,
and database guards."""

from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core.models import Division
from apps.inventory import items
from apps.inventory.models import Item, StockMovement, Store
from apps.masters.models import Machine, Section
from apps.production import boms, jobs, moulds, orders, routings
from apps.production.jobs import JobError
from apps.production.models import JobExcess, JobIssue, JobOperation, JobOrder
from apps.sales import orders as sales_orders

from .test_access import as_user, person
from .test_routings import OPERATIONS
from .test_sales_orders import (  # noqa: F401
    call_offs,
    director,
    executive,
    from_quote,
    unilever,
    won,
)
from .test_vouchers import payee

pytestmark = pytest.mark.django_db
URL = "/api/v1/job-orders/"
TODAY = timezone.localdate()
DUE = TODAY + timedelta(days=21)
St = JobOrder.Status


@pytest.fixture
def planner():
    return person("planner@sml.lk", "production_planner", divisions=["WS", "IM"])


@pytest.fixture
def manager():
    return person("pm@sml.lk", "production_manager", divisions=["WS", "IM"])


@pytest.fixture
def storeman():
    return person("stores@sml.lk", "store_supervisor", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


def stocked(accountant, code, name, category, unit, lots, store="WS-MAIN"):
    item = items.create_item(
        accountant,
        {
            "code": code,
            "name": name,
            "category": category,
            "unit": unit,
            "inventory_account": "1210",
        },
    )
    where = Store.objects.get(code=store)
    for lot, quantity, value in lots:
        StockMovement.objects.create(
            item=item,
            store=where,
            division=where.division,
            lot_no=lot,
            kind="opening",
            movement_date=TODAY,
            quantity=D(quantity),
            value=D(value),
            created_by=accountant,
        )
    return item


@pytest.fixture
def shaft(planner, manager, accountant):
    """SH-100 with an approved routing (cut, turn, plate) and BOM: 2 kg of EN8 a shaft with
    5% scrap, 2 bearings. EN8 in WS-MAIN: lot A 30 kg, lot B 20 kg; bearings 100."""
    Machine.objects.create(
        code="M-LAT-01", name="Lathe 1", section=Section.objects.get(code="M-LAT")
    )
    payee("Ceylon Platers", code="S0100")
    part = Item.objects.create(
        code="SH-100", name="Drive shaft", category="finished", unit="pcs", created_by=planner
    )
    stocked(
        accountant,
        "EN8-50",
        "EN8 bar 50 mm",
        "raw_material",
        "kg",
        [("A", "30", "3000.00"), ("B", "20", "2400.00")],
    )
    stocked(accountant, "BRG-6205", "Bearing 6205", "bought_out", "pcs", [("", "100", "50000.00")])
    stocked(accountant, "IN-CNMG", "Turning insert", "consumable", "pcs", [("", "20", "20000.00")])
    routing = routings.create(
        planner, {"item": "SH-100", "drawing_revision": "B", "operations": OPERATIONS}
    )
    routings.submit(planner, routing)
    routings.decide(manager, routing, "approve")
    bom = boms.create(
        planner,
        {
            "item": "SH-100",
            "kind": "machining",
            "lines": [
                {
                    "seq": 10,
                    "line_type": "raw",
                    "component": "EN8-50",
                    "quantity": "2",
                    "scrap_pct": "5",
                    "operation_seq": 10,
                },
                {"seq": 20, "line_type": "bought", "component": "BRG-6205", "quantity": "2"},
            ],
        },
    )
    boms.submit(planner, bom)
    boms.decide(manager, bom, "approve")
    return part


def internal(planner, **more):
    values = {
        "purpose": "tools",
        "division": "WS",
        "description": "Drill jig",
        "quantity": "1",
        "due_date": DUE,
    }
    return jobs.create(planner, values | more)


def shafts(planner, quantity="20", **more):
    """A job for 20 shafts, made through the WS division as an internal job for the part."""
    return internal(planner, item="SH-100", description="", quantity=quantity, **more)


def released(planner, quantity="20"):
    return jobs.release(planner, shafts(planner, quantity))


def give(storeman, job, *lines, store="WS-MAIN"):
    return jobs.issue(
        storeman,
        job,
        {
            "store": Store.objects.get(code=store).pk,
            "lines": [{"item": code, "quantity": q, "lot_no": lot} for code, q, lot in lines],
        },
    )


def material(job, code, user) -> dict:
    found = jobs.payload(JobOrder.objects.get(pk=job.pk), user)["materials"]
    return next(m for m in found if m["component"] == code)


# --- Making jobs ---------------------------------------------------------------------------------


def test_a_job_copies_the_routing_and_bom_and_changes_only_while_a_draft(planner, shaft):
    made = as_user(planner).post(
        URL,
        {
            "purpose": "tools",
            "division": "WS",
            "item": "SH-100",
            "drawing_no": "D-100",
            "drawing_revision": "B",
            "quantity": "20",
            "due_date": DUE.isoformat(),
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    body = made.json()
    assert body["number"].startswith(f"JO{TODAY:%y%m}") and body["status"] == "draft"
    assert (body["description"], body["division"], body["routing"]["revision"]) == (
        "Drive shaft",
        "WS",
        1,
    )
    assert [(o["seq"], o["name"], o["section"], o["machine"]) for o in body["operations"]] == [
        (10, "Cut to length", "M-BSW", ""),
        (20, "Turn", "M-LAT", "M-LAT-01"),
        (30, "Hard chrome plating", "", ""),
    ]
    # 2 kg a shaft with 5% scrap is 2.1 kg; 20 shafts may use 42 kg.
    en8 = next(m for m in body["materials"] if m["component"] == "EN8-50")
    assert (en8["per_piece"], en8["allowed"], en8["issued"], en8["on_hand"]) == (
        "2.1",
        "42",
        "0",
        "50",
    )
    job = JobOrder.objects.get(pk=body["id"])
    # The Planner changes this job's operations and materials while it is a draft.
    changed = (
        as_user(planner)
        .patch(
            f"{URL}{job.pk}/",
            {
                "operations": OPERATIONS[:2],
                "materials": [
                    {"seq": 10, "line_type": "raw", "component": "EN8-50", "per_piece": "2.2"}
                ],
            },
            format="json",
        )
        .json()
    )
    assert [o["seq"] for o in changed["operations"]] == [10, 20]
    assert [(m["component"], m["allowed"]) for m in changed["materials"]] == [("EN8-50", "44")]
    # The routing in force is copied again on request.
    again = jobs.update(planner, job, {"copy_again": True})
    assert again.operations.count() == 3 and again.materials.count() == 2
    jobs.release(planner, job)
    with pytest.raises(JobError, match="is released"):
        jobs.update(planner, job, {"quantity": "30"})
    with pytest.raises(DatabaseError, match="never change"), transaction.atomic():
        JobOperation.objects.filter(job=job, seq=10).update(name="Saw")
    with pytest.raises(DatabaseError, match="what it makes never changes"), transaction.atomic():
        JobOrder.objects.filter(pk=job.pk).update(quantity=30)


def test_a_job_for_a_sales_order_line_shares_its_quantity_with_production_orders(
    planner,
    shaft,
    executive,  # noqa: F811
    from_quote,  # noqa: F811
):
    with pytest.raises(JobError, match="is not open"):
        jobs.create(
            planner,
            {
                "purpose": "sales",
                "sales_line": from_quote.lines.get().pk,
                "item": "SH-100",
                "quantity": "1",
                "due_date": DUE,
            },
        )
    sales_orders.save(
        executive, from_quote, lines=call_offs(from_quote, (14, "10000")), customer_po="P1"
    )
    sales_orders.confirm(executive, from_quote)
    line = from_quote.lines.get()
    job = jobs.create(
        planner,
        {
            "purpose": "sales",
            "sales_line": line.pk,
            "item": "SH-100",
            "quantity": "7000",
            "due_date": DUE,
        },
    )
    assert (job.division.code, job.description, job.sales_line_id) == (
        "IM",
        "Cap, PP, white",
        line.pk,
    )
    assert orders.planned_for(line) == D("7000")
    with pytest.raises(JobError, match="has 3000 pcs left to make"):
        jobs.create(
            planner,
            {
                "purpose": "sales",
                "sales_line": line.pk,
                "item": "SH-100",
                "quantity": "3001",
                "due_date": DUE,
            },
        )
    body = as_user(planner).get(f"{URL}{job.pk}/").json()
    assert (body["sales_order"], body["customer"]) == (from_quote.number, "Unilever Sri Lanka")
    listed = as_user(planner).get(f"{URL}sales-lines/").json()["results"]
    assert (listed[0]["planned"], listed[0]["left"]) == ("7000", "3000")
    # A cancelled job frees its quantity.
    jobs.cancel(planner, job, "Customer moved the order")
    assert orders.planned_for(line) == 0


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"quantity": "0"}, "quantity is more than 0"),
        ({"quantity": "1.0001"}, "at most 3 decimal places"),
        ({"due_date": "soon"}, "Give the due date"),
        ({"purpose": "fun"}, "Say what the job is for"),
        ({"division": "XX"}, "Choose the division"),
        ({"description": ""}, "Describe the job"),
        ({"purpose": "mould_repair"}, "Choose the mould to repair"),
        ({"mould": "MD-404"}, "There is no mould MD-404"),
        ({"item": "NOPE"}, "There is no item NOPE"),
        (
            {"purpose": "sales", "sales_line": "999999", "item": "SH-100"},
            "Choose the sales order line",
        ),
        ({"operations": [{"seq": 10, "name": "Mill"}]}, "give the section"),
        ({"materials": [{"component": "NOPE", "per_piece": "1"}]}, "no active item NOPE"),
        ({"materials": [{"component": "EN8-50", "per_piece": "0"}]}, "more than 0"),
    ],
)
def test_jobs_are_checked(planner, shaft, values, message):
    with pytest.raises(JobError, match=message):
        internal(planner, **values)


def test_internal_jobs_without_a_routing_get_their_operations_from_the_planner(
    planner, manager, shaft
):
    base = {"cycle_time_s": "12", "shot_weight_g": "40", "runner_weight_g": "4"}
    Item.objects.create(
        code="CAP-28", name="Cap", category="finished", unit="pcs", created_by=planner
    )
    moulds.create(planner, base | {"code": "MD-001", "name": "Cap", "parts": "CAP-28 x 8"})
    repair = internal(
        planner, purpose="mould_repair", mould="MD-001", description="Repair cavity 3"
    )
    assert (repair.mould.code, repair.operations.count(), repair.materials.count()) == (
        "MD-001",
        0,
        0,
    )
    with pytest.raises(JobError, match="has no operations"):
        jobs.release(planner, repair)
    jobs.update(
        planner,
        repair,
        {
            "operations": [{"seq": 10, "name": "Weld and polish", "section": "M-LAT"}],
            "materials": [{"line_type": "raw", "component": "EN8-50", "per_piece": "0.5"}],
        },
    )
    jobs.release(planner, repair)
    assert JobOrder.objects.get(pk=repair.pk).status == St.RELEASED
    listed = as_user(planner).get(f"{URL}?purpose=mould_repair").json()["results"]
    assert [(j["number"], j["mould"], j["purpose_label"]) for j in listed] == [
        (repair.number, "MD-001", "Mould repair")
    ]


def test_only_the_planner_makes_jobs_and_statuses_move_forward(planner, storeman, shaft):
    refused = as_user(storeman).post(
        URL,
        {
            "purpose": "tools",
            "division": "WS",
            "description": "Jig",
            "quantity": "1",
            "due_date": DUE.isoformat(),
        },
        format="json",
    )
    assert refused.status_code == 400 and "Only the Production Planner" in refused.json()["detail"]
    job = released(planner)
    with pytest.raises(JobError, match="cannot be closed"):
        jobs.close(planner, job)
    with pytest.raises(JobError, match="Give the reason"):
        jobs.cancel(planner, job, " ")
    jobs.complete(planner, job)
    with pytest.raises(JobError, match="cannot be cancelled"):
        jobs.cancel(planner, job, "late")
    jobs.close(planner, job)
    with pytest.raises(DatabaseError, match="never deleted"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM production_joborder WHERE id = %s", [job.pk])
    with pytest.raises(DatabaseError, match="it never changes"), transaction.atomic():
        JobOrder.objects.filter(pk=job.pk).update(notes="x")


# --- Material ------------------------------------------------------------------------------------


def test_stores_issues_by_lot_within_what_the_job_may_use(planner, storeman, shaft):
    job = shafts(planner)
    with pytest.raises(JobError, match="released job"):
        give(storeman, job, ("EN8-50", "1", ""))
    jobs.release(planner, job)
    with pytest.raises(JobError, match="Only the stores person"):
        give(planner, job, ("EN8-50", "1", ""))
    # 35 kg: lot A (30) first, then 5 from B, at the average cost of 108.00.
    made = give(storeman, job, ("EN8-50", "35", ""), ("BRG-6205", "40", ""))
    assert made.purpose.startswith(f"Job {job.number}")
    assert sorted((x.item.code, x.lot_no, x.quantity) for x in made.lines.all()) == [
        ("BRG-6205", "", D("40.000")),
        ("EN8-50", "A", D("30.000")),
        ("EN8-50", "B", D("5.000")),
    ]
    assert JobIssue.objects.get(stock_issue=made).job_id == job.pk
    assert (
        material(job, "EN8-50", storeman).items()
        >= {"allowed": "42", "issued": "35", "left": "7"}.items()
    )
    # A chosen lot, and not more than the job may use.
    give(storeman, job, ("EN8-50", "2", "B"))
    with pytest.raises(JobError, match=r"EN8-50: 6 kg is 1 more than .* may still use \(5\)"):
        give(storeman, job, ("EN8-50", "6", ""))
    with pytest.raises(JobError, match="IN-CNMG: 1 pcs is 1 more"):
        give(storeman, job, ("IN-CNMG", "1", ""))
    with pytest.raises(JobError, match="store of division WS"):
        give(storeman, job, ("EN8-50", "1", ""), store="IM-MAIN")
    lots = (
        as_user(storeman)
        .get(f"{URL}{job.pk}/lots/?store={Store.objects.get(code='WS-MAIN').pk}&item=EN8-50")
        .json()["results"]
    )
    assert lots == [{"lot_no": "B", "quantity": "13"}]


def test_returns_are_credited_to_the_job(planner, storeman, shaft):
    job = released(planner)
    made = give(storeman, job, ("EN8-50", "42", ""))
    line_b = made.lines.get(lot_no="B")
    body = as_user(storeman).post(
        f"{URL}{job.pk}/return/",
        {"issue": made.pk, "lines": [{"line": line_b.pk, "quantity": "4"}]},
        format="json",
    )
    assert body.status_code == 201, body.json()
    assert body.json()["stock_issue"].startswith("MI")
    assert material(job, "EN8-50", storeman)["left"] == "4"
    back = next(i for i in body.json()["issues"] if i["kind"] == "return")
    assert [(x["item"], x["lot_no"], x["quantity"]) for x in back["lines"]] == [
        ("EN8-50", "B", "4")
    ]
    with pytest.raises(JobError, match="only 8.000 was issued and not yet returned"):
        jobs.give_back(
            storeman, job, {"issue": made.pk, "lines": [{"line": line_b.pk, "quantity": "9"}]}
        )
    with pytest.raises(JobError, match="Choose an issue of"):
        jobs.give_back(storeman, job, {"issue": 0, "lines": []})
    # A job with material out is not cancelled; once it is back, it may be.
    with pytest.raises(JobError, match="return it to stores first"):
        jobs.cancel(planner, job, "Order lost")
    jobs.give_back(
        storeman,
        job,
        {
            "issue": made.pk,
            "lines": [
                {"line": x.pk, "quantity": str(x.quantity - (4 if x.lot_no == "B" else 0))}
                for x in made.lines.all()
            ],
        },
    )
    jobs.cancel(planner, job, "Order lost")
    with pytest.raises(DatabaseError, match="Issues to a job never change"), transaction.atomic():
        JobIssue.objects.filter(job=job).delete()


def test_more_than_the_job_allows_needs_the_production_managers_approval(
    planner, manager, storeman, shaft
):
    job = released(planner)
    give(storeman, job, ("EN8-50", "42", ""))
    with pytest.raises(JobError, match="Give the reason"):
        jobs.ask_more(storeman, job, {"item": "EN8-50", "quantity": "4"})
    asked = as_user(storeman).post(
        f"{URL}{job.pk}/ask-more/",
        {"item": "EN8-50", "quantity": "4", "reason": "Two shafts scrapped at setup"},
        format="json",
    )
    assert asked.status_code == 200, asked.json()
    excess = JobExcess.objects.get(job=job)
    assert asked.json()["excess"][0].items() >= {"status": "awaiting", "can_decide": False}.items()
    with pytest.raises(JobError, match="already waiting"):
        jobs.ask_more(storeman, job, {"item": "EN8-50", "quantity": "1", "reason": "more"})
    # Not yet approved: still refused.
    with pytest.raises(JobError, match="1 more than"):
        give(storeman, job, ("EN8-50", "1", ""))
    waiting = as_user(manager).get(f"{URL}waiting/").json()["results"]
    assert [(w["job"], w["item"], w["quantity"]) for w in waiting] == [(job.number, "EN8-50", "4")]
    assert as_user(storeman).get(f"{URL}waiting/").json()["results"] == []
    with pytest.raises(JobError):
        jobs.decide_more(storeman, excess, "approve")
    decided = as_user(manager).post(
        f"{URL}excess/{excess.pk}/decide/", {"action": "approve"}, format="json"
    )
    assert decided.json() == {"status": "approved"}
    assert material(job, "EN8-50", storeman)["allowed"] == "46"
    give(storeman, job, ("EN8-50", "4", ""))
    with pytest.raises(DatabaseError, match="never changes"), transaction.atomic():
        JobExcess.objects.filter(pk=excess.pk).update(quantity=40)
    # A material not on the job, rejected: nothing more may be issued.
    other = jobs.ask_more(
        storeman, job, {"item": "IN-CNMG", "quantity": "2", "reason": "Insert broke"}
    )
    with pytest.raises(JobError, match="reason"):
        jobs.decide_more(manager, other, "reject")
    jobs.decide_more(manager, other, "reject", "Use the spare inserts")
    assert JobExcess.objects.get(pk=other.pk).status == "rejected"
    with pytest.raises(JobError, match="IN-CNMG: 1 pcs is 1 more"):
        give(storeman, job, ("IN-CNMG", "1", ""))
    # Approved extra of a material not on the job shows as an extra line.
    third = jobs.ask_more(
        planner, job, {"item": "IN-CNMG", "quantity": "2", "reason": "Insert broke again"}
    )
    jobs.complete(planner, job)
    with pytest.raises(JobError, match="waiting for approval"):
        jobs.close(planner, job)
    jobs.decide_more(manager, third, "approve")
    extra = material(job, "IN-CNMG", planner)
    assert (extra["extra"], extra["allowed"]) == (True, "2")
    jobs.close(planner, job)


def test_the_job_order_series_and_approver_are_seeded():
    from apps.core.models import ApprovalReminder, ApprovalRule, NumberSeries

    assert NumberSeries.objects.get(document_type="job_order").format == "JO{YY}{MM}{NNNN}"
    assert ApprovalRule.objects.get(document_type="job_excess").role.code == "production_manager"
    assert ApprovalReminder.objects.get(document_type="job_excess").after_days == 1
    assert Division.objects.filter(code="WS").exists()
