"""Job cards and operation entry (backlog P3-12): printed cards with QR codes, the supervisor
scanning a card in a machining section's shift report, completed + rejected never above
what the operation before released, no overlapping times on a machine, minutes per piece
against standard, quantity available for the next operation, and approval as P3-09."""

from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.masters.models import Machine, Section
from apps.production import jobs, shift_approval, shift_reports
from apps.production.models import JobCardEntry, ShiftReport
from apps.production.shift_reports import ShiftReportError

from .test_access import as_user, person
from .test_job_orders import accountant, manager, planner, shaft, shafts  # noqa: F401
from .test_shift_reports import at, clock  # noqa: F401

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()


@pytest.fixture
def supervisor():
    user = person("wsup@sml.lk", "production_supervisor", divisions=["WS"])
    user.all_sections = False
    user.save()
    for code in ("M-BSW", "M-LAT"):
        Section.objects.get(code=code).supervisors.add(user)
    return user


@pytest.fixture
def job(planner, shaft):  # noqa: F811
    """20 shafts: 10 cut (M-BSW), 20 turn (M-LAT-01), 30 hard chrome (sent out)."""
    Machine.objects.create(
        code="M-BSW-01", name="Band saw", section=Section.objects.get(code="M-BSW")
    )
    return jobs.release(planner, shafts(planner))


def open_report(user, section):
    return shift_reports.open_report(
        user, {"section": section, "shift": "G", "day": TODAY.isoformat()}
    )


def line(job, op, **more):
    return {
        "job": f"{job.number}/{op}",
        "machine": "M-BSW-01" if op == 10 else "M-LAT-01",
        "start_time": "08:00",
        "end_time": "09:00",
        "completed": "0",
    } | more


def save(user, report, *rows, **more):
    return shift_reports.save(user, report, {"operations": list(rows)} | more)


def steps(job) -> dict:
    return {s["seq"]: s for s in jobs.payload(job, job.created_by)["progress"]}


def test_the_supervisor_scans_cards_and_parts_flow_from_operation_to_operation(
    clock,  # noqa: F811
    supervisor,
    job,
):
    saw = open_report(supervisor, "M-BSW")
    save(
        supervisor,
        saw,
        line(
            job,
            10,
            completed="18",
            rework="1",
            setup=True,
            rejects=[{"reason": "DIMENSION", "quantity": "1"}],
        ),
    )
    body = as_user(supervisor).get(f"/api/v1/shift-reports/{saw.pk}/").json()
    assert body["section_type"] == "machining"
    [entry] = body["operations"]
    assert (entry["job"], entry["operation"], entry["completed"], entry["rejected"]) == (
        job.number,
        10,
        "18",
        "1",
    )
    # 60 minutes over 19 pieces, against the routing's 2.5 a piece.
    assert (entry["minutes_per_piece"], entry["standard_minutes"]) == ("3.158", "2.5")
    assert [j["number"] for j in body["options"]["jobs"]] == [job.number]
    # The lathe has only the 18 pieces the saw released.
    lathe = open_report(supervisor, "M-LAT")
    with pytest.raises(
        ShiftReportError,
        match=r"19 completed and rejected is more than what operation 10 released \(18\)",
    ):
        save(supervisor, lathe, line(job, 20, completed="19"))
    save(
        supervisor,
        lathe,
        line(job, 20, completed="15", rejects=[{"reason": "SURFACE", "quantity": "2"}]),
        downtime=[
            {
                "machine": "M-LAT-01",
                "reason": "BREAKDOWN",
                "start_time": "08:00",
                "end_time": "08:09",
            }
        ],
    )
    # 51 minutes worked over 17 pieces.
    assert JobCardEntry.objects.get(report=lathe).minutes_per_piece == D("3.000")
    flow = steps(job)
    assert {
        k: flow[10][k]
        for k in ("received", "completed", "rejected", "rework", "in_hand", "available")
    } == {
        "received": "20",
        "completed": "18",
        "rejected": "1",
        "rework": "1",
        "in_hand": "1",
        "available": "1",
    }
    assert (flow[20]["received"], flow[20]["in_hand"], flow[20]["available"]) == ("18", "1", "15")
    # The plating is sent out: it finishes the parts only when they come back (P3-13).
    assert (flow[30]["subcontract"], flow[30]["in_hand"], flow[30]["finished"]) == (True, "15", "0")
    assert flow[30]["card"] == f"{job.number}/30"
    # The first operation never does more than the job's quantity.
    with pytest.raises(ShiftReportError, match=r"more than the job's quantity \(20\)"):
        save(
            supervisor,
            saw,
            line(job, 10, completed="18", rejects=[{"reason": "DIMENSION", "quantity": "1"}]),
            line(job, 10, completed="2", start_time="09:00", end_time="09:30"),
        )


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"job": "JO99999999/10"}, "is not a released job"),
        ({"job": "{job}/40"}, "has no operation 40"),
        ({"job": "{job}"}, "Choose the operation"),
        ({"job": "{job}/30"}, "sent out to a supplier"),
        ({"machine": "M-LAT-01"}, "M-LAT-01 is not a machine of this section"),
        ({"completed": "0"}, "Give the pieces completed"),
        ({"completed": "1.0001"}, "at most 3 decimal places"),
        ({"rejects": [{"reason": "FLASH", "quantity": "1"}]}, "Choose a reject reason"),
        ({"operator": "E999"}, "no employee E999"),
        ({"end_time": "07:00"}, "outside"),
    ],
)
def test_entries_are_checked(clock, supervisor, job, row, message):  # noqa: F811
    saw = open_report(supervisor, "M-BSW")
    row = {k: (v.format(job=job.number) if isinstance(v, str) else v) for k, v in row.items()}
    with pytest.raises(ShiftReportError, match=message):
        save(supervisor, saw, line(job, 10, completed="1") | row)


