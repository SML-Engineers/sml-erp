"""Moulding shift reports (backlog P3-08): the supervisor's own sections, entry only during
the shift and the grace period, runs with good quantity (shots × cavities − rejects) and
actual cycle time, shot counters never going down, rejects never above what was made,
times on one machine never overlapping (service and database), downtime, material and
manpower, the summary, and a submitted report locked (database)."""

from datetime import datetime, time, timedelta
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.masters.models import Machine, Section
from apps.production import orders, shift_reports
from apps.production.models import MouldingRun, ReasonCode, ShiftReport
from apps.production.shift_reports import ShiftReportError

from .test_access import as_user, person
from .test_employees import add as add_employee
from .test_payroll import hr  # noqa: F401
from .test_production_orders import cap, for_stock, manager, planner, stock, storeman  # noqa: F401

pytestmark = pytest.mark.django_db
URL = "/api/v1/shift-reports/"
TODAY = timezone.localdate()


def at(hour, minute=0, day=TODAY):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


@pytest.fixture
def clock(monkeypatch):
    """Freeze the clock (default 10:00 today, during the General shift 08:00-17:00)."""
    moment = {"now": at(10)}
    monkeypatch.setattr(timezone, "now", lambda: moment["now"])
    return moment


@pytest.fixture
def supervisor():
    user = person("sup@sml.lk", "production_supervisor", divisions=["IM"])
    user.all_sections = False
    user.save()
    Section.objects.get(code="IM-MLD").supervisors.add(user)
    return user


@pytest.fixture
def press():
    return Machine.objects.create(
        code="IMM-250", name="Haitian 250 t", section=Section.objects.get(code="IM-MLD")
    )


@pytest.fixture
def released(planner, cap):  # noqa: F811
    return orders.release(planner, for_stock(planner))


@pytest.fixture
def report(clock, supervisor, press, released):
    return shift_reports.open_report(
        supervisor, {"section": "IM-MLD", "shift": "G", "day": TODAY.isoformat()}
    )


def run(prod, **more):
    return {
        "machine": "IMM-250",
        "order": prod.pk,
        "start_time": "08:00",
        "end_time": "10:00",
        "start_counter": "1000",
        "end_counter": "1500",
        "rejects": [{"reason": "FLASH", "quantity": "40"}],
    } | more


