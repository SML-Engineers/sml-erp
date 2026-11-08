"""Mould maintenance (backlog P3-10): due and approaching from the shots since the last
preventive maintenance, the Production Manager told once per stage when an approved shift
report takes a mould there, records (preventive or repair) that restart the count and can
put a mould under maintenance or back in service, records never changed (database), and
the repair history per mould."""

from datetime import timedelta
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.core.models import Notification
from apps.production import maintenance, moulds, shift_approval
from apps.production.maintenance import MaintenanceError
from apps.production.models import Mould, MouldMaintenance

from .test_access import as_user, person
from .test_boms import item
from .test_production_orders import cap, for_stock, manager, planner  # noqa: F401
from .test_shift_approval import ready  # noqa: F401
from .test_shift_reports import TODAY, clock, press, run, supervisor  # noqa: F401

pytestmark = pytest.mark.django_db
URL = "/api/v1/mould-maintenance/"


@pytest.fixture
def mould(planner):  # noqa: F811
    item(planner, "CAP-28", "Cap 28 mm")
    base = {"cycle_time_s": "12", "shot_weight_g": "40", "pm_interval_shots": "1000"}
    return moulds.create(planner, base | {"code": "MD-001", "name": "Cap", "parts": "CAP-28 x 8"})


def shots(m, count):
    Mould.objects.filter(pk=m.pk).update(shot_count=count)
    m.refresh_from_db()
    return m


def test_due_and_approaching(mould, planner):  # noqa: F811
    assert maintenance.state(mould) == "ok"
    assert maintenance.state(shots(mould, 899)) == "ok"
    assert maintenance.state(shots(mould, 900)) == "approaching"
    assert maintenance.state(shots(mould, 1000)) == "due"
    Mould.objects.filter(pk=mould.pk).update(pm_interval_shots=None)
    mould.refresh_from_db()
    assert maintenance.state(mould) == ""
    Mould.objects.filter(pk=mould.pk).update(pm_interval_shots=1000)
    body = as_user(planner).get(URL).json()
    row = body["moulds"][0]
    assert (row["code"], row["since"], row["left"], row["state"]) == ("MD-001", 1000, 0, "due")
    assert body["can_record"] is True


def test_preventive_maintenance_restarts_the_count(mould, planner, manager):  # noqa: F811
    shots(mould, 1200)
    made = as_user(manager).post(
        URL,
        {
            "mould": "md-001",
            "kind": "planned",
            "done_on": TODAY.isoformat(),
            "work_done": "Cleaned vents, new O-rings",
            "cost": "12,500.50",
            "done_by": "Mould shop",
            "by_workshop": True,
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    mould.refresh_from_db()
    assert (mould.shot_count, mould.shots_at_last_pm) == (1200, 1200)
    record = MouldMaintenance.objects.get()
    assert (record.shot_count, record.cost, record.by_workshop) == (1200, D("12500.50"), True)
    assert made.json()["moulds"][0]["state"] == "ok"
    # A repair does not restart the count, and can put the mould under maintenance.
    shots(mould, 2100)
    maintenance.record(
        planner,
        {
            "mould": "MD-001",
            "kind": "repair",
            "work_done": "Broken ejector pin",
            "done_by": "ABC",
            "status": "maintenance",
        },
    )
    mould.refresh_from_db()
    assert (mould.shots_at_last_pm, mould.status) == (1200, "maintenance")
    maintenance.record(
        planner,
        {
            "mould": "MD-001",
            "kind": "repair",
            "work_done": "Pin replaced",
            "done_by": "ABC",
            "status": "active",
        },
    )
    mould.refresh_from_db()
    assert mould.status == "active"
    history = as_user(planner).get(f"{URL}?mould=MD-001").json()
    assert [h["work_done"] for h in history["history"]] == [
        "Pin replaced",
        "Broken ejector pin",
        "Cleaned vents, new O-rings",
    ]
    assert history["total_cost"] == "12500.50"
    # Records never change (database).
    with pytest.raises(DatabaseError, match="never changed"), transaction.atomic():
        MouldMaintenance.objects.filter(pk=record.pk).update(cost=D("1"))
    with pytest.raises(DatabaseError, match="never changed"), transaction.atomic():
        MouldMaintenance.objects.filter(pk=record.pk).delete()


@pytest.mark.parametrize(
    "values, message",
    [
        ({"mould": "MD-999"}, "no mould MD-999"),
        ({"kind": "clean"}, "preventive maintenance or a repair"),
        ({"done_on": "yesterday"}, "Give the date"),
        ({"done_on": (TODAY + timedelta(days=1)).isoformat()}, "not in advance"),
        ({"work_done": " "}, "what work was done"),
        ({"done_by": ""}, "who did the work"),
        ({"cost": "-1"}, "at least 0"),
        ({"cost": "1.234"}, "2 decimal places"),
        ({"cost": "abc"}, "is a number"),
        ({"status": "retired"}, "under maintenance or back in service"),
    ],
)
def test_records_are_checked(mould, planner, values, message):  # noqa: F811
    base = {"mould": "MD-001", "kind": "repair", "work_done": "Fixed", "done_by": "ABC"}
    with pytest.raises(MaintenanceError, match=message):
        maintenance.record(planner, base | values)
    assert not MouldMaintenance.objects.exists()


def test_only_the_manager_or_planner_records(mould, planner):  # noqa: F811
    supervisor_ = person("sup2@sml.lk", "production_supervisor", divisions=["IM"])
    with pytest.raises(MaintenanceError, match="Production Manager or the Planner"):
        maintenance.record(supervisor_, {"mould": "MD-001"})
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).get(URL).status_code == 403
    Mould.objects.filter(pk=mould.pk).update(status="retired")
    with pytest.raises(MaintenanceError, match="retired"):
        maintenance.record(
            planner, {"mould": "MD-001", "kind": "repair", "work_done": "x", "done_by": "y"}
        )


def test_approval_tells_the_production_manager_once_per_stage(ready, manager):  # noqa: F811
    mould = Mould.objects.get(code="MD-001")
    # The report has 500 shots; with an interval of 550 the mould is then approaching.
    Mould.objects.filter(pk=mould.pk).update(pm_interval_shots=550)
    shift_approval.decide(manager, ready["report"], "approve")
    told = Notification.objects.filter(event="mould_maintenance_due")
    assert [n.title for n in told.filter(user=manager)] == [
        "Mould MD-001 is approaching maintenance"
    ]
    # Telling again is not repeated for the same stage; reaching "due" is told.
    maintenance.after_shots([mould.pk])
    assert told.count() == 1
    Mould.objects.filter(pk=mould.pk).update(shot_count=600)
    maintenance.after_shots([mould.pk])
    assert told.filter(title="Mould MD-001 is due for maintenance").count() == 1
    # After preventive maintenance, the next approach is told again.
    maintenance.record(
        manager, {"mould": "MD-001", "kind": "planned", "work_done": "PM", "done_by": "Shop"}
    )
    Mould.objects.filter(pk=mould.pk).update(shot_count=1100)
    maintenance.after_shots([mould.pk])
    assert told.filter(title="Mould MD-001 is approaching maintenance").count() == 2
