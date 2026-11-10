"""Live order profitability (backlog P3-17): each open order's estimate (from the accepted
quotation's costing), actual to date and forecast at completion, with a red, amber or green
status; the order dashboard and its filters; each cost line's source document; alerts to the
Production Manager and the Director once per order and kind; the daily snapshot; the moulding
view per machine and mould."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.accounting.models import Account
from apps.core.models import Division, Notification
from apps.inventory.models import Item
from apps.masters.models import Section
from apps.production import jobs, orders, profit, reasons, shift_approval, shift_reports
from apps.production.models import (
    CostRate,
    Mould,
    OrderCost,
    OrderProfitSnapshot,
    ProductionReceipt,
    ProductionSetting,
    ProfitAlert,
)
from apps.sales import orders as sales_orders
from apps.sales import services, workflow
from apps.sales.models import QuotationCosting
from apps.sales.services import LineInput as QuoteLine

from .test_access import as_user
from .test_job_cards import line, open_report, save, supervisor  # noqa: F401
from .test_job_orders import accountant, give, manager, planner, shaft, storeman  # noqa: F401
from .test_production_orders import cap, for_stock  # noqa: F401
from .test_sales_orders import call_offs, director, executive, unilever  # noqa: F401
from .test_shift_approval import put_in
from .test_shift_reports import TODAY, clock, press, run  # noqa: F401
from .test_shift_reports import supervisor as moulding_supervisor  # noqa: F401

pytestmark = pytest.mark.django_db
ONE_OP = [{"seq": 10, "name": "Turn", "section": "M-LAT"}]
URL = "/api/v1/order-profits/"


@pytest.fixture
def shaft_order(executive, director, unilever):  # noqa: F811
    """20 drive shafts at 400.00 each, quoted at a cost of 300.00 a shaft (1 kg at 300)."""
    q = services.save(
        executive,
        None,
        customer=unilever,
        division=Division.objects.get(code="WS"),
        lines=[QuoteLine(description="Drive shaft", quantity="20", unit_price="400")],
    )
    QuotationCosting.objects.create(
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
    workflow.submit(executive, q)
    workflow.approve(director, q)
    q = workflow.record_outcome(executive, q, accepted=True, reason="price")
    order = sales_orders.from_quotation(executive, q)
    sales_orders.save(executive, order, lines=call_offs(order, (14, "20")), customer_po="P9")
    sales_orders.confirm(executive, order)
    return order


@pytest.fixture
def half_done(
    django_capture_on_commit_callbacks,
    clock,  # noqa: F811
    planner,  # noqa: F811
    manager,  # noqa: F811
    storeman,  # noqa: F811
    supervisor,  # noqa: F811
    shaft,  # noqa: F811
    shaft_order,
):
    """The job for the 20 shafts: 10 kg of EN8 issued (1,080.00), 2 hours on the lathe at
    600 labour and 400 overhead (2,000.00), 10 shafts finished. Cost so far 3,080.00."""
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
            supervisor, report, line(job, 10, completed="10", machine="M-LAT-01", end_time="10:00")
        )
        shift_reports.submit(supervisor, report)
        shift_approval.decide(manager, report, "approve")
    job.refresh_from_db()
    return job


def stricter(**limits) -> ProductionSetting:
    """New production settings from today, the rest as now."""
    now = reasons.setting_on()
    values = {
        "grace_hours": now.grace_hours,
        "reject_alert_pct": now.reject_alert_pct,
        "overrun_alert_pct": now.overrun_alert_pct,
        "min_margin_pct": now.min_margin_pct,
    } | {k: D(v) for k, v in limits.items()}
    ProductionSetting.objects.filter(effective_from=TODAY).exists() and pytest.fail("in force")
    return ProductionSetting.objects.create(effective_from=TODAY, reason="test", **values)


def test_an_order_shows_its_estimate_actual_and_forecast(accountant, half_done):  # noqa: F811
    f = profit.figures(half_done)
    assert (f["estimate_basis"], f["estimate_unit"], f["estimate_cost"]) == (
        "quotation",
        D("300.00"),
        D("6000.00"),
    )
    assert (f["value"], f["estimate_margin"]) == (D("8000.00"), D("2000.00"))
    assert (f["good"], f["complete_pct"], f["cost"], f["earned"]) == (
        D("10"),
        D("50.00"),
        D("3080.00"),
        D("4000.00"),
    )
    # 3,080 for 10 against 300 each: 2.67% over. Forecast 3,080 + 10 × 300.
    assert f["overrun_pct"] == D("2.67")
    assert (f["forecast_cost"], f["forecast_margin"], f["margin_pct"]) == (
        D("6080.00"),
        D("1920.00"),
        D("31.58"),
    )
    assert (f["status"], f["flags"]) == ("green", [])
    body = as_user(accountant).get(f"/api/v1/job-orders/{half_done.pk}/").json()
    assert (body["profit"]["status"], body["profit"]["forecast_margin"]) == ("green", "1920.00")
    # Every cost line names its source document.
    entries = {e["element"]: e for e in body["costs"]["entries"]}
    assert entries["labour"]["document"].startswith("Work shift report M-LAT ")
    assert entries["labour"]["link"].startswith("/shift-report?report=")


def test_the_dashboard_lists_open_orders_worst_first_with_filters(
    accountant,  # noqa: F811
    planner,  # noqa: F811
    half_done,
    unilever,  # noqa: F811
):
    client = as_user(accountant)
    found = client.get(URL).json()
    [row] = found["orders"]
    assert (row["number"], row["customer"], row["sections"], row["status"]) == (
        half_done.number,
        "Unilever Sri Lanka",
        ["M-LAT"],
        "green",
    )
    assert (row["value"], row["cost"], row["complete_pct"]) == ("8000.00", "3080.00", "50.00")
    assert found["counts"] == {"red": 0, "amber": 0, "green": 1}
    assert client.get(f"{URL}?division=IM").json()["orders"] == []
    assert client.get(f"{URL}?section=M-BSW").json()["orders"] == []
    assert len(client.get(f"{URL}?customer={unilever.pk}&section=M-LAT").json()["orders"]) == 1
    due = (TODAY + timedelta(days=13)).isoformat()
    assert client.get(f"{URL}?due_by={due}").json()["orders"] == []
    assert client.get(f"{URL}?state=completed").json()["orders"] == []
    # The planner does not see money.
    assert as_user(planner).get(URL).status_code == 403
    assert as_user(planner).get(f"/api/v1/job-orders/{half_done.pk}/").json()["profit"] is None


def test_alerts_go_to_the_production_manager_and_director_once(
    django_capture_on_commit_callbacks,
    manager,  # noqa: F811
    director,  # noqa: F811
    half_done,
):
    stricter(min_margin_pct="40")
    f = profit.figures(half_done)
    assert (f["status"], f["flags"], f["min_margin_pct"]) == ("amber", ["margin"], D("40"))
    with django_capture_on_commit_callbacks(execute=True):
        [alert] = profit.check_alerts(half_done)
    assert alert.detail == "Forecast margin 1,920.00 (31.58%) is below the minimum of 40.00%."
    told = Notification.objects.filter(event="order_profit_alert")
    assert sorted(n.user.email for n in told) == ["director@sml.lk", "pm@sml.lk"]
    assert told.first().link == f"/job-orders?job={half_done.pk}"
    assert profit.check_alerts(half_done) == []  # once per order and kind
    # A late bill puts the cost over the estimate by more than 10%: red.
    OrderCost.objects.create(
        job=half_done,
        division=half_done.division,
        element="direct",
        day=TODAY,
        source="test:bill",
        amount=D("1000.00"),
        description="Special tooling",
    )
    f = profit.figures(half_done)
    assert (f["status"], f["overrun_pct"]) == ("red", D("36.00"))
    with django_capture_on_commit_callbacks(execute=True):
        [alert] = profit.check_alerts(half_done)
    assert alert.kind == "overrun"
    assert alert.detail.startswith("Cost so far 4,080.00 for 10 good pieces is 36.00% over")
    with pytest.raises(DatabaseError), transaction.atomic():
        ProfitAlert.objects.filter(pk=alert.pk).update(detail="x")


def test_a_snapshot_of_each_open_order_is_kept_daily(accountant, half_done):  # noqa: F811
    assert profit.snapshot_open(TODAY) == 1
    assert profit.snapshot_open(TODAY) == 0  # once a day
    shot = OrderProfitSnapshot.objects.get(job=half_done)
    assert (shot.cost, shot.forecast_margin, shot.complete_pct, shot.status) == (
        D("3080.00"),
        D("1920.00"),
        D("50.00"),
        "green",
    )
    body = as_user(accountant).get(f"/api/v1/job-orders/{half_done.pk}/").json()["profit"]
    assert [(s["day"], s["forecast_margin"]) for s in body["snapshots"]] == [
        (TODAY.isoformat(), "1920.00")
    ]
    with pytest.raises(DatabaseError), transaction.atomic():
        OrderProfitSnapshot.objects.filter(pk=shot.pk).delete()


def test_an_order_without_a_quotation_uses_its_bom_and_has_no_revenue(planner, shaft):  # noqa: F811
    job = jobs.release(
        planner,
        jobs.create(
            planner,
            {
                "purpose": "tools",
                "division": "WS",
                "item": "SH-100",
                "quantity": "5",
                "due_date": (TODAY + timedelta(days=7)).isoformat(),
                "operations": ONE_OP,
            },
        ),
    )
    f = profit.figures(job)
    assert f["estimate_basis"] == "bom" and f["estimate_unit"] > 0
    assert (f["value"], f["forecast_margin"], f["margin_pct"]) == (None, None, None)
    assert f["status"] == "green"


@pytest.fixture
def moulded(
    django_capture_on_commit_callbacks,
    clock,  # noqa: F811
    planner,  # noqa: F811
    manager,  # noqa: F811
    cap,  # noqa: F811
    moulding_supervisor,  # noqa: F811
    press,  # noqa: F811
):
    """500 shots × 8 caps from 08:00 to 10:00 with 2 people, 40 rejects; labour 500,
    overhead 300 an hour, the mould 0.10 a shot."""
    Item.objects.filter(category="raw_material").update(
        inventory_account=Account.objects.get(name="Raw materials")
    )
    Item.objects.filter(code__in=["CAP-28", "BAG-1K"]).update(
        inventory_account=Account.objects.get(name="Finished goods")
    )
    put_in("PP-H", "100", "50000", "L1", planner)
    put_in("MB-BLK", "10", "15000", "M1", planner)
    put_in("BAG-1K", "100", "2000", "B1", planner)
    moulding = Section.objects.get(code="IM-MLD")
    start = date(2026, 1, 1)
    for kind, rate in (("labour", "500"), ("overhead", "300")):
        CostRate.objects.create(
            kind=kind, section=moulding, rate=D(rate), effective_from=start, reason="t"
        )
    CostRate.objects.create(
        kind="mould",
        mould=Mould.objects.get(code="MD-001"),
        rate=D("0.10"),
        effective_from=start,
        reason="t",
    )
    order = orders.release(planner, for_stock(planner))
    report = shift_reports.open_report(
        moulding_supervisor, {"section": "IM-MLD", "shift": "G", "day": TODAY.isoformat()}
    )
    shift_reports.save(
        moulding_supervisor,
        report,
        {
            "runs": [run(order, material_lot="L1")],
            "manpower": [{"machine": "IMM-250", "people": "2"}],
        },
    )
    shift_reports.submit(moulding_supervisor, report)
    with django_capture_on_commit_callbacks(execute=True):
        shift_approval.decide(manager, report, "approve")
    return order


def test_the_moulding_view_per_machine_and_mould(accountant, moulded):  # noqa: F811
    receipt = ProductionReceipt.objects.get(order=moulded, item__code="CAP-28")
    found = as_user(accountant).get(f"{URL}moulding/?start={TODAY}&end={TODAY}").json()
    [row] = found["rows"]
    assert (row["machine"], row["mould"], row["orders"]) == ("IMM-250", "MD-001", [moulded.number])
    assert (row["good"], row["rejected"], row["reject_pct"]) == ("3960", 40, "1.00")
    assert row["standard_cycle_s"] == str(Mould.objects.get(code="MD-001").cycle_time_s)
    per_piece = (receipt.value / 3960).quantize(D("0.0001"))
    assert row["material_per_piece"] == str(per_piece)
    # Labour 2 h × 2 × 500, overhead 2 h × 300, mould 500 shots × 0.10.
    cost = receipt.value + D("2000") + D("600") + D("50")
    assert row["cost_per_1000"] == str((cost / 3960 * 1000).quantize(D("0.01")))
    assert row["margin_per_1000"] is None  # for stock: no price
    # A stricter reject limit flags the order (its BOM's standard cost is the estimate).
    assert "rejects" not in profit.figures(moulded)["flags"]
    stricter(reject_alert_pct="0.5")
    f = profit.figures(moulded)
    assert (f["estimate_basis"], f["reject_pct"]) == ("bom", D("1.00"))
    assert "rejects" in f["flags"]
    backwards = as_user(accountant).get(f"{URL}moulding/?start={TODAY}&end=2000-01-01")
    assert backwards.status_code == 400
