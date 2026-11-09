"""Order costs in the ledger (backlog P3-16 part 2): a job's costs in Work in progress until it
is completed, then its finished parts into stock at that value; a moulding order's costs
added to its parts' stock value; finished parts delivered charged to cost of sales and
brought back if the note is cancelled; the month-end WIP report reconciled with the account."""

from datetime import date
from decimal import Decimal as D

import pytest
from django.db.models import Sum

from apps.accounting import close
from apps.accounting.models import Account, JournalLine
from apps.inventory.models import Item, StockMovement, Store
from apps.masters.models import Section
from apps.production import jobs, shift_approval, shift_reports, wip
from apps.production.models import CostRate, JobCompletion, OrderCost
from apps.sales import deliveries
from apps.sales import orders as sales_orders
from apps.sales.services import SalesError

from .test_access import as_user
from .test_job_cards import line, open_report, save, supervisor  # noqa: F401
from .test_job_orders import (  # noqa: F401
    accountant,
    give,
    internal,
    manager,
    planner,
    shaft,
    storeman,
)
from .test_sales_orders import (  # noqa: F401
    call_offs,
    director,
    executive,
    from_quote,
    unilever,
    won,
)
from .test_shift_reports import TODAY, clock  # noqa: F401

pytestmark = pytest.mark.django_db
ONE_OP = [{"seq": 10, "name": "Turn", "section": "M-LAT"}]


def balance(role: str, division: str) -> D:
    row = JournalLine.objects.filter(account__system_role=role, division__code=division).aggregate(
        d=Sum("debit"), c=Sum("credit")
    )
    return (row["d"] or D("0")) - (row["c"] or D("0"))


@pytest.fixture
def turned(
    django_capture_on_commit_callbacks,
    clock,  # noqa: F811
    planner,  # noqa: F811
    manager,  # noqa: F811
    storeman,  # noqa: F811
    supervisor,  # noqa: F811
    shaft,  # noqa: F811
):  # noqa: F811
    """20 drive shafts for stock: 10 kg of EN8 issued (1,080.00), 2 hours on the lathe at 600
    labour and 400 overhead, 20 finished."""
    lathe = Section.objects.get(code="M-LAT")
    for kind, rate in (("labour", "600"), ("overhead", "400")):
        CostRate.objects.create(
            kind=kind, section=lathe, rate=D(rate), effective_from=date(2026, 1, 1), reason="t"
        )
    job = jobs.release(
        planner, internal(planner, item="SH-100", description="", quantity="20", operations=ONE_OP)
    )
    with django_capture_on_commit_callbacks(execute=True):
        give(storeman, job, ("EN8-50", "10", ""))
        report = open_report(supervisor, "M-LAT")
        save(
            supervisor, report, line(job, 10, completed="20", machine="M-LAT-01", end_time="10:00")
        )
        shift_reports.submit(supervisor, report)
        shift_approval.decide(manager, report, "approve")
    return job


def test_a_jobs_costs_sit_in_work_in_progress_until_it_is_completed(accountant, planner, turned):  # noqa: F811
    job = turned
    assert set(OrderCost.objects.filter(job=job).values_list("ledger", flat=True)) == {"wip"}
    assert balance("work_in_progress", "WS") == D("3080.00")
    assert balance("production_absorbed", "WS") == D("-2000.00")  # labour and overhead absorbed
    found = as_user(accountant).get("/api/v1/wip-report/").json()
    [ws] = found["divisions"]
    assert (ws["orders"], ws["ledger"], ws["difference"], found["reconciled"]) == (
        "3080.00",
        "3080.00",
        "0.00",
        True,
    )
    assert ws["jobs"][0]["number"] == job.number
    jobs.complete(planner, job)
    done = JobCompletion.objects.get(job=job)
    assert (done.quantity, done.value) == (D("20"), D("3080.00"))
    stock = StockMovement.objects.get(lot_no=job.number, kind="produced")
    assert (stock.item.code, stock.store.code, stock.quantity, stock.value) == (
        "SH-100",
        "WS-MAIN",
        20,
        D("3080.00"),
    )
    assert balance("work_in_progress", "WS") == 0
    assert balance("finished_goods", "WS") == D("3080.00")
    assert wip.report()["divisions"] == []
    month = TODAY.replace(day=1)
    item = next(i for i in close.checklist(month) if i.key == "order_costs")
    assert item.done is True