def test_the_supervisor_enters_a_shift_and_the_system_works_it_out(
    report,
    supervisor,
    released,
    storeman,  # noqa: F811
    hr,  # noqa: F811
):
    stock("PP-H", "100", storeman)
    operator = add_employee(hr, number="E010", division="IM")
    operator.section = Section.objects.get(code="IM-MLD")
    operator.save()
    opened = as_user(supervisor).get(URL).json()
    general = next(s for s in opened["open"] if s["shift"] == "G")
    assert (general["section"], general["report"], general["status"]) == (
        "IM-MLD",
        report.pk,
        "draft",
    )
    body = {
        "runs": [run(released, material_lot="l1", operator="E010")],
        "downtime": [
            {
                "machine": "IMM-250",
                "reason": "MOULD-CHANGE",
                "start_time": "09:00",
                "end_time": "09:20",
                "remarks": "Colour change",
            },
        ],
        "materials": [
            {"kind": "issue", "lot_no": "L1", "quantity": "25"},
            {"kind": "return", "lot_no": "L1", "quantity": "5.5"},
            {"kind": "regrind", "item": "PP-H", "quantity": "1.2"},
        ],
        "manpower": [{"machine": "IMM-250", "people": "2", "overtime_hours": "1.5"}],
        "notes": "Heater 3 replaced",
    }
    saved = as_user(supervisor).put(f"{URL}{report.pk}/", body, format="json")
    assert saved.status_code == 200, saved.json()
    data = saved.json()
    r = data["runs"][0]
    # 500 shots × 8 cavities − 40 rejects; 100 minutes running (2 h less 20 min of
    # downtime) over 500 shots = 12 s a shot.
    assert (r["shots"], r["cavities"], r["good_quantity"]) == (500, 8, "3960")
    assert (r["actual_cycle_s"], r["standard_cycle_s"]) == ("12", "12")
    assert (r["material"], r["material_lot"], r["operator"]) == ("PP-H", "L1", "E010")
    s = data["summary"]
    assert (s["shots"], s["made"], s["good"], s["rejects"], s["reject_pct"]) == (
        500,
        4000,
        "3960",
        40,
        "1",
    )
    assert s["downtime_minutes"] == 20 and s["regrind"] == "1.2"
    # 19.5 kg used for 3,960 good caps: 4.924 g a cap.
    assert s["material"] == [
        {"item": "PP-H", "used": "19.5", "unit": "kg", "grams_per_good": "4.924"}
    ]
    assert (s["people"], s["overtime_hours"]) == (2, "1.5")
    assert {o["code"] for o in data["options"]["machines"]} == {"IMM-250"}
    assert data["options"]["operators"] == [{"number": "E010", "name": "Kamal Perera"}]

    done = as_user(supervisor).post(f"{URL}{report.pk}/submit/")
    assert done.status_code == 200 and done.json()["status"] == "submitted"
    assert done.json()["editable"] is False
    assert ReasonCode.objects.get(division__code="IM", code="FLASH").first_used_at is not None
    # Locked: the service and the database refuse changes.
    again = as_user(supervisor).put(f"{URL}{report.pk}/", body, format="json")
    assert again.status_code == 400 and "locked" in again.json()["detail"]
    with pytest.raises(DatabaseError, match="locked"), transaction.atomic():
        MouldingRun.objects.filter(report=report).update(end_counter=9999)
    with pytest.raises(DatabaseError, match="locked"), transaction.atomic():
        ShiftReport.objects.filter(pk=report.pk).update(notes="x")
    with pytest.raises(DatabaseError, match="locked"), transaction.atomic():
        ShiftReport.objects.filter(pk=report.pk).update(status="draft")


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"machine": "IMM-999"}, "not a machine of this section"),
        ({"order": "0"}, "Choose a released production order"),
        ({"start_time": "7:00"}, "outside General"),
        ({"end_time": "18:00"}, "outside General"),
        ({"start_time": "eight"}, "as HH:MM"),
        ({"end_time": "08:00"}, "end time of run 1 .IMM-250. is after its start"),
        ({"end_counter": "900"}, "goes down .1000 to 900."),
        ({"start_counter": "-1"}, "start of run 1 .IMM-250. is at least 0"),
        ({"start_counter": "1e3"}, "whole number"),
        ({"rejects": [{"reason": "FLASH", "quantity": "4001"}]}, "more than it made"),
        ({"rejects": [{"reason": "BREAKDOWN", "quantity": "1"}]}, "Choose a reject reason"),
        ({"rejects": [{"reason": "FLASH", "quantity": "0"}]}, "more than 0"),
        ({"material_lot": "NOPE"}, "no material batch NOPE"),
        ({"operator": "E999"}, "no employee E999"),
    ],
)
def test_runs_are_checked(report, supervisor, released, changes, message):
    with pytest.raises(ShiftReportError, match=message):
        shift_reports.save(supervisor, report, {"runs": [run(released, **changes)]})
    assert not MouldingRun.objects.exists()


