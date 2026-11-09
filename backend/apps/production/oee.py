"""OEE of the moulding machines (spec 7.4, 3A.2; backlog P3-19).

For each moulding machine and shift, from approved shift reports and the roster:

- **Planned time**: the shift's working minutes (length less break) on every shift the
  roster runs for the section that day (a section's own roster replaces the division's),
  and on any other shift that was worked (a shift report exists). Off days are not counted.
  **Planned stops** (downtime with a planned reason) are taken off the planned time.
- **Availability** = run time ÷ (planned time − planned stops). Run time is the moulding runs'
  time less any downtime inside them. A rostered shift with no run on the machine is all
  lost.
- **Performance** = the mould's standard cycle × shots ÷ run time.
- **Quality** = good pieces ÷ pieces moulded (shots × cavities).
- **OEE** = availability × performance × quality.

Days, months and the whole range add the minutes and pieces first, then work out the ratios.
A night shift belongs to the day it starts. Figures over 100% (a mould running faster than
its standard) are shown as they are, so a wrong standard is visible."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from apps.core.access import division_scope
from apps.core.models import User
from apps.masters import rosters
from apps.masters.models import Machine, Section

from .models import DowntimeEntry, MouldingRun, ShiftReport

ZERO = Decimal("0")
SIXTY = Decimal("60")
MAX_DAYS = 366


class OeeError(Exception):
    pass


def _minutes(start: datetime, end: datetime) -> Decimal:
    return Decimal(str((end - start).total_seconds())) / SIXTY


def _overlap(start, end, stops) -> Decimal:
    total = ZERO
    for s, e in stops:
        a, b = max(s, start), min(e, end)
        if b > a:
            total += _minutes(a, b)
    return total


def _rostered(section: Section, start: date, end: date) -> dict[date, set]:
    """The shifts the roster runs for the section each day."""
    out: dict[date, set] = defaultdict(set)
    day = start
    while day <= end:
        days = min((end - day).days + 1, rosters.MAX_PREVIEW_DAYS)
        for d, entries in rosters.schedule(section.division, day, days, section):
            own = [e for e in entries if e.assignment.section_id == section.pk]
            for e in own or entries:
                out[d].add(e.shift)
        day += timedelta(days=days)
    return out


def _empty() -> dict:
    return {
        "planned": ZERO,
        "planned_stops": ZERO,
        "run": ZERO,
        "ideal": ZERO,
        "good": ZERO,
        "made": 0,
        "unplanned_stops": ZERO,
    }


def _add(into: dict, cell: dict) -> None:
    for key, value in cell.items():
        into[key] += value


def _pct(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str((value * 100).quantize(Decimal("0.1"), ROUND_HALF_UP))


def ratios(c: dict) -> dict:
    available = c["planned"] - c["planned_stops"]
    a = c["run"] / available if available > 0 else None
    p = c["ideal"] / c["run"] if c["run"] > 0 else None
    q = c["good"] / c["made"] if c["made"] else None
    oee = a * p * q if None not in (a, p, q) else (ZERO if a == 0 else None)
    return {
        "planned_h": str((c["planned"] / SIXTY).quantize(Decimal("0.01"), ROUND_HALF_UP)),
        "planned_stops_h": str(
            (c["planned_stops"] / SIXTY).quantize(Decimal("0.01"), ROUND_HALF_UP)
        ),
        "run_h": str((c["run"] / SIXTY).quantize(Decimal("0.01"), ROUND_HALF_UP)),
        "unplanned_stops_h": str(
            (c["unplanned_stops"] / SIXTY).quantize(Decimal("0.01"), ROUND_HALF_UP)
        ),
        "good": f"{c['good'].normalize():f}" if c["good"] else "0",
        "made": c["made"],
        "availability": _pct(a),
        "performance": _pct(p),
        "quality": _pct(q),
        "oee": _pct(oee),
    }


def _cells(section: Section, machines: list[Machine], start: date, end: date):
    """{(machine pk, day, shift): cell} for every planned or worked shift."""
    reports = {
        (r.day, r.shift_id): r
        for r in ShiftReport.objects.filter(
            section=section,
            status=ShiftReport.Status.APPROVED,
            day__gte=start,
            day__lte=end,
        ).select_related("shift")
    }
    slots = {(d, s.pk): s for d, shifts in _rostered(section, start, end).items() for s in shifts}
    for (d, shift_id), r in reports.items():
        slots[(d, shift_id)] = r.shift
    ids = [m.pk for m in machines]
    runs = defaultdict(list)
    for run in MouldingRun.objects.filter(
        report__in=reports.values(), machine_id__in=ids
    ).select_related("mould"):
        runs[(run.report_id, run.machine_id)].append(run)
    stops = defaultdict(list)
    for d in DowntimeEntry.objects.filter(
        report__in=reports.values(), machine_id__in=ids
    ).select_related("reason"):
        stops[(d.report_id, d.machine_id)].append(d)
    out = {}
    for (day, shift_id), shift in slots.items():
        report = reports.get((day, shift_id))
        for m in machines:
            cell = _empty()
            cell["planned"] = Decimal(shift.working_minutes)
            if report is not None:
                downs = stops[(report.pk, m.pk)]
                cell["planned_stops"] = sum(
                    (_minutes(x.started_at, x.ended_at) for x in downs if x.reason.planned), ZERO
                )
                spans = [(x.started_at, x.ended_at) for x in downs]
                for run in runs[(report.pk, m.pk)]:
                    inside = _overlap(run.started_at, run.ended_at, spans)
                    cell["run"] += max(_minutes(run.started_at, run.ended_at) - inside, ZERO)
                    cell["ideal"] += run.mould.cycle_time_s * run.shots / SIXTY
                    cell["good"] += run.good_quantity
                    cell["made"] += run.shots * run.cavities
                cell["unplanned_stops"] = sum(
                    (_minutes(x.started_at, x.ended_at) for x in downs if not x.reason.planned),
                    ZERO,
                )
            out[(m.pk, day, shift)] = cell
    return out


def report(user: User, start: date, end: date, section_code: str = "") -> dict:
    """OEE per moulding machine for the range: the totals to compare machines, and each
    machine's months, days and shifts."""
    if end < start:
        raise OeeError("The end date is before the start.")
    if (end - start).days + 1 > MAX_DAYS:
        raise OeeError(f"Show at most {MAX_DAYS} days.")
    sections = Section.objects.filter(
        section_type=Section.Type.MOULDING, is_active=True, division__in=division_scope(user)
    ).order_by("code")
    if section_code:
        sections = sections.filter(code=section_code)
    machines_out = []
    overall = _empty()
    for section in sections:
        machines = list(
            Machine.objects.filter(section=section)
            .exclude(status=Machine.Status.RETIRED)
            .order_by("code")
        )
        if not machines:
            continue
        cells = _cells(section, machines, start, end)
        for m in machines:
            total = _empty()
            days = defaultdict(_empty)
            months = defaultdict(_empty)
            shifts = []
            for (pk, day, shift), cell in sorted(
                cells.items(), key=lambda x: (x[0][1], x[0][2].start_time)
            ):
                if pk != m.pk:
                    continue
                _add(total, cell)
                _add(days[day], cell)
                _add(months[day.strftime("%Y-%m")], cell)
                shifts.append({"day": day, "shift": shift.code, **ratios(cell)})
            _add(overall, total)
            machines_out.append(
                {
                    "machine": m.code,
                    "name": m.name,
                    "section": section.code,
                    **ratios(total),
                    "months": [{"month": k, **ratios(v)} for k, v in sorted(months.items())],
                    "days": [{"day": k, **ratios(v)} for k, v in sorted(days.items())],
                    "shifts": shifts,
                }
            )
    return {
        "start": start,
        "end": end,
        "sections": list(
            Section.objects.filter(
                section_type=Section.Type.MOULDING,
                is_active=True,
                division__in=division_scope(user),
            )
            .order_by("code")
            .values_list("code", flat=True)
        ),
        "total": ratios(overall),
        "machines": machines_out,
    }
