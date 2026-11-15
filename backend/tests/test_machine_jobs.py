"""Machine time (backlog P3-24 a; owner, 15 Nov 2026): the Production Team Leader starts and
finishes jobs live at the machine. Workshop jobs by job card, moulding by production order
and shot counter; one running job per machine (service and database) unless the Production
Manager allows a second with a reason; machines of the person's own sections only; a machine
under maintenance cannot start; the time is worked out from start and finish."""

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction

from apps.core.access import effective_access
from apps.masters.models import Machine, Section
from apps.production import jobs, machine_jobs, orders
from apps.production.machine_jobs import MachineJobError
from apps.production.models import MachineJob

from .test_access import as_user, person
from .test_job_orders import accountant, manager, planner, shaft, shafts  # noqa: F401
from .test_production_orders import cap, for_stock, stock, storeman  # noqa: F401
from .test_shift_reports import at, clock  # noqa: F401

pytestmark = pytest.mark.django_db
BOARD = "/api/v1/machine-jobs/board/"
JOBS = "/api/v1/machine-jobs/"


@pytest.fixture
def leader():
    user = person("tl@sml.lk", "production_team_leader", divisions=["WS", "IM"])
    user.all_sections = False
    user.save()
    for code in ("M-LAT", "IM-MLD"):
        Section.objects.get(code=code).users.add(user)
    return user


@pytest.fixture
def job(planner, shaft):  # noqa: F811
    """20 shafts: 10 cut (M-BSW), 20 turn (M-LAT-01), 30 hard chrome (sent out)."""
    return jobs.release(planner, shafts(planner))


@pytest.fixture
def press():
    return Machine.objects.create(
        code="IMM-250", name="Haitian 250 t", section=Section.objects.get(code="IM-MLD")
    )


@pytest.fixture
def released(planner, cap):  # noqa: F811
    return orders.release(planner, for_stock(planner))


def test_the_new_role_and_area():
    rights = effective_access(person("tl2@sml.lk", "production_team_leader", divisions=["WS"]))
    assert rights.has("machine_time", "enter")
    assert not rights.has("machine_time", "approve")
    assert not rights.has("shop_floor", "enter")  # not the shift report
    pm = effective_access(person("pm2@sml.lk", "production_manager", divisions=["WS"]))
    assert pm.has("machine_time", "approve")
    clerk = effective_access(person("c@sml.lk", "clerk", divisions=["WS"]))
    assert not clerk.has("machine_time", "view")


def test_the_team_leader_starts_and_finishes_a_workshop_job(clock, leader, job):  # noqa: F811
    started = machine_jobs.start(
        leader, {"machine": "M-LAT-01", "job": f"{job.number}/20", "notes": "First batch"}
    )
    assert started.kind == "job" and started.operation.seq == 20
    assert started.drawing_no == job.drawing_no  # from the job
    assert started.description == started.operation.name
    board = machine_jobs.board(leader)
    lathe = next(m for m in board["machines"] if m["code"] == "M-LAT-01")
    assert lathe["status"] == "running" and lathe["jobs"][0]["job"] == job.number

    clock["now"] = at(12, 30)
    done = machine_jobs.finish(leader, started.pk, {"completed": "12", "rejected": "1"})
    assert done.ended_at == at(12, 30) and done.ended_by == leader
    payload = machine_jobs.payload(done)
    assert payload["minutes"] == 150 and payload["hours"] == "2.50"
    assert payload["completed"] == "12" and payload["rejected"] == "1"
    lathe = next(m for m in machine_jobs.board(leader)["machines"] if m["code"] == "M-LAT-01")
    assert lathe["status"] == "idle"
    with pytest.raises(MachineJobError, match="already finished"):
        machine_jobs.finish(leader, started.pk, {})


def test_moulding_by_order_and_shot_counter(clock, leader, press, released):  # noqa: F811
    with pytest.raises(MachineJobError, match="starting shot counter"):
        machine_jobs.start(leader, {"machine": "IMM-250", "order": released.number})
    started = machine_jobs.start(
        leader, {"machine": "IMM-250", "order": released.number, "start_counter": "1000"}
    )
    assert started.kind == "moulding" and started.mould == released.mould
    clock["now"] = at(11)
    with pytest.raises(MachineJobError, match="below the one at the start"):
        machine_jobs.finish(leader, started.pk, {"end_counter": "900"})
    done = machine_jobs.finish(leader, started.pk, {"end_counter": "1600"})
    assert done.end_counter == 1600 and machine_jobs.minutes(done) == 60


