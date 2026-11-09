"""Production reports (backlog P3-20 part 1): daily production, rejects by reason, part,
mould and machine, downtime Pareto, machining jobs' time against estimate and on-time
delivery, material against standard and regrind, moulds approaching maintenance."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from apps.accounting import report_builder as rb
from apps.masters.models import Section
from apps.production import jobs, reports, shift_approval, shift_reports
from apps.production.models import CostRate, Mould, ProductionReceipt

from .test_access import as_user
from .test_job_cards import line, open_report, save  # noqa: F401
from .test_job_cards import supervisor as ws_supervisor  # noqa: F401
from .test_job_orders import accountant, manager, planner, shaft, storeman  # noqa: F401
from .test_oee import week  # noqa: F401
from .test_production_orders import cap, for_stock  # noqa: F401
from .test_shift_reports import TODAY, at, clock, press, supervisor  # noqa: F401

pytestmark = pytest.mark.django_db
URL = "/api/v1/production-reports/"
TURN = {"seq": 10, "name": "Turn", "section": "M-LAT", "setup_min": "30", "run_min": "5"}


def test_daily_production_rejects_and_downtime(manager, week):  # noqa: F811
    day = reports.daily(manager, TODAY, TODAY)
    [row] = day["rows"]
    assert row == {
        "day": TODAY,
        "section": "IM-MLD",
        "machine": "IMM-250",
        "shift": "G",
        "good": "3960",
        "rejected": "40",
        "reject_pct": "1.0",
        "run_h": "2.00",
        "stopped_h": "6.00",
    }
    by_reason = reports.rejects(manager, TODAY, TODAY, "reason")["rows"]
    assert [(r["key"], r["rejected"], r["share_pct"]) for r in by_reason] == [
        ("FLASH", "40", "100.0")
    ]
    by_mould = reports.rejects(manager, TODAY, TODAY, "mould")["rows"]
    assert [(r["key"], r["made"], r["reject_pct"]) for r in by_mould] == [("MD-001", "4000", "1.0")]
    assert reports.rejects(manager, TODAY, TODAY, "part")["rows"][0]["key"] == "CAP-28"
    with pytest.raises(reports.ReportError):
        reports.rejects(manager, TODAY, TODAY, "colour")
    stops = reports.downtime(manager, TODAY, TODAY)
    assert [
        (r["key"], r["hours"], r["planned"], r["cumulative_pct"]) for r in stops["reasons"]
    ] == [("NO-PLAN", "6.00", True, "100.0")]
    assert stops["machines"][0]["key"] == "IMM-250"


def test_material_against_standard_and_moulds_due(manager, week):  # noqa: F811
    found = reports.material(manager, TODAY, TODAY)
    resin = next(r for r in found["rows"] if r["item"] == "PP-H")
    # Nothing was entered as issued by the supervisor: all the standard is a shortfall.
    assert resin["issued"] == "0" and D(resin["standard"]) > 0
    assert D(resin["difference"]) == -D(resin["standard"])
    assert ProductionReceipt.objects.filter(report=week).exists()
    Mould.objects.filter(code="MD-001").update(pm_interval_shots=500)
    [due] = reports.moulds_due(manager)
    assert (due["mould"], due["state"], due["shots_since"], due["used_pct"]) == (
        "MD-001",
        "due",
        500,
        "100.0",
    )


def test_jobs_time_against_estimate_and_on_time(
    django_capture_on_commit_callbacks,
    clock,  # noqa: F811
    planner,  # noqa: F811
    manager,  # noqa: F811
    accountant,  # noqa: F811
    ws_supervisor,  # noqa: F811
    shaft,  # noqa: F811
):
    lathe = Section.objects.get(code="M-LAT")
    for kind, rate in (("labour", "600"), ("overhead", "400")):
        CostRate.objects.create(
            kind=kind, section=lathe, rate=D(rate), effective_from=date(2026, 1, 1), reason="t"
        )
    due = TODAY + timedelta(days=3)
    job = jobs.release(
        planner,
        jobs.create(
            planner,
            {
                "purpose": "tools",
                "division": "WS",
                "item": "SH-100",
                "quantity": "20",
                "due_date": due.isoformat(),
                "operations": [
                    {
                        "seq": 10,
                        "name": "Turn",
                        "section": "M-LAT",
                        "setup_min": "30",
                        "run_min": "5",
                    }
                ],
            },
        ),
    )
    with django_capture_on_commit_callbacks(execute=True):
        report = open_report(ws_supervisor, "M-LAT")
        save(
            ws_supervisor,
            report,
            line(job, 10, completed="20", machine="M-LAT-01", end_time="10:00"),
        )
        shift_reports.submit(ws_supervisor, report)
        shift_approval.decide(manager, report, "approve")
    jobs.complete(planner, job)
    found = reports.jobs(accountant, TODAY, due)
    [row] = found["rows"]
    # 30 + 5 × 20 minutes estimated; 2 hours on the card.
    assert (row["estimated_h"], row["actual_h"], row["time_variance_pct"]) == (
        "2.17",
        "2.00",
        "-7.7",
    )
    assert (row["on_time"], row["days_late"], row["actual_cost"]) == (True, 0, "2000.00")
    assert (found["completed"], found["on_time"], found["on_time_pct"]) == (1, 1, "100.0")
    # Without access to costs the money is left out.
    assert reports.jobs(planner, TODAY, due)["rows"][0]["actual_cost"] is None


def test_the_reports_page_answers_by_kind(manager, planner, week):  # noqa: F811
    client = as_user(manager)
    body = client.get(f"{URL}daily/?start={TODAY}&end={TODAY}&section=IM-MLD").json()
    assert body["total"]["good"] == "3960"
    assert client.get(f"{URL}rejects/?by=machine").json()["rows"][0]["key"] == "IMM-250"
    assert client.get(f"{URL}moulds/").status_code == 200
    assert client.get(f"{URL}sections/").json()["sections"]
    assert client.get(f"{URL}nothing/").status_code == 404
    assert client.get(f"{URL}daily/?start={TODAY}&end=2000-01-01").status_code == 400
    assert as_user(planner).get(f"{URL}downtime/").status_code == 200


def test_moulding_runs_and_downtime_in_the_report_builder(manager, week):  # noqa: F811
    runs = rb.run(
        manager,
        rb.parse(
            manager,
            {
                "source": "moulding_runs",
                "columns": ["machine", "good", "rejected", "shots", "hours"],
            },
        ),
    )
    line = runs["rows"][0]["cells"]
    assert (line["machine"], line["good"], line["rejected"], line["shots"], line["hours"]) == (
        "IMM-250",
        "3960",
        "40",
        "500",
        "2",
    )
    by_month = rb.run(
        manager,
        rb.parse(
            manager,
            {
                "source": "moulding_runs",
                "columns": ["machine", "good"],
                "group_by": "machine",
                "period": "month",
                "measure": "good",
            },
        ),
    )
    assert by_month["rows"][0]["cells"]["total"] == "3960"
    stops = rb.run(
        manager, rb.parse(manager, {"source": "downtime", "columns": ["reason", "hours"]})
    )
    assert stops["rows"][0]["cells"]["hours"] == "6"
