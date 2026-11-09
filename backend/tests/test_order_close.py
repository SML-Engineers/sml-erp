"""Closing an order and its variances (backlog P3-18): an order for a sales line closes when
its last quantity is delivered; its final report shows revenue, cost and margin in LKR and
the estimate against actual by element with the material price and usage variances; the
report is never changed; closed orders give the actual kg, hours and cycle time per part for
the next quotation."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.accounting.models import Account
from apps.core.models import Company, Division
from apps.inventory.models import Item, StockMovement, Store
from apps.masters.models import Machine, Section
from apps.production import closing, jobs, orders, shift_approval, shift_reports
from apps.production.models import CostRate, OrderClose
from apps.sales import deliveries, invoices, services, workflow
from apps.sales import orders as sales_orders
from apps.sales.models import QuotationCosting, QuotationCostingOperation
from apps.sales.services import LineInput as QuoteLine

from .test_access import as_user
from .test_job_cards import line, open_report, save, supervisor  # noqa: F401
from .test_job_orders import accountant, give, manager, planner, shaft, storeman  # noqa: F401
from .test_order_profit import moulded  # noqa: F401
from .test_production_orders import cap, for_stock  # noqa: F401
from .test_sales_orders import call_offs, director, executive, unilever  # noqa: F401
from .test_shift_reports import TODAY, clock, press  # noqa: F401
from .test_shift_reports import supervisor as moulding_supervisor  # noqa: F401

pytestmark = pytest.mark.django_db
ONE_OP = [{"seq": 10, "name": "Turn", "section": "M-LAT"}]


@pytest.fixture
def shaft_order(executive, director, unilever, shaft):  # noqa: F811
    """20 drive shafts at 400.00, quoted at 300 of material (1 kg at 300) and 100 of turning
    (6 minutes at 1,000 an hour) a shaft."""
    Item.objects.filter(code="SH-100").update(
        inventory_account=Account.objects.get(system_role="finished_goods")
    )
    q = services.save(
        executive,
        None,
        customer=unilever,
        division=Division.objects.get(code="WS"),
        lines=[QuoteLine(description="Drive shaft", quantity="20", unit_price="400")],
    )
    costing = QuotationCosting.objects.create(
        line=q.lines.get(),
        method="machining",
        rates_date=TODAY,
        material_rate=D("300"),
        weight_kg=D("1"),
        setup_rate=D("0"),
        overhead_pct=D("0"),
        margin_pct=D("20"),
        updated_by=executive,
    )
    QuotationCostingOperation.objects.create(
        costing=costing,
        seq=10,
        machine=Machine.objects.get(code="M-LAT-01"),
        minutes=D("6"),
        rate=D("1000"),
    )
    workflow.submit(executive, q)
    workflow.approve(director, q)
    q = workflow.record_outcome(executive, q, accepted=True, reason="price")
    order = sales_orders.from_quotation(executive, q)
    sales_orders.save(executive, order, lines=call_offs(order, (14, "20")), customer_po="P9")
    sales_orders.confirm(executive, order)
    return order


@pytest.fixture
def made(
    django_capture_on_commit_callbacks,
    clock,  # noqa: F811
    planner,  # noqa: F811
    manager,  # noqa: F811
    storeman,  # noqa: F811
    supervisor,  # noqa: F811
    shaft,  # noqa: F811
    shaft_order,  # noqa: F811
):
    """The job for the 20 shafts: 10 kg of EN8 (1,080.00), 2 hours on the lathe (labour
    1,200.00, overhead 800.00); 18 good, 2 rejected. The job is completed."""
    lathe = Section.objects.get(code="M-LAT")
    for kind, rate in (("labour", "600"), ("overhead", "400")):
        CostRate.objects.create(
            kind=kind, section=lathe, rate=D(rate), effective_from=date(2026, 1, 1), reason="t"
        )
    job = jobs.create(
        planner,
        {
            "purpose": "sales",
            "sales_line": shaft_order.lines.get().pk,
            "item": "SH-100",
            "quantity": "20",
            "due_date": (TODAY + timedelta(days=14)).isoformat(),
            "operations": ONE_OP,
        },
    )
    job = jobs.release(planner, job)
    with django_capture_on_commit_callbacks(execute=True):
        give(storeman, job, ("EN8-50", "10", ""))
        report = open_report(supervisor, "M-LAT")
        save(
            supervisor,
            report,
            line(
                job,
                10,
                completed="18",
                rejects=[{"reason": "DIMENSION", "quantity": "2"}],
                machine="M-LAT-01",
                end_time="10:00",
            ),
        )
        shift_reports.submit(supervisor, report)
        shift_approval.decide(manager, report, "approve")
    return jobs.complete(planner, job)


def deliver(user, order, quantity):
    note = deliveries.create(user, order, lines=[deliveries.LineInput(order.lines.get(), quantity)])
    return deliveries.issue(user, note)


def test_the_last_delivery_closes_the_job_with_its_variances(
    executive,  # noqa: F811
    accountant,  # noqa: F811
    shaft_order,  # noqa: F811
    made,
):
    job = made
    assert job.status == "completed"
    deliver(executive, shaft_order, "18")
    job.refresh_from_db()
    assert job.status == "completed"  # 2 still to deliver
    store = Store.objects.get(code="WS-MAIN")
    StockMovement.objects.create(
        item=Item.objects.get(code="SH-100"),
        store=store,
        division=store.division,
        lot_no="OLD",
        kind="opening",
        movement_date=TODAY,
        quantity=D("2"),
        value=D("600.00"),
        created_by=accountant,
    )
    deliver(executive, shaft_order, "2")
    job.refresh_from_db()
    assert (job.status, job.closed_at is not None) == ("closed", True)
    closed = OrderClose.objects.get(job=job)
    assert (closed.automatic, closed.closed_by, closed.cost) == (True, executive, D("3080.00"))
    r = closed.report
    assert (r["basis"], r["good"], r["rejected"]) == ("quotation", "18", "2")
    # Revenue: 18 good at 400 (no invoice yet: the sales order's price and rate).
    assert (r["revenue"], r["revenue_basis"], r["margin"], r["margin_pct"]) == (
        "7200.00",
        "order",
        "4120.00",
        "133.77",
    )
    rows = {x["key"]: (x["estimate"], x["actual"], x["variance"]) for x in r["rows"]}
    assert rows == {
        "material": ("5400.00", "972.00", "-4428.00"),  # 18 × 300; 90% of 1,080
        "machine": ("1800.00", "1800.00", "0.00"),  # 18 × 100; 90% of 2,000
        "setup": ("0.00", "0.00", "0.00"),
        "rejects": ("0.00", "308.00", "308.00"),  # 10% of everything spent
        "outside": ("0.00", "0.00", "0.00"),
    }
    assert (r["estimate_cost"], r["variance"]) == ("7200.00", "-4120.00")
    # 9 kg for the good shafts at 108 against 1 kg a shaft at 300.
    assert (r["material_price"], r["material_usage"]) == ("-1728.00", "-2700.00")
    assert r["actuals"] == {
        "kg_per_piece": "0.5000",
        "hours_per_1000": "100.00",
        "setup_hours": "0.00",
        "cycle_s": None,
    }
    body = as_user(accountant).get(f"/api/v1/job-orders/{job.pk}/").json()["close_report"]
    assert (body["automatic"], body["variance"]) == (True, "-4120.00")
    # The report never changes.
    with pytest.raises(DatabaseError), transaction.atomic():
        OrderClose.objects.filter(pk=closed.pk).update(cost=D("1"))
    # The next quotation for the part sees what it really took.
    found = as_user(accountant).get("/api/v1/order-profits/part/?item=sh-100").json()
    assert [o["number"] for o in found["orders"]] == [job.number]
    assert found["average"]["kg_per_piece"] == "0.5000"
    assert as_user(accountant).get("/api/v1/order-profits/part/?item=NOPE").status_code == 400
    listed = as_user(accountant).get("/api/v1/order-profits/?state=closed").json()["orders"]
    assert [o["number"] for o in listed] == [job.number]


def test_revenue_follows_the_issued_invoices(
    executive,  # noqa: F811
    accountant,  # noqa: F811
    shaft_order,  # noqa: F811
    made,
):
    Division.objects.filter(code="WS").update(tax_invoice_code="W1")
    Company.objects.filter(pk=1).update(name="SML Engineers (Pvt) Ltd", tin="134567890")
    deliver(executive, shaft_order, "18")
    invoices.issue(accountant, invoices.create(executive, shaft_order))
    income, basis = closing.revenue(made, D("18"))
    assert (income, basis) == (D("7200.00"), "invoices")


def test_a_job_completed_after_the_last_delivery_closes_on_completion(
    django_capture_on_commit_callbacks,
    executive,  # noqa: F811
    accountant,  # noqa: F811
    planner,  # noqa: F811
    shaft,  # noqa: F811
    shaft_order,  # noqa: F811
):
    """All 20 delivered from stock first; the job then completes and closes at once."""
    store = Store.objects.get(code="WS-MAIN")
    job = jobs.release(
        planner,
        jobs.create(
            planner,
            {
                "purpose": "sales",
                "sales_line": shaft_order.lines.get().pk,
                "item": "SH-100",
                "quantity": "20",
                "due_date": (TODAY + timedelta(days=14)).isoformat(),
                "operations": ONE_OP,
            },
        ),
    )
    StockMovement.objects.create(
        item=Item.objects.get(code="SH-100"),
        store=store,
        division=store.division,
        lot_no="OLD",
        kind="opening",
        movement_date=TODAY,
        quantity=D("20"),
        value=D("6000.00"),
        created_by=accountant,
    )
    deliver(executive, shaft_order, "20")
    job.refresh_from_db()
    assert job.status == "released"  # not made yet: it stays open
    job = jobs.complete(planner, job)
    assert job.status == "closed" and OrderClose.objects.get(job=job).automatic


def test_an_order_for_stock_is_closed_by_the_planner_with_its_report(
    planner,  # noqa: F811
    accountant,  # noqa: F811
    moulded,  # noqa: F811
):
    order = orders.complete(planner, moulded)
    assert order.status == "completed"  # for stock: no delivery closes it
    order = orders.close(planner, order)
    closed = OrderClose.objects.get(production_order=order)
    r = closed.report
    assert (closed.automatic, closed.revenue, r["basis"], r["revenue"]) == (
        False,
        None,
        "bom",
        None,
    )
    assert all(x["estimate"] is None for x in r["rows"])
    assert sum(D(x["actual"]) for x in r["rows"]) == closed.cost
    assert r["actuals"]["cycle_s"] is not None and r["standard_cycle_s"] is not None
    assert r["actuals"]["kg_per_piece"] is not None  # the resin backflushed
    body = as_user(accountant).get(f"/api/v1/production-orders/{order.pk}/").json()
    assert body["close_report"]["cost"] == str(closed.cost)
    assert (
        as_user(planner).get(f"/api/v1/production-orders/{order.pk}/").json()["close_report"]
        is None
    )
