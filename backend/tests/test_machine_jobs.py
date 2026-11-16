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


# --- P3-24 c: into the shift report ---------------------------------------------------------


@pytest.fixture
def mould_supervisor():
    user = person("msup@sml.lk", "production_supervisor", divisions=["IM"])
    user.all_sections = False
    user.save()
    Section.objects.get(code="IM-MLD").supervisors.add(user)
    return user


def test_a_finished_moulding_job_is_offered_to_the_shift_report_once(
    clock,  # noqa: F811
    leader,
    mould_supervisor,
    press,
    released,
):
    from apps.production import shift_reports

    clock["now"] = at(8)
    started = machine_jobs.start(
        leader, {"machine": "IMM-250", "order": released.number, "start_counter": "1000"}
    )
    report = shift_reports.open_report(
        mould_supervisor, {"section": "IM-MLD", "shift": "G", "day": at(8).date().isoformat()}
    )
    # Still running during the shift: not offered yet.
    assert shift_reports.payload(report, mould_supervisor)["options"]["machine_time"] == []
    clock["now"] = at(10)
    machine_jobs.finish(leader, started.pk, {"end_counter": "1500"})
    offered = shift_reports.payload(report, mould_supervisor)["options"]["machine_time"]
    assert offered == [
        {
            "machine_job": started.pk,
            "machine": "IMM-250",
            "operator": "",
            "start_time": "08:00",
            "end_time": "10:00",
            "started_by": leader.full_name,
            "running": False,
            "kind": "moulding",
            "order": released.pk,
            "order_number": released.number,
            "mould": released.mould.code,
            "start_counter": 1000,
            "end_counter": 1500,
        }
    ]
    line = {k: offered[0][k] for k in ("machine", "order", "start_time", "end_time", "machine_job")}
    shift_reports.save(
        mould_supervisor,
        report,
        {"runs": [line | {"start_counter": "1000", "end_counter": "1500"}]},
    )
    assert report.runs.get().machine_job == started
    assert shift_reports.payload(report, mould_supervisor)["options"]["machine_time"] == []
    assert shift_reports.payload(report, mould_supervisor)["runs"][0]["machine_job"] == started.pk


def test_a_job_across_a_shift_change_is_split_and_its_figures_shared_by_time(
    clock,  # noqa: F811
    leader,
    mould_supervisor,
    press,
    released,
):
    from apps.production import shift_reports

    clock["now"] = at(15)
    started = machine_jobs.start(
        leader, {"machine": "IMM-250", "order": released.number, "start_counter": "1000"}
    )
    clock["now"] = at(19)
    machine_jobs.finish(leader, started.pk, {"end_counter": "1401"})
    report = shift_reports.open_report(
        mould_supervisor, {"section": "IM-MLD", "shift": "G", "day": at(8).date().isoformat()}
    )
    (line,) = machine_jobs.for_report(report, at(8), at(17))
    assert (line["start_time"], line["end_time"]) == ("15:00", "17:00")
    assert (line["start_counter"], line["end_counter"]) == (1000, 1200)  # half the time
    (rest,) = machine_jobs.for_report(report, at(17), at(23))
    assert (rest["start_counter"], rest["end_counter"]) == (1200, 1401)


def test_pieces_shared_by_time_always_add_up():
    job = MachineJob(started_at=at(7), ended_at=at(9))
    from decimal import Decimal as D

    from apps.production.machine_jobs import _piece_part

    first = _piece_part(job, D("11"), at(7), at(8), at(9))
    second = _piece_part(job, D("11"), at(8), at(9), at(9))
    assert (first, second) == ("5", "6")
    assert _piece_part(job, D("11"), at(7), at(9), at(9)) == "11"
    assert _piece_part(MachineJob(started_at=at(7)), D("11"), at(7), at(8), at(9)) == ""


# --- P3-24 d: the Dashboard ---------------------------------------------------------------------


def test_the_dashboard_counts_machines_and_hours_today(
    clock,  # noqa: F811
    leader,
    manager,  # noqa: F811
    job,
    press,
    released,
):
    Machine.objects.create(
        code="M-LAT-02", name="Lathe 2", section=Section.objects.get(code="M-LAT")
    )
    Machine.objects.filter(code="IMM-250").update(status=Machine.Status.MAINTENANCE)
    clock["now"] = at(8)
    first = machine_jobs.start(leader, {"machine": "M-LAT-01", "job": f"{job.number}/20"})
    clock["now"] = at(9, 30)
    machine_jobs.finish(leader, first.pk, {"completed": "4"})
    machine_jobs.start(leader, {"machine": "M-LAT-01", "job": f"{job.number}/20"})
    clock["now"] = at(10)
    d = as_user(manager).get("/api/v1/machine-jobs/today/").json()
    assert d["counts"] == {"running": 1, "idle": 1, "maintenance": 1}
    assert [m["code"] for m in d["running"]] == ["M-LAT-01"]
    assert d["running"][0]["jobs"][0]["minutes"] == 30
    assert d["running"][0]["jobs"][0]["started_by"] == leader.full_name
    assert d["idle"] == ["M-LAT-02"] and d["maintenance"] == ["IMM-250"]
    assert [(f["job"], f["minutes"]) for f in d["finished"]] == [(job.number, 90)]
    lathe = next(h for h in d["hours"] if h["machine"] == "M-LAT-01")
    assert lathe["minutes"] == 120 and lathe["pct"] == "20.0"  # 2 h of the 10 h so far