def test_a_late_bill_goes_to_the_parts_or_to_cost_of_sales(planner, turned):  # noqa: F811
    job = turned
    jobs.complete(planner, job)
    entry = OrderCost.objects.create(
        job=job,
        division=job.division,
        element="direct",
        day=TODAY,
        source="test:late",
        amount=D("100.00"),
        description="Late bill",
    )
    wip.post_pending(job)
    entry.refresh_from_db()
    assert entry.ledger == "finished"  # 20 shafts still in stock
    assert StockMovement.objects.get(kind="costed", lot_no=job.number).value == D("100.00")


def test_a_job_with_nothing_finished_sends_its_work_in_progress_to_cost_of_sales(
    django_capture_on_commit_callbacks,
    planner,  # noqa: F811
    storeman,  # noqa: F811
    shaft,  # noqa: F811
):
    job = jobs.release(
        planner, internal(planner, item="SH-100", description="", quantity="5", operations=ONE_OP)
    )
    with django_capture_on_commit_callbacks(execute=True):
        give(storeman, job, ("EN8-50", "2", ""))
    assert balance("work_in_progress", "WS") == D("216.00")
    done = wip.finish(planner, job, D("0"))  # as on cancelling, or completing with none made
    assert (done.quantity, done.value, done.movement) == (D("0"), D("216.00"), None)
    assert balance("work_in_progress", "WS") == 0
    assert balance("finished_goods_sold", "WS") == D("216.00")


@pytest.fixture
def ordered(executive, from_quote):  # noqa: F811
    sales_orders.save(
        executive, from_quote, lines=call_offs(from_quote, (14, "10000")), customer_po="P1"
    )
    sales_orders.confirm(executive, from_quote)
    return from_quote


def test_finished_parts_delivered_leave_stock_at_cost_of_sales(
    executive,  # noqa: F811
    shaft,  # noqa: F811
    accountant,  # noqa: F811
    storeman,  # noqa: F811
    ordered,  # noqa: F811
):  # noqa: F811
    order_line = ordered.lines.get()
    shafts = Item.objects.get(code="SH-100")
    finished = Account.objects.get(system_role="finished_goods")
    Item.objects.filter(pk=shafts.pk).update(inventory_account=finished)
    note = deliveries.create(
        executive, ordered, lines=[deliveries.LineInput(order_line, "5", shafts)]
    )
    with pytest.raises(
        SalesError, match=r"only 0.000 pcs of SH-100 is in IM-MAIN. Approve its production first"
    ):
        deliveries.issue(executive, note)
    store = Store.objects.get(code="IM-MAIN")
    for lot, quantity, value in (("A", "3", "450.00"), ("B", "4", "640.00")):
        StockMovement.objects.create(
            item=shafts,
            store=store,
            division=store.division,
            lot_no=lot,
            kind="opening",
            movement_date=TODAY,
            quantity=D(quantity),
            value=D(value),
            created_by=accountant,
        )
    deliveries.issue(executive, note)
    note.refresh_from_db()
    # 5 of 7 at the average 155.7143: 778.57.
    assert note.lines.get().cost == D("778.57")
    lines = sorted((x.account.system_role, x.debit, x.credit) for x in note.cost_entry.lines.all())
    assert lines == [
        ("finished_goods", D("0"), D("778.57")),
        ("finished_goods_sold", D("778.57"), D("0")),
    ]
    out = StockMovement.objects.filter(kind="delivered").order_by("lot_no")
    assert [(m.lot_no, m.quantity) for m in out] == [("A", -3), ("B", -2)]
    body = as_user(executive).get(f"/api/v1/delivery-notes/{note.pk}/").json()
    assert (body["lines"][0]["item"], body["lines"][0]["cost"]) == ("SH-100", "778.57")
    # Cancelled: back into the same lots, the journal reversed.
    deliveries.cancel(storeman, note, "Wrong lorry")
    back = StockMovement.objects.filter(kind="undeliver").order_by("lot_no")
    assert [(m.lot_no, m.quantity, m.value) for m in back] == [
        ("A", 3, D("467.14")),
        ("B", 2, D("311.43")),
    ]
    assert balance("finished_goods_sold", "IM") == 0


def test_a_line_without_a_stock_part_moves_nothing(executive, ordered):  # noqa: F811
    note = deliveries.create(
        executive, ordered, lines=[deliveries.LineInput(ordered.lines.get(), "5")]
    )
    assert note.lines.get().item is None  # no job or production order for the line
    deliveries.issue(executive, note)
    note.refresh_from_db()
    assert note.cost_entry is None and not StockMovement.objects.filter(kind="delivered").exists()