def test_times_never_overlap_and_counters_never_go_down(report, supervisor, released):
    twice = [run(released), run(released, start_time="09:30", end_time="11:00")]
    with pytest.raises(ShiftReportError, match="overlap"):
        shift_reports.save(supervisor, report, {"runs": twice})
    back = [
        run(released),
        run(
            released,
            start_time="10:00",
            end_time="11:00",
            start_counter="1400",
            end_counter="1600",
            rejects=[],
        ),
    ]
    with pytest.raises(ShiftReportError, match="starts at 1400, below the last reading 1500"):
        shift_reports.save(supervisor, report, {"runs": back})
    stops = [
        {"machine": "IMM-250", "reason": "POWER", "start_time": "08:10", "end_time": "08:40"},
        {"machine": "IMM-250", "reason": "SETUP", "start_time": "08:30", "end_time": "08:50"},
    ]
    with pytest.raises(ShiftReportError, match="downtime 1 .* and downtime 2 .* overlap"):
        shift_reports.save(supervisor, report, {"downtime": stops})
    with pytest.raises(ShiftReportError, match="Choose the reason for downtime 1"):
        shift_reports.save(supervisor, report, {"downtime": [dict(stops[0], reason="FLASH")]})
    shift_reports.save(supervisor, report, {"runs": [run(released)]})
    # The database refuses an overlapping run on the same machine too.
    first = MouldingRun.objects.get()
    with pytest.raises(DatabaseError, match="never overlap"), transaction.atomic():
        MouldingRun.objects.create(
            report=report,
            machine=first.machine,
            order=first.order,
            mould=first.mould,
            started_at=at(9),
            ended_at=at(9, 30),
            start_counter=1500,
            end_counter=1600,
            cavities=8,
            good_quantity=D("800"),
        )


def test_entry_only_during_the_shift_and_the_grace_period(clock, supervisor, press, released):
    clock["now"] = at(7, 59)
    with pytest.raises(ShiftReportError, match="open for entry from"):
        shift_reports.open_report(supervisor, {"section": "IM-MLD", "shift": "G", "day": TODAY})
    clock["now"] = at(20, 59)  # 17:00 + 4 hours' grace
    report = shift_reports.open_report(
        supervisor, {"section": "IM-MLD", "shift": "G", "day": TODAY.isoformat()}
    )
    shift_reports.save(supervisor, report, {"runs": [run(released)]})
    clock["now"] = at(21, 1)
    with pytest.raises(ShiftReportError, match="grace period are over"):
        shift_reports.save(supervisor, report, {"runs": []})
    with pytest.raises(ShiftReportError, match="grace period are over"):
        shift_reports.submit(supervisor, report)
    assert shift_reports.open_shifts(supervisor) == []


def test_only_the_sections_own_supervisor(clock, press, released, supervisor):
    other = person("other@sml.lk", "production_supervisor", divisions=["IM"])
    other.all_sections = False
    other.save()
    with pytest.raises(ShiftReportError, match="Choose one of your sections"):
        shift_reports.open_report(other, {"section": "IM-MLD", "shift": "G", "day": TODAY})
    report = shift_reports.open_report(
        supervisor, {"section": "IM-MLD", "shift": "G", "day": TODAY}
    )
    assert as_user(other).get(f"{URL}{report.pk}/").status_code == 404
    pm = person("pm2@sml.lk", "production_manager", divisions=["IM"])
    seen = as_user(pm).get(f"{URL}{report.pk}/")
    assert seen.status_code == 200 and seen.json()["editable"] is False
    with pytest.raises(ShiftReportError, match="Only a supervisor"):
        shift_reports.save(pm, report, {})
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).get(URL).status_code == 403
    with pytest.raises(ShiftReportError, match="at least one run, job card or downtime"):
        shift_reports.submit(supervisor, report)