def test_the_dashboard_panel_shows_only_your_own_sections(clock, leader, job):  # noqa: F811
    clock["now"] = at(8)
    machine_jobs.start(leader, {"machine": "M-LAT-01", "job": f"{job.number}/20"})
    clock["now"] = at(9)
    today = "/api/v1/machine-jobs/today/"
    # The team leader of the section sees the running lathe.
    mine = as_user(leader).get(today).json()
    assert [m["code"] for m in mine["running"]] == ["M-LAT-01"]
    # A team leader of other sections sees none of it.
    other = person("tl4@sml.lk", "production_team_leader", divisions=["WS"])
    other.all_sections = False
    other.save()
    theirs = as_user(other).get(today).json()
    assert theirs["running"] == [] and theirs["finished"] == [] and theirs["hours"] == []
    assert theirs["counts"] == {"running": 0, "idle": 0, "maintenance": 0}
    # Someone without machine time is refused.
    assert as_user(person("c3@sml.lk", "clerk", divisions=["WS"])).get(today).status_code == 403


# --- P3-24 e: machine hours report -----------------------------------------------------------


def test_machine_hours_estimate_against_actual_and_cost(
    clock,  # noqa: F811
    leader,
    manager,  # noqa: F811
    job,
):
    from decimal import Decimal as D

    from apps.production.models import CostRate

    lathe = Machine.objects.get(code="M-LAT-01")
    CostRate.objects.create(
        kind="overhead",
        section=lathe.section,
        machine=lathe,
        rate=D("1200.00"),
        effective_from=at(8).date() - timedelta(days=30),
        reason="t",
    )
    op = job.operations.get(seq=20)
    clock["now"] = at(8)
    first = machine_jobs.start(leader, {"machine": "M-LAT-01", "job": f"{job.number}/20"})
    clock["now"] = at(10)
    machine_jobs.finish(leader, first.pk, {"completed": "10"})
    day = at(8).date().isoformat()
    url = f"/api/v1/machine-jobs/hours/?start={day}&end={day}&by=day"

    d = as_user(manager).get(url).json()
    lathe_row = next(m for m in d["machines"] if m["machine"] == "M-LAT-01")
    assert lathe_row["hours"] == "2.00"
    assert lathe_row["utilisation"] == "20.0"  # 2 h of the 10 h of today so far
    (row,) = d["jobs"]
    estimate = (op.setup_min + op.run_min * 10) / 60
    assert row["estimate_hours"] == str(estimate.quantize(D("0.01")))
    assert row["over"] == (D(120) > op.setup_min + op.run_min * 10)
    assert "cost" in row  # the manager may see costs (order profitability)
    assert row["cost"] == "2400.00" and row["rate"] == "1200.00"

    # A team leader sees the hours but no costs.
    led = as_user(leader).get(url).json()
    assert led["show_cost"] is False and "cost" not in led["jobs"][0]
    assert as_user(manager).get(url.replace("by=day", "by=year")).status_code == 400


def test_machine_hours_show_only_your_own_sections(clock, leader, job):  # noqa: F811
    clock["now"] = at(8)
    first = machine_jobs.start(leader, {"machine": "M-LAT-01", "job": f"{job.number}/20"})
    clock["now"] = at(9)
    machine_jobs.finish(leader, first.pk, {"completed": "2"})
    day = at(8).date().isoformat()
    url = f"/api/v1/machine-jobs/hours/?start={day}&end={day}&by=day"
    assert [r["job"] for r in as_user(leader).get(url).json()["jobs"]] == [job.number]
    # A team leader of other sections sees none of these jobs.
    other = person("tl5@sml.lk", "production_team_leader", divisions=["WS"])
    other.all_sections = False
    other.save()
    assert as_user(other).get(url).json()["jobs"] == []
    # Someone without machine time is refused.
    assert as_user(person("c4@sml.lk", "clerk", divisions=["WS"])).get(url).status_code == 403