def test_one_running_job_per_machine_unless_the_manager_allows_a_second(
    clock,  # noqa: F811
    leader,
    manager,  # noqa: F811
    job,
):
    first = machine_jobs.start(leader, {"machine": "M-LAT-01", "job": f"{job.number}/20"})
    with pytest.raises(MachineJobError, match="already running"):
        machine_jobs.start(leader, {"machine": "M-LAT-01", "job": f"{job.number}/20"})
    with pytest.raises(MachineJobError, match="say why"):
        machine_jobs.start(manager, {"machine": "M-LAT-01", "job": f"{job.number}/20"})
    second = machine_jobs.start(
        manager,
        {"machine": "M-LAT-01", "job": f"{job.number}/20", "second_reason": "Two parts set up"},
    )
    assert second.second_allowed_by == manager
    lathe = next(m for m in machine_jobs.board(manager)["machines"] if m["code"] == "M-LAT-01")
    assert len(lathe["jobs"]) == 2
    # The database refuses a second running job nobody allowed.
    with pytest.raises(IntegrityError), transaction.atomic():
        MachineJob.objects.create(
            machine=first.machine,
            kind="job",
            job=job,
            operation=first.operation,
            description="x",
            started_at=at(9),
            started_by=leader,
        )


def test_checks(clock, leader, job, released, press):  # noqa: F811
    cases = [
        ({"machine": "M-BSW-01", "job": f"{job.number}/10"}, "not a machine of your sections"),
        ({"machine": "M-LAT-01", "job": job.number}, "Choose the operation"),
        ({"machine": "M-LAT-01", "job": f"{job.number}/30"}, "subcontractor"),
        ({"machine": "M-LAT-01", "job": "JO99/20"}, "not a released job"),
        ({"machine": "M-LAT-01", "job": f"{job.number}/20", "operator": "E999"}, "no employee"),
        (
            {"machine": "M-LAT-01", "job": f"{job.number}/20", "started_at": at(11).isoformat()},
            "future",
        ),
    ]
    Machine.objects.create(
        code="M-BSW-01", name="Band saw", section=Section.objects.get(code="M-BSW")
    )
    for values, message in cases:
        with pytest.raises(MachineJobError, match=message):
            machine_jobs.start(leader, values)
    Machine.objects.filter(code="IMM-250").update(status=Machine.Status.MAINTENANCE)
    with pytest.raises(MachineJobError, match="under maintenance"):
        machine_jobs.start(
            leader, {"machine": "IMM-250", "order": released.number, "start_counter": "1"}
        )
    assert (
        next(m for m in machine_jobs.board(leader)["machines"] if m["code"] == "IMM-250")["status"]
        == "maintenance"
    )
    started = machine_jobs.start(leader, {"machine": "M-LAT-01", "job": f"{job.number}/20"})
    with pytest.raises(MachineJobError, match="after the start"):
        machine_jobs.finish(
            leader, started.pk, {"ended_at": (at(10) - timedelta(minutes=5)).isoformat()}
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        MachineJob.objects.filter(pk=started.pk).update(ended_at=at(9))


def test_through_the_api(clock, leader, job):  # noqa: F811
    client = as_user(leader)
    options = client.get("/api/v1/machine-jobs/options/?machine=M-LAT-01").json()
    assert options["kind"] == "job"
    shaft_job = options["jobs"][0]
    assert shaft_job["number"] == job.number
    assert [op["card"] for op in shaft_job["operations"]] == [
        f"{job.number}/10",
        f"{job.number}/20",
    ]
    started = client.post(JOBS, {"machine": "M-LAT-01", "job": f"{job.number}/20"}, format="json")
    assert started.status_code == 201, started.json()
    assert (
        client.post(
            JOBS, {"machine": "M-LAT-01", "job": f"{job.number}/20"}, format="json"
        ).status_code
        == 400
    )
    clock["now"] = at(11)
    done = client.post(f"{JOBS}{started.json()['id']}/finish/", {"completed": "5"}, format="json")
    assert done.status_code == 200 and done.json()["minutes"] == 60
    assert client.get(JOBS).json()["results"][0]["id"] == started.json()["id"]
    # Another section's team leader sees nothing of it, and a clerk is refused.
    other = person("tl3@sml.lk", "production_team_leader", divisions=["WS"])
    other.all_sections = False
    other.save()
    assert as_user(other).get(BOARD).json()["machines"] == []
    assert (
        as_user(other).post(f"{JOBS}{started.json()['id']}/finish/", {}, format="json").status_code
        == 400
    )
    assert as_user(person("c2@sml.lk", "clerk", divisions=["WS"])).get(BOARD).status_code == 403
