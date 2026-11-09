"""Inspection on jobs (backlog P3-14): first-article, in-process and final inspections with
measurements per piece from the part's inspection plan; a failed one holds the job until
the Production Manager decides rework, scrap or acceptance under deviation (the Director
when a critical check failed); decided inspections never change (database)."""

from decimal import Decimal as D

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError

from apps.core.models import Notification
from apps.inventory.models import InspectionParameter, InspectionPlan, Item
from apps.production import job_inspections as qc
from apps.production import jobs, subcontract
from apps.production.job_inspections import JobInspectionError
from apps.production.jobs import JobError
from apps.production.models import JobInspection, JobInspectionResult
from apps.production.shift_reports import ShiftReportError

from .test_access import as_user, person
from .test_job_cards import job, line, open_report, save, steps, supervisor  # noqa: F401
from .test_job_orders import accountant, manager, planner, shaft, shafts  # noqa: F401
from .test_shift_reports import clock  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def inspector():
    return person("qc@sml.lk", "qc_inspector", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def turned(clock, supervisor, job, inspector):  # noqa: F811
    """SH-100's plan: diameter 49.98-50.00 mm (critical) and a pass/fail surface check.
    18 shafts cut, 15 turned."""
    plan = InspectionPlan.objects.create(
        name="Drive shaft", item=Item.objects.get(code="SH-100"), created_by=inspector
    )
    InspectionParameter.objects.create(
        plan=plan,
        position=1,
        name="Diameter",
        kind="number",
        minimum=D("49.98"),
        maximum=D("50.00"),
        unit="mm",
        critical=True,
    )
    InspectionParameter.objects.create(plan=plan, position=2, name="Surface", kind="pass_fail")
    save(supervisor, open_report(supervisor, "M-BSW"), line(job, 10, completed="18"))
    lathe = open_report(supervisor, "M-LAT")
    save(supervisor, lathe, line(job, 20, completed="15"))
    return {"job": job, "lathe": lathe}


def inspect(inspector, job, stage="in_process", operation="20", pieces="2", **more):  # noqa: F811
    return qc.start(
        inspector, job, {"stage": stage, "operation": operation, "pieces": pieces} | more
    )


def results(inspection, diameters, surface=True):
    rows = [{"position": 1, "piece": n, "value": v} for n, v in enumerate(diameters, start=1)]
    rows += [{"position": 2, "piece": n, "passed": surface} for n in range(1, len(diameters) + 1)]
    return {"results": rows}


def test_a_first_article_inspection_from_the_plan_passes(inspector, turned):
    job = turned["job"]  # noqa: F811
    started = as_user(inspector).post(
        f"/api/v1/job-orders/{job.pk}/inspect/",
        {"stage": "first_article", "operation": "10", "pieces": "2"},
        format="json",
    )
    assert started.status_code == 200, started.json()
    [shown] = started.json()["inspections"]
    assert (shown["stage_label"], shown["operation"], shown["can_enter"]) == (
        "First article",
        10,
        True,
    )
    assert [(c["name"], c["minimum"], c["maximum"], len(c["pieces"])) for c in shown["checks"]] == [
        ("Diameter", "49.98", "50", 2),
        ("Surface", "", "", 2),
    ]
    inspection = JobInspection.objects.get(job=job)
    with pytest.raises(JobInspectionError, match="being done"):
        inspect(inspector, job)
    with pytest.raises(JobInspectionError, match="Enter every result first: Diameter, piece 1"):
        qc.finish(inspector, inspection)
    done = as_user(inspector).post(
        f"/api/v1/job-orders/inspections/{inspection.pk}/finish/",
        results(inspection, ["49.99", "50.000"]),
        format="json",
    )
    assert done.status_code == 200, done.json()
    assert done.json()["inspections"][0]["status"] == "passed" and done.json()["on_hold"] is False
    with pytest.raises(DatabaseError, match="never changes"), transaction.atomic():
        JobInspection.objects.filter(pk=inspection.pk).update(notes="x")
    with pytest.raises(DatabaseError, match="never change"), transaction.atomic():
        JobInspectionResult.objects.filter(inspection=inspection).update(value=1)
    with pytest.raises(DatabaseError, match="never deleted"), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM production_jobinspection")


def test_a_failed_inspection_holds_the_job_until_the_production_manager_decides(
    django_capture_on_commit_callbacks,
    inspector,
    manager,  # noqa: F811
    planner,  # noqa: F811
    supervisor,  # noqa: F811
    turned,  # noqa: F811
):
    job = turned["job"]  # noqa: F811
    inspection = inspect(inspector, job)
    qc.save(inspector, inspection, results(inspection, ["50.02", "49.99"]))
    with django_capture_on_commit_callbacks(execute=True):
        qc.finish(inspector, inspection)
    told = Notification.objects.filter(event="job_on_hold")
    assert [(n.user, n.title) for n in told] == [
        (manager, f"{job.number} is on hold: in process inspection failed")
    ]
    inspection.refresh_from_db()
    assert inspection.status == "on_hold"
    # Held: no work entered, nothing sent out, not completed.
    with pytest.raises(ShiftReportError, match="on hold after a failed inspection"):
        save(supervisor, turned["lathe"], line(job, 20, completed="16"))
    with pytest.raises(subcontract.SubcontractError, match="on hold"):
        subcontract.send_out(planner, job, {"operation": "30", "quantity": "1"})
    with pytest.raises(JobError, match="on hold"):
        jobs.complete(planner, job)
    # Only the Production Manager decides, with a reason and pieces within what was done.
    with pytest.raises(JobInspectionError, match="The Production Manager decides"):
        qc.decide(planner, inspection, {"decision": "rework", "quantity": "2", "reason": "x"})
    with pytest.raises(JobInspectionError, match="reason"):
        qc.decide(manager, inspection, {"decision": "rework", "quantity": "2"})
    with pytest.raises(JobInspectionError, match="has 15 pieces completed"):
        qc.decide(
            manager, inspection, {"decision": "rework", "quantity": "16", "reason": "Oversize"}
        )
    decided = as_user(manager).post(
        f"/api/v1/job-orders/inspections/{inspection.pk}/decide/",
        {"decision": "rework", "quantity": "3", "reason": "Oversize: take another pass"},
        format="json",
    )
    assert decided.status_code == 200, decided.json()
    assert decided.json()["on_hold"] is False
    # The 3 pieces are back at the lathe: no longer completed there.
    flow = steps(job)
    assert (flow[20]["completed"], flow[20]["rework"], flow[20]["in_hand"]) == ("12", "3", "6")
    # The 3 reworked pieces are completed again: 18 entered, 15 good after the rework.
    save(supervisor, turned["lathe"], line(job, 20, completed="18"))
    assert steps(job)[20]["completed"] == "15"
    # A scrap decision on the next failure rejects the pieces at the operation.
    again = inspect(inspector, job, pieces="1")
    qc.save(inspector, again, results(again, ["49.99"], surface=False))
    qc.finish(inspector, again)
    qc.decide(manager, again, {"decision": "scrap", "quantity": "1", "reason": "Scored surface"})
    flow = steps(job)
    assert (flow[20]["completed"], flow[20]["rejected"]) == ("14", "1")


def test_a_deviation_on_a_critical_check_needs_the_director(inspector, manager, director, turned):  # noqa: F811
    job = turned["job"]  # noqa: F811
    inspection = inspect(inspector, job, stage="final")
    assert inspection.operation.seq == 30  # final: after the last operation
    qc.save(inspector, inspection, results(inspection, ["50.01", "50.00"]))
    qc.finish(inspector, inspection)
    qc.decide(manager, inspection, {"decision": "deviation", "reason": "Customer accepts +0.01"})
    inspection.refresh_from_db()
    assert inspection.status == "deviation_requested"
    with pytest.raises(JobError, match="on hold"):
        jobs.complete(manager, job)
    body = as_user(director).get(f"/api/v1/job-orders/{job.pk}/").json()
    assert body["inspections"][0]["can_approve"] is True
    as_user(director).post(
        f"/api/v1/job-orders/inspections/{inspection.pk}/director/",
        {"action": "reject", "reason": "Ask the customer in writing first"},
        format="json",
    )
    inspection.refresh_from_db()
    assert (inspection.status, inspection.decision) == ("on_hold", "")
    qc.decide(
        manager, inspection, {"decision": "deviation", "reason": "Customer's letter of 9 Nov"}
    )
    qc.director_decides(director, inspection, "approve")
    inspection.refresh_from_db()
    assert (inspection.status, inspection.decision) == ("decided", "deviation")
    assert jobs.payload(job, manager)["on_hold"] is False


def test_checks_are_added_where_there_is_no_plan(inspector, planner, shaft):  # noqa: F811
    job = jobs.release(planner, jobs.update(planner, shafts(planner), {}))  # noqa: F811
    with pytest.raises(JobInspectionError, match="no inspection plan for this part"):
        inspect(inspector, job, operation="10")
    with pytest.raises(JobInspectionError, match="Only the QC Inspector"):
        inspect(planner, job, operation="10")
    with pytest.raises(JobInspectionError, match="Choose the operation"):
        inspect(inspector, job, operation="99", checks=[{"name": "Length", "maximum": "120"}])
    made = inspect(
        inspector,
        job,
        operation="10",
        pieces="3",
        checks=[{"name": "Length", "minimum": "119.5", "maximum": "120.5", "unit": "mm"}],
    )
    assert made.results.count() == 3
    other = person("qc2@sml.lk", "qc_inspector", all_divisions=True)
    with pytest.raises(JobInspectionError, match="who started it"):
        qc.save(other, made, {"results": []})
