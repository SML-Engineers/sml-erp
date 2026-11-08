"""The moulding production plan (backlog P3-07): released orders on moulding machines per
shift, the planned quantity from cycle time × cavities × planned minutes, warnings (mould
too big, maintenance, a machine planned twice or beyond the shift, a mould on two machines,
no crew rostered, material short, more than the order needs), past days never changed,
completed or cancelled orders leaving the plan, and the supervisors' own sections."""

from datetime import time, timedelta
from decimal import Decimal as D

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core.models import Division
from apps.masters import rosters
from apps.masters.models import Machine, Section, Shift
from apps.production import orders, plan
from apps.production.models import Mould, PlanEntry
from apps.production.plan import PlanError

from .test_access import as_user, person
from .test_production_orders import cap, for_stock, manager, planner, stock, storeman  # noqa: F401

pytestmark = pytest.mark.django_db
URL = "/api/v1/production-plan/"
TODAY = timezone.localdate()
TOMORROW = TODAY + timedelta(days=1)


@pytest.fixture
def presses():
    section = Section.objects.get(code="IM-MLD")
    big = Machine.objects.create(
        code="IMM-250", name="Haitian 250 t", section=section, clamping_force_t=D("250")
    )
    small = Machine.objects.create(
        code="IMM-90", name="Haitian 90 t", section=section, clamping_force_t=D("90")
    )
    return big, small


@pytest.fixture
def released(planner, cap):  # noqa: F811
    order = for_stock(planner)
    return orders.release(planner, order)


@pytest.fixture
def day_roster():
    """IM works the General shift (08:00-17:00) with crew A; nobody is on nights."""
    night = rosters.create_shift(
        code="N", name="Night", start_time=time(20), end_time=time(8), break_minutes=60
    )
    pattern = rosters.create_pattern(name="Days", days=[Shift.objects.get(code="G").pk])
    im = Division.objects.get(code="IM")
    crew = rosters.create_crew(division=im, code="A")
    rosters.create_assignment(pattern=pattern, division=im, start_date=TODAY, crews=[(crew, 0)])
    return night


def entry(planner, prod, machine="IMM-250", shift="G", day=TOMORROW, **more):  # noqa: F811
    when = day if isinstance(day, str) else day.isoformat()
    values = {"day": when, "shift": shift, "machine": machine, "order": prod.pk}
    return plan.add(planner, values | more)


def test_an_order_is_planned_with_its_quantity(planner, released, presses, day_roster):  # noqa: F811
    made = as_user(planner).post(
        URL,
        {"day": TOMORROW.isoformat(), "shift": "G", "machine": "IMM-250", "order": released.pk},
        format="json",
    )
    assert made.status_code == 201, made.json()
    body = made.json()
    # The whole General shift: 480 minutes at 12 s a shot = 2,400 shots × 8 caps.
    assert (body["minutes"], body["quantity"], body["mould"]) == (480, "19200", "MD-001")
    # Part of a shift: 100 minutes = 500 shots = 4,000 caps.
    part = entry(planner, released, machine="IMM-90", minutes="100")
    assert part.quantity == D("4000")
    board = as_user(planner).get(f"{URL}?start={TODAY}&days=3").json()
    assert [d for d in board["days"]] == [(TODAY + timedelta(days=n)).isoformat() for n in range(3)]
    assert [m["code"] for m in board["machines"]] == ["IMM-250", "IMM-90"]
    assert {s["code"] for s in board["shifts"]} == {"G", "N"}
    assert board["orders"][0]["planned"] == "23200" and board["orders"][0]["quantity"] == "10000"
    assert board["can_plan"] is True
    by = {e["machine"]: e for e in board["entries"]}
    assert "The plan makes more than" in " ".join(by["IMM-250"]["warnings"])


@pytest.mark.parametrize(
    "values, message",
    [
        ({"day": "2020-01-01"}, "today or later"),
        ({"day": "soon"}, "Give the date"),
        ({"shift": "X"}, "Choose the shift"),
        ({"machine": "NONE"}, "no machine NONE"),
        ({"order": "abc"}, "Choose the production order"),
        ({"minutes": "0"}, "planned minutes are 1 to 480"),
        ({"minutes": "481"}, "planned minutes are 1 to 480"),
        ({"minutes": "1.5"}, "whole number"),
    ],
)
def test_plan_entries_are_checked(planner, released, presses, values, message):  # noqa: F811
    with pytest.raises(PlanError, match=message):
        entry(planner, released, **values)
    assert not PlanEntry.objects.exists()


def test_only_released_orders_on_moulding_machines(planner, cap, presses):  # noqa: F811
    draft = for_stock(planner)
    with pytest.raises(PlanError, match="is not released"):
        entry(planner, draft)
    lathe = Machine.objects.create(
        code="M-LAT-01", name="Lathe", section=Section.objects.get(code="M-LAT")
    )
    orders.release(planner, draft)
    planner.divisions.add(Division.objects.get(code="WS"))
    with pytest.raises(PlanError, match="not a moulding machine"):
        entry(planner, draft, machine=lathe.code)
    Machine.objects.filter(code="IMM-90").update(status="retired")
    with pytest.raises(PlanError, match="retired"):
        entry(planner, draft, machine="IMM-90")
    # The database refuses a plan for an order that is not released, or for a past day.
    other = for_stock(planner, quantity="10")
    with pytest.raises(DatabaseError, match="Only a released"), transaction.atomic():
        PlanEntry.objects.create(
            day=TOMORROW,
            shift=Shift.objects.get(code="G"),
            machine=presses[0],
            order=other,
            mould=draft.mould,
            minutes=10,
            quantity=D("1"),
            created_by=planner,
        )