def test_times_on_a_machine_never_overlap_and_moulding_runs_are_not_job_cards(
    clock,  # noqa: F811
    supervisor,
    job,
):
    saw = open_report(supervisor, "M-BSW")
    with pytest.raises(ShiftReportError, match="overlap"):
        save(
            supervisor,
            saw,
            line(job, 10, completed="5"),
            line(job, 10, completed="5", start_time="08:30", end_time="09:30"),
        )
    with pytest.raises(ShiftReportError, match="enters job card operations, not runs"):
        shift_reports.save(supervisor, saw, {"runs": [{"machine": "M-BSW-01"}]})
    save(supervisor, saw, line(job, 10, completed="5"))
    entry = JobCardEntry.objects.get(report=saw)
    with pytest.raises(DatabaseError, match="never overlap"), transaction.atomic():
        JobCardEntry.objects.create(
            report=saw,
            job=job,
            operation=entry.operation,
            machine=entry.machine,
            started_at=at(8, 30),
            ended_at=at(9, 30),
            completed=1,
        )


def test_the_report_is_submitted_locked_and_approved(clock, supervisor, manager, job):  # noqa: F811
    lathe = open_report(supervisor, "M-LAT")
    with pytest.raises(ShiftReportError, match="Enter at least one run, job card or downtime"):
        shift_reports.submit(supervisor, lathe)
    saw = open_report(supervisor, "M-BSW")
    save(supervisor, saw, line(job, 10, completed="20"))
    shift_reports.submit(supervisor, saw)
    with pytest.raises(DatabaseError, match="locked"), transaction.atomic():
        JobCardEntry.objects.filter(report=saw).update(completed=19)
    shift_approval.decide(manager, saw, "approve")
    saw.refresh_from_db()
    assert (saw.status, saw.stock_issue_id, saw.receipt_entry_id) == (
        ShiftReport.Status.APPROVED,
        None,
        None,
    )


def test_the_job_cards_are_printed_for_a_released_job(planner, job):  # noqa: F811
    printed = as_user(planner).get(f"/api/v1/job-orders/{job.pk}/cards/")
    assert printed.status_code == 200
    assert printed["Content-Type"] == "application/pdf" and printed.content.startswith(b"%PDF")
    draft = shafts(planner)
    refused = as_user(planner).get(f"/api/v1/job-orders/{draft.pk}/cards/")
    assert refused.status_code == 400
    assert as_user(planner).get(f"/api/v1/job-orders/{draft.pk}/").json()["progress"] == []
