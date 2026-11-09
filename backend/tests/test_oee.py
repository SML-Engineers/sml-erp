"""OEE of the moulding machines (backlog P3-19): planned time from the roster (off days not
counted, planned stops taken off), availability, performance against the mould's standard
cycle, quality, OEE = A × P × Q, by machine, shift, day and month."""

from datetime import timedelta

import pytest

from apps.accounting.models import Account
from apps.core.models import Division
from apps.inventory.models import Item
from apps.masters.models import (
    Machine,
    RosterAssignment,
    RosterPattern,
    RosterPatternDay,
    Section,
    Shift,
)
from apps.production import oee, orders, shift_approval, shift_reports

from .test_access import as_user
from .test_job_orders import manager, planner  # noqa: F401
from .test_production_orders import cap, for_stock  # noqa: F401
from .test_shift_approval import put_in
from .test_shift_reports import TODAY, at, clock, press, run, supervisor  # noqa: F401

pytestmark = pytest.mark.django_db
YESTERDAY = TODAY - timedelta(days=1)


@pytest.fixture
def week(
    clock,  # noqa: F811
    planner,  # noqa: F811
    manager,  # noqa: F811
    cap,  # noqa: F811
    supervisor,  # noqa: F811
    press,  # noqa: F811
):
    """IM-MLD on the General shift every day from yesterday; IMM-250 and IMM-120. Today
    IMM-250 moulded 500 shots × 8 from 08:00 to 10:00 (40 rejects, 12 s standard cycle), then
    stood with nothing planned to 16:00. Yesterday nothing was moulded."""
    Machine.objects.create(code="IMM-120", name="Haitian 120 t", section=press.section)
    pattern = RosterPattern.objects.create(name="General every day")
    RosterPatternDay.objects.create(pattern=pattern, position=0, shift=Shift.objects.get(code="G"))
    RosterAssignment.objects.create(
        pattern=pattern,
        division=Division.objects.get(code="IM"),
        section=Section.objects.get(code="IM-MLD"),
        start_date=YESTERDAY,
    )
    clock["now"] = at(17)
    Item.objects.filter(category="raw_material").update(
        inventory_account=Account.objects.get(name="Raw materials")
    )
    Item.objects.filter(code__in=["CAP-28", "BAG-1K"]).update(
        inventory_account=Account.objects.get(name="Finished goods")
    )
    put_in("PP-H", "100", "50000", "L1", planner)
    put_in("MB-BLK", "10", "15000", "M1", planner)
    put_in("BAG-1K", "100", "2000", "B1", planner)
    order = orders.release(planner, for_stock(planner))
    report = shift_reports.open_report(
        supervisor, {"section": "IM-MLD", "shift": "G", "day": TODAY.isoformat()}
    )
    shift_reports.save(
        supervisor,
        report,
        {
            "runs": [run(order, material_lot="L1")],
            "downtime": [
                {
                    "machine": "IMM-250",
                    "reason": "NO-PLAN",
                    "start_time": "10:00",
                    "end_time": "16:00",
                }
            ],
        },
    )
    shift_reports.submit(supervisor, report)
    shift_approval.decide(manager, report, "approve")
    return report


def test_oee_per_machine_shift_and_day(manager, week):  # noqa: F811
    found = oee.report(manager, YESTERDAY, TODAY)
    by = {m["machine"]: m for m in found["machines"]}
    big = by["IMM-250"]
    today = next(d for d in big["days"] if d["day"] == TODAY)
    # 8 working hours less 6 planned: 2 h available, 2 h run; 500 × 12 s = 100 min of 120.
    assert (today["planned_h"], today["planned_stops_h"], today["run_h"]) == (
        "8.00",
        "6.00",
        "2.00",
    )
    assert (today["availability"], today["performance"], today["quality"], today["oee"]) == (
        "100.0",
        "83.3",
        "99.0",
        "82.5",
    )
    # Yesterday was rostered but nothing ran: all lost.
    yesterday = next(d for d in big["days"] if d["day"] == YESTERDAY)
    assert (yesterday["availability"], yesterday["oee"]) == ("0.0", "0.0")
    # The two days together: 2 h run of 10 h available.
    assert (big["availability"], big["performance"], big["quality"], big["oee"]) == (
        "20.0",
        "83.3",
        "99.0",
        "16.5",
    )
    assert [s["shift"] for s in big["shifts"]] == ["G", "G"]
    assert [m["month"] for m in big["months"]] == sorted({f"{d:%Y-%m}" for d in (YESTERDAY, TODAY)})
    # The idle press: planned both days, nothing run.
    assert (by["IMM-120"]["planned_h"], by["IMM-120"]["oee"]) == ("16.00", "0.0")
    assert found["sections"] == ["IM-MLD"]


def test_off_days_are_not_lost(manager, week):  # noqa: F811
    """Before the roster started there is no planned time at all."""
    before = TODAY - timedelta(days=5)
    found = oee.report(manager, before, before)
    assert all(m["planned_h"] == "0.00" and m["oee"] is None for m in found["machines"])


def test_the_oee_page_is_for_production(manager, planner, week):  # noqa: F811
    client = as_user(manager)
    body = client.get(f"/api/v1/oee/?start={YESTERDAY}&end={TODAY}&section=IM-MLD").json()
    assert {m["machine"] for m in body["machines"]} == {"IMM-120", "IMM-250"}
    assert client.get(f"/api/v1/oee/?start={TODAY}&end={YESTERDAY}").status_code == 400
    assert client.get("/api/v1/oee/?start=nope").status_code == 400
    assert as_user(planner).get("/api/v1/oee/").status_code == 200  # planners view reports