def test_the_warnings(planner, released, presses, day_roster, storeman):  # noqa: F811
    big, small = presses
    # A mould needing 120 t on the 90 t press; the press under maintenance.
    Mould.objects.filter(pk=released.mould_id).update(tonnage_t=D("120"))
    Machine.objects.filter(pk=small.pk).update(status="maintenance")
    on_small = entry(planner, released, machine="IMM-90", minutes="200")
    # Twice on the big press, together beyond the 480 minutes of the shift.
    first = entry(planner, released, minutes="300")
    second = entry(planner, released, minutes="300")
    # On nights nobody is rostered.
    night = entry(planner, released, shift="N", minutes="60")
    board = plan.board(planner, TOMORROW.isoformat(), 1)
    w = {e["id"]: " | ".join(e["warnings"]) for e in board["entries"]}
    assert "Too big: Clamping force: the mould needs 120 t, IMM-90 has 90" in w[on_small.pk]
    assert "IMM-90 is under maintenance" in w[on_small.pk]
    assert "also planned on another machine" in w[on_small.pk]
    assert "IMM-250 is planned 2 times on this shift" in w[first.pk]
    assert "more than the shift's working time" in w[second.pk]
    assert "No crew is rostered on Night in IM-MLD" in w[night.pk]
    assert "No crew" not in w[first.pk]
    # The order has no stock at all: it is short of material.
    assert f"{released.number} is short of material" in w[first.pk]
    stock("PP-H", "1000", storeman)
    stock("MB-BLK", "100", storeman)
    stock("BAG-1K", "100", storeman)
    board = plan.board(planner, TOMORROW.isoformat(), 1)
    assert not any("short of material" in " ".join(e["warnings"]) for e in board["entries"])


def test_moving_copying_and_removing(planner, released, presses):  # noqa: F811
    first = entry(planner, released, minutes="100")
    moved = as_user(planner).patch(
        f"{URL}{first.pk}/", {"machine": "IMM-90", "shift": "G"}, format="json"
    )
    assert moved.status_code == 200, moved.json()
    assert (moved.json()["machine"], moved.json()["minutes"]) == ("IMM-90", 100)
    copied = as_user(planner).post(
        f"{URL}copy/",
        {"source": TOMORROW.isoformat(), "target": (TOMORROW + timedelta(days=1)).isoformat()},
        format="json",
    )
    assert copied.json() == {"copied": 1}
    with pytest.raises(PlanError, match="nothing planned"):
        plan.copy_day(planner, TODAY, TOMORROW)
    assert as_user(planner).delete(f"{URL}{first.pk}/").status_code == 204
    assert PlanEntry.objects.count() == 1


def test_a_past_day_never_changes(planner, released, presses):  # noqa: F811
    today = entry(planner, released, day=TODAY)
    # As if it had been planned yesterday.
    past = PlanEntry.objects.filter(pk=today.pk)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL session_replication_role = replica")  # triggers off
        past.update(day=TODAY - timedelta(days=1))
        cursor.execute("SET LOCAL session_replication_role = DEFAULT")
    old = past.get()
    with pytest.raises(PlanError, match="past day never changes"):
        plan.change(planner, old, {"minutes": "10"})
    with pytest.raises(PlanError, match="past day never changes"):
        plan.remove(planner, old)
    for change in (lambda: past.update(minutes=10), lambda: past.delete()):
        with pytest.raises(DatabaseError, match="has passed and never changes"):
            with transaction.atomic():
                change()
    # A completed order leaves the plan after today, but today and the past stay.
    later = entry(planner, released, day=TOMORROW)
    entry(planner, released, day=TODAY)
    orders.complete(planner, released)
    assert not PlanEntry.objects.filter(pk=later.pk).exists()
    assert PlanEntry.objects.filter(order=released).count() == 2


def test_only_the_planner_changes_it_and_supervisors_see_their_sections(
    planner,  # noqa: F811
    released,
    presses,
):
    put = entry(planner, released, day=TODAY)
    entry(planner, released, day=TODAY + timedelta(days=3))
    supervisor = person("sup@sml.lk", "production_supervisor", divisions=["IM"])
    supervisor.all_sections = False
    supervisor.save()
    with pytest.raises(PlanError, match="Only the Production Planner"):
        plan.add(supervisor, {})
    # A supervisor of another section sees nothing; of IM-MLD, today's and tomorrow's.
    assert as_user(supervisor).get(f"{URL}mine/").json()["entries"] == []
    board = as_user(supervisor).get(f"{URL}?start={TODAY}&days=7").json()
    assert (board["entries"], board["machines"], board["can_plan"]) == ([], [], False)
    Section.objects.get(code="IM-MLD").supervisors.add(supervisor)
    mine = as_user(supervisor).get(f"{URL}mine/").json()["entries"]
    assert [e["id"] for e in mine] == [put.pk]
    assert mine[0]["order_number"] == released.number
    refused = as_user(supervisor).delete(f"{URL}{put.pk}/")
    assert refused.status_code == 400
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).get(URL).status_code == 403