def test_a_supervisor_gets_only_their_sections_even_with_all_sections_ticked(
    clock, press, released, supervisor
):
    """Owner's testing (R2, 12 Nov 2026): the Workshop supervisor, with "All sections" ticked
    (as every person is by default), could start the moulding section's report."""
    workshop = person("ws@sml.lk", "production_supervisor", all_divisions=True)
    assert workshop.all_sections is True
    Section.objects.get(code="C-LAT").supervisors.add(workshop)
    assert {s["section"] for s in shift_reports.open_shifts(workshop)} == {"C-LAT"}
    with pytest.raises(ShiftReportError, match="Choose one of your sections"):
        shift_reports.open_report(workshop, {"section": "IM-MLD", "shift": "G", "day": TODAY})
    moulding = shift_reports.open_report(
        supervisor, {"section": "IM-MLD", "shift": "G", "day": TODAY}
    )
    assert as_user(workshop).get(f"{URL}{moulding.pk}/").status_code == 404
    assert moulding.pk not in {r["id"] for r in as_user(workshop).get(URL).json()["recent"]}
    # The moulding presses are not on their plan either.
    plan_board = as_user(workshop).get(f"/api/v1/production-plan/?start={TODAY}&days=1").json()
    assert plan_board["machines"] == []
    # Nor in their production reports.
    sections = as_user(workshop).get("/api/v1/production-reports/sections/").json()["sections"]
    assert {s["code"] for s in sections} == {"C-LAT"}
    # Someone who plans or approves still sees every section of their divisions.
    pm = person("pm3@sml.lk", "production_manager", all_divisions=True)
    assert as_user(pm).get(f"{URL}{moulding.pk}/").status_code == 200


def test_material_and_manpower_are_checked(report, supervisor, released):
    for materials, message in [
        ([{"kind": "gift", "lot_no": "L1", "quantity": "1"}], "issued, returned or regrind"),
        ([{"kind": "issue", "item": "PP-H", "quantity": "1"}], "Give the batch"),
        ([{"kind": "issue", "lot_no": "NOPE", "quantity": "1"}], "no material batch"),
        ([{"kind": "regrind", "item": "CAP-28", "quantity": "1"}], "Regrind is of a raw"),
        ([{"kind": "regrind", "item": "PP-H", "quantity": "0"}], "more than 0"),
        ([{"kind": "regrind", "item": "PP-H", "quantity": "1.2345"}], "3 decimal places"),
    ]:
        with pytest.raises(ShiftReportError, match=message):
            shift_reports.save(supervisor, report, {"materials": materials})
    with pytest.raises(ShiftReportError, match="people on manpower line 1 is more than 0"):
        shift_reports.save(supervisor, report, {"manpower": [{"people": "0"}]})


def test_a_night_shift_runs_past_midnight(clock, supervisor, press, released):
    from apps.masters import rosters

    rosters.create_shift(
        code="N", name="Night", start_time=time(20), end_time=time(8), break_minutes=60
    )
    clock["now"] = at(2, day=TODAY + timedelta(days=1))
    report = shift_reports.open_report(
        supervisor, {"section": "IM-MLD", "shift": "N", "day": TODAY.isoformat()}
    )
    shift_reports.save(
        supervisor,
        report,
        {"runs": [run(released, start_time="23:00", end_time="01:00", rejects=[])]},
    )
    saved = MouldingRun.objects.get()
    assert saved.started_at == at(23) and saved.ended_at == at(1, day=TODAY + timedelta(days=1))
    assert saved.good_quantity == D("4000") and saved.actual_cycle_s == D("14.40")


def test_a_save_made_offline_on_an_older_copy_is_refused_not_overwritten(
    clock, report, supervisor, released
):
    """P3-21: the phone sends the version its copy came from; if the report was saved since,
    the save is refused with the current report, and the supervisor chooses."""
    client = as_user(supervisor)
    first = client.get(f"{URL}{report.pk}/").json()["version"]
    clock["now"] = at(10, 5)
    saved = client.put(
        f"{URL}{report.pk}/",
        {"notes": "From the office PC", "base_version": first},
        format="json",
    )
    assert saved.status_code == 200 and saved.json()["version"] != first
    clock["now"] = at(10, 10)
    late = client.put(
        f"{URL}{report.pk}/", {"notes": "Typed offline", "base_version": first}, format="json"
    )
    assert late.status_code == 409
    assert late.json()["current"]["notes"] == "From the office PC"
    report.refresh_from_db()
    assert report.notes == "From the office PC"  # nothing overwritten
    # The supervisor chooses to keep the phone's version: sent without a base version.
    kept = client.put(f"{URL}{report.pk}/", {"notes": "Typed offline"}, format="json")
    assert kept.status_code == 200 and kept.json()["notes"] == "Typed offline"
