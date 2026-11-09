"""Order costs (backlog P3-16 part 1): every job order and production order collects its
costs from what was approved (material, labour, overhead, setup and mould change, mould
amortisation, subcontract and direct bills), each entry naming its source; entries are
insert-only, so a corrected report or a cancelled bill adds adjusting entries."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.accounting.models import Account
from apps.inventory.models import Item
from apps.masters.models import Section
from apps.production import costs, orders, shift_approval, shift_reports
from apps.production.models import CostRate, JobOrder, Mould, OrderCost, ProductionReceipt

from .test_access import as_user
from .test_job_cards import supervisor  # noqa: F401
from .test_job_orders import accountant, manager, planner, shaft, storeman  # noqa: F401
from .test_mould_transfers import costed, director, memory_storage, mould  # noqa: F401
from .test_production_orders import cap, for_stock  # noqa: F401
from .test_shift_approval import put_in
from .test_shift_reports import TODAY, at, clock, press, run  # noqa: F401
from .test_shift_reports import supervisor as moulding_supervisor  # noqa: F401

pytestmark = pytest.mark.django_db


def entries(order) -> list[tuple]:
    key = {"job": order} if isinstance(order, JobOrder) else {"production_order": order}
    return sorted((e.element, e.amount, e.adjusts) for e in OrderCost.objects.filter(**key))


def by_element(order) -> dict:
    out = {}
    for element, amount, _ in entries(order):
        out[element] = out.get(element, D("0")) + amount
    return out


def test_a_jobs_costs_come_from_its_issues_time_and_bills(accountant, costed):  # noqa: F811
    job = costed
    assert costs.sync(job) == 5
    assert entries(job) == [
        ("direct", D("25000.00"), False),
        ("labour", D("1200.00"), False),
        ("material", D("-108.00"), False),
        ("material", D("432.00"), False),
        ("overhead", D("800.00"), False),
    ]
    assert costs.sync(job) == 0  # nothing new: no entries added
    body = as_user(accountant).get(f"/api/v1/job-orders/{job.pk}/").json()["costs"]
    assert body["total"] == "27324.00" and body["out_of_date"] is False
    assert [(e["label"], e["amount"]) for e in body["elements"]] == [
        ("Material", "324.00"),
        ("Labour", "1200.00"),
        ("Machine time and overhead", "800.00"),
        ("Direct expenses", "25000.00"),
    ]
    labour = next(e for e in body["entries"] if e["element"] == "labour")
    assert (labour["quantity"], labour["unit"], labour["rate"]) == ("2", "h", "600")
    first = OrderCost.objects.filter(job=job).first()
    with pytest.raises(DatabaseError, match="never changed or deleted"), transaction.atomic():
        OrderCost.objects.filter(pk=first.pk).update(amount=1)


def test_a_corrected_report_takes_its_costs_back(
    accountant,  # noqa: F811
    manager,  # noqa: F811
    supervisor,  # noqa: F811
    clock,  # noqa: F811
    costed,  # noqa: F811
):
    job = costed
    costs.sync(job)
    report = job.entries.get().report
    clock["now"] = at(10, day=TODAY + timedelta(days=2))
    fix = shift_approval.ask(supervisor, report, "Wrong machine")
    shift_approval.decide_fix(manager, fix, "approve")
    assert costs.sync(job) == 2
    taken = OrderCost.objects.filter(job=job, adjusts=True).order_by("element")
    assert [(e.element, e.amount, e.description[:10]) for e in taken] == [
        ("labour", D("-1200.00"), "Taken back"),
        ("overhead", D("-800.00"), "Taken back"),
    ]
    assert by_element(job)["labour"] == 0


def test_costs_follow_the_approvals_on_commit(
    django_capture_on_commit_callbacks,
    planner,  # noqa: F811
    storeman,  # noqa: F811
    mould,  # noqa: F811
):
    from .test_job_orders import give
    from .test_mould_transfers import mould_job

    job = mould_job(planner)
    with django_capture_on_commit_callbacks(execute=True):
        give(storeman, job, ("EN8-50", "2", ""))
    assert entries(job) == [("material", D("216.00"), False)]


def test_a_production_orders_costs_from_its_shift(
    django_capture_on_commit_callbacks,
    clock,  # noqa: F811
    planner,  # noqa: F811
    manager,  # noqa: F811
    accountant,  # noqa: F811
    cap,  # noqa: F811
    moulding_supervisor,  # noqa: F811
    press,  # noqa: F811
):
    """500 shots × 8 caps from 08:30 to 10:00 with 2 people, after a 30-minute mould change;
    labour 500, overhead 300 an hour, the mould 0.10 a shot."""
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
        )  # noqa: E501
    CostRate.objects.create(
        kind="mould",
        mould=Mould.objects.get(code="MD-001"),
        rate=D("0.10"),
        effective_from=start,
        reason="t",
    )  # noqa: E501
    order = orders.release(planner, for_stock(planner))
    report = shift_reports.open_report(
        moulding_supervisor, {"section": "IM-MLD", "shift": "G", "day": TODAY.isoformat()}
    )  # noqa: E501
    shift_reports.save(
        moulding_supervisor,
        report,
        {
            "runs": [run(order, material_lot="L1", start_time="08:30")],
            "downtime": [
                {
                    "machine": "IMM-250",
                    "reason": "MOULD-CHANGE",
                    "start_time": "08:00",
                    "end_time": "08:30",
                }
            ],  # noqa: E501
            "manpower": [{"machine": "IMM-250", "people": "2"}],
        },
    )
    shift_reports.submit(moulding_supervisor, report)
    with django_capture_on_commit_callbacks(execute=True):
        shift_approval.decide(manager, report, "approve")
    receipt = ProductionReceipt.objects.get(order=order, item__code="CAP-28")
    assert by_element(order) == {
        "material": receipt.value,
        "labour": D("1500.00"),
        "overhead": D("450.00"),
        "mould": D("50.00"),
        "setup": D("650.00"),
    }
    body = as_user(accountant).get(f"/api/v1/production-orders/{order.pk}/").json()["costs"]
    total = receipt.value + D("2650.00")
    assert (body["good"], body["rejected"], body["total"]) == ("3960", "40", str(total))
    assert body["on_rejects"] == str((total * 40 / 4000).quantize(D("0.01")))
    # The planner, who does not see costs, gets none.
    assert as_user(planner).get(f"/api/v1/production-orders/{order.pk}/").json()["costs"] is None


def test_the_accountant_refreshes_every_open_order(accountant, planner, costed):  # noqa: F811
    refused = as_user(planner).post("/api/v1/order-costs/refresh/")
    assert refused.status_code == 403
    done = as_user(accountant).post("/api/v1/order-costs/refresh/")
    assert done.status_code == 200 and done.json()["entries"] == 5
