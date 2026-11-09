"""Production reports (spec 7.6; backlog P3-20 part 1), from approved shift reports in the
user's sections:

- **Daily production** by day, section, machine and shift: good and rejected pieces, reject
  %, run hours and stopped hours (moulding runs and machining job cards).
- **Rejects** by reason, part, mould or machine: pieces rejected, pieces made, reject % and
  share of all rejects.
- **Downtime** by reason and by machine, largest first with the cumulative % (Pareto),
  planned stops marked.
- **Jobs**: each machining job's estimated time (routing setup + run minutes × quantity, own
  operations) against the hours on its job cards, estimated against actual cost, and whether
  it was completed by its due date (on-time delivery).
- **Material**: the material supervisors issued less returned against the standard the
  approved shift reports backflushed, per item; regrind made and regrind issued.
- **Moulds** approaching or due for maintenance.

OEE has its own page (P3-19); profitability reports and production as a report builder source
are part 2."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from apps.core.models import User
from apps.masters.models import Section
from apps.masters.services import section_scope

from . import maintenance, profit
from .models import (
    DowntimeEntry,
    JobCardEntry,
    JobCardReject,
    JobOrder,
    MaterialEntry,
    Mould,
    MouldingRun,
    RejectEntry,
    ShiftReport,
)

ZERO = Decimal("0")
HUNDRED = Decimal("100")
SIXTY = Decimal("60")
MAX_DAYS = 366
APPROVED = ShiftReport.Status.APPROVED


class ReportError(Exception):
    pass


def _hours(start: datetime, end: datetime) -> Decimal:
    return Decimal(str((end - start).total_seconds())) / 3600


def _n(value: Decimal | int | None, places: str = "0.01") -> str | None:
    if value is None:
        return None
    return str(Decimal(value).quantize(Decimal(places), ROUND_HALF_UP))


def _q(value: Decimal) -> str:
    return f"{Decimal(value).normalize():f}" if value else "0"


def _pct(part, whole) -> str | None:
    return _n(Decimal(part) / Decimal(whole) * HUNDRED, "0.1") if whole else None


def _sections(user: User, code: str = ""):
    found = section_scope(user).filter(
        section_type__in=(Section.Type.MOULDING, Section.Type.MACHINING), is_active=True
    )
    return found.filter(code=code) if code else found


def _reports(user: User, start: date, end: date, section: str = ""):
    if end < start:
        raise ReportError("The end date is before the start.")
    if (end - start).days + 1 > MAX_DAYS:
        raise ReportError(f"Show at most {MAX_DAYS} days.")
    return ShiftReport.objects.filter(
        status=APPROVED, day__gte=start, day__lte=end, section__in=_sections(user, section)
    )


def sections(user: User) -> list[dict]:
    return [
        {"code": s.code, "name": s.name, "type": s.section_type}
        for s in _sections(user).order_by("code")
    ]


# --- Daily production ------------------------------------------------------------------------


def daily(user: User, start: date, end: date, section: str = "") -> dict:
    reports = _reports(user, start, end, section)
    rows: dict[tuple, dict] = {}

    def row(report, machine):
        key = (report.day, report.section.code, machine.code, report.shift.code)
        return rows.setdefault(
            key,
            {"good": ZERO, "rejected": ZERO, "run": ZERO, "stopped": ZERO},
        )

    runs = MouldingRun.objects.filter(report__in=reports).select_related(
        "report__section", "report__shift", "machine"
    )
    rejected = defaultdict(int)
    for run_id, q in RejectEntry.objects.filter(run__in=runs).values_list("run_id", "quantity"):
        rejected[run_id] += q
    for run in runs:
        r = row(run.report, run.machine)
        r["good"] += run.good_quantity
        r["rejected"] += rejected[run.pk]
        r["run"] += _hours(run.started_at, run.ended_at)
    for e in JobCardEntry.objects.filter(report__in=reports).select_related(
        "report__section", "report__shift", "machine"
    ):
        r = row(e.report, e.machine)
        r["good"] += e.completed
        r["rejected"] += e.rejected
        r["run"] += _hours(e.started_at, e.ended_at)
    for d in DowntimeEntry.objects.filter(report__in=reports).select_related(
        "report__section", "report__shift", "machine"
    ):
        row(d.report, d.machine)["stopped"] += _hours(d.started_at, d.ended_at)
    out = []
    total = {"good": ZERO, "rejected": ZERO, "run": ZERO, "stopped": ZERO}
    for (day, sec, machine, shift), r in sorted(rows.items()):
        for k in total:
            total[k] += r[k]
        out.append(
            {
                "day": day,
                "section": sec,
                "machine": machine,
                "shift": shift,
                "good": _q(r["good"]),
                "rejected": _q(r["rejected"]),
                "reject_pct": _pct(r["rejected"], r["good"] + r["rejected"]),
                "run_h": _n(r["run"]),
                "stopped_h": _n(r["stopped"]),
            }
        )
    return {
        "rows": out,
        "total": {
            "good": _q(total["good"]),
            "rejected": _q(total["rejected"]),
            "reject_pct": _pct(total["rejected"], total["good"] + total["rejected"]),
            "run_h": _n(total["run"]),
            "stopped_h": _n(total["stopped"]),
        },
    }


# --- Rejects ---------------------------------------------------------------------------------

BY = ("reason", "part", "mould", "machine")


def rejects(user: User, start: date, end: date, by: str = "reason", section: str = "") -> dict:
    if by not in BY:
        raise ReportError("Group the rejects by reason, part, mould or machine.")
    reports = _reports(user, start, end, section)
    made: dict[str, Decimal] = defaultdict(lambda: ZERO)
    lost: dict[str, Decimal] = defaultdict(lambda: ZERO)
    names: dict[str, str] = {}
    runs = list(
        MouldingRun.objects.filter(report__in=reports).select_related(
            "machine", "mould", "order__item"
        )
    )
    run_rejects = defaultdict(list)
    for x in RejectEntry.objects.filter(run__in=runs).select_related("reason"):
        run_rejects[x.run_id].append(x)
    for run in runs:
        key = {
            "part": run.order.item.code,
            "mould": run.mould.code,
            "machine": run.machine.code,
        }.get(by)
        if key is not None:
            names[key] = {"part": run.order.item.name, "mould": run.mould.name}.get(by, "")
            made[key] += run.good_quantity + sum(x.quantity for x in run_rejects[run.pk])
        for x in run_rejects[run.pk]:
            k = x.reason.code if by == "reason" else key
            if by == "reason":
                names[k] = x.reason.name
            lost[k] += x.quantity
    entries = list(
        JobCardEntry.objects.filter(report__in=reports).select_related("machine", "job__item")
    )
    entry_rejects = defaultdict(list)
    for x in JobCardReject.objects.filter(entry__in=entries).select_related("reason"):
        entry_rejects[x.entry_id].append(x)
    for e in entries:
        part = e.job.item.code if e.job.item_id else e.job.number
        key = {"part": part, "machine": e.machine.code}.get(by)
        if by == "mould":
            continue
        if key is not None:
            names[key] = (
                (e.job.item.name if e.job.item_id else e.job.description) if (by == "part") else ""
            )
            made[key] += e.completed + e.rejected
        for x in entry_rejects[e.pk]:
            k = x.reason.code if by == "reason" else key
            if by == "reason":
                names[k] = x.reason.name
            lost[k] += x.quantity
    all_lost = sum(lost.values(), ZERO)
    keys = set(lost) | (set(made) if by != "reason" else set())
    out = [
        {
            "key": k,
            "name": names.get(k, ""),
            "rejected": _q(lost[k]),
            "made": _q(made[k]) if by != "reason" else None,
            "reject_pct": _pct(lost[k], made[k]) if by != "reason" else None,
            "share_pct": _pct(lost[k], all_lost),
        }
        for k in keys
    ]
    out.sort(key=lambda r: (-Decimal(r["rejected"]), r["key"]))
    return {"by": by, "rows": out, "total_rejected": _q(all_lost)}


# --- Downtime (Pareto) ------------------------------------------------------------------------


def _pareto(hours: dict[str, Decimal], extra: dict[str, dict]) -> list[dict]:
    total = sum(hours.values(), ZERO)
    out, running = [], ZERO
    for key, h in sorted(hours.items(), key=lambda x: (-x[1], x[0])):
        running += h
        out.append(
            {
                "key": key,
                **extra.get(key, {}),
                "hours": _n(h),
                "share_pct": _pct(h, total),
                "cumulative_pct": _pct(running, total),
            }
        )
    return out


def downtime(user: User, start: date, end: date, section: str = "") -> dict:
    reports = _reports(user, start, end, section)
    by_reason: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_machine: dict[str, Decimal] = defaultdict(lambda: ZERO)
    reason_info: dict[str, dict] = {}
    count = defaultdict(int)
    for d in DowntimeEntry.objects.filter(report__in=reports).select_related("reason", "machine"):
        h = _hours(d.started_at, d.ended_at)
        by_reason[d.reason.code] += h
        count[d.reason.code] += 1
        reason_info[d.reason.code] = {"name": d.reason.name, "planned": d.reason.planned}
        by_machine[d.machine.code] += h
    for code, info in reason_info.items():
        info["stops"] = count[code]
    return {
        "reasons": _pareto(by_reason, reason_info),
        "machines": _pareto(by_machine, {}),
        "total_h": _n(sum(by_reason.values(), ZERO)),
    }


# --- Machining jobs: time, cost and on-time delivery --------------------------------------------


def jobs(user: User, start: date, end: date) -> dict:
    """Jobs due in the range, or completed in it."""
    scope = section_scope(user).values_list("division_id", flat=True)
    found = (
        JobOrder.objects.filter(division_id__in=scope)
        .exclude(status__in=[JobOrder.Status.DRAFT, JobOrder.Status.CANCELLED])
        .filter(due_date__gte=start, due_date__lte=end)
        .select_related("item")
        .order_by("due_date", "number")
    )
    today = timezone.localdate()
    out = []
    on_time = finished = late_open = 0
    see_money = profit.can_see(user)
    for job in found:
        ops = list(job.operations.filter(subcontract=False))
        estimate = sum((o.setup_min + o.run_min * job.quantity for o in ops), ZERO) / SIXTY
        actual = sum(
            (_hours(e.started_at, e.ended_at) for e in job.entries.filter(report__status=APPROVED)),
            ZERO,
        )
        done = job.completed_at.date() if job.completed_at else None
        if done is not None:
            finished += 1
            on_time += done <= job.due_date
        elif job.due_date < today:
            late_open += 1
        f = profit.figures(job) if see_money else None
        out.append(
            {
                "id": job.pk,
                "number": job.number,
                "part": job.item.code if job.item_id else "",
                "description": job.description,
                "status": job.get_status_display(),
                "quantity": _q(job.quantity),
                "due_date": job.due_date,
                "completed_on": done,
                "on_time": None if done is None else done <= job.due_date,
                "days_late": max(((done or today) - job.due_date).days, 0),
                "estimated_h": _n(estimate),
                "actual_h": _n(actual),
                "time_variance_pct": _pct(actual - estimate, estimate) if estimate else None,
                "estimated_cost": str(f["estimate_cost"])
                if f and f["estimate_cost"] is not None
                else None,
                "actual_cost": str(f["cost"]) if f else None,
            }
        )
    return {
        "rows": out,
        "completed": finished,
        "on_time": on_time,
        "on_time_pct": _pct(on_time, finished),
        "late_open": late_open,
    }


# --- Material against standard; regrind -------------------------------------------------------


def material(user: User, start: date, end: date, section: str = "") -> dict:
    from .shift_approval import _needs

    reports = list(
        _reports(user, start, end, section).filter(section__section_type=Section.Type.MOULDING)
    )
    issued: dict[int, Decimal] = defaultdict(lambda: ZERO)
    regrind_made: dict[int, Decimal] = defaultdict(lambda: ZERO)
    items = {}
    for m in MaterialEntry.objects.filter(report__in=reports).select_related("item"):
        items[m.item_id] = m.item
        if m.kind == MaterialEntry.Kind.ISSUE:
            issued[m.item_id] += m.quantity
        elif m.kind == MaterialEntry.Kind.RETURN:
            issued[m.item_id] -= m.quantity
        else:
            regrind_made[m.item_id] += m.quantity
    standard: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for report in reports:
        for rows in _needs(report).values():
            for item, _, quantity, _ in rows:
                items[item.pk] = item
                standard[item.pk] += quantity
    out = []
    for pk in sorted(set(issued) | set(standard), key=lambda p: items[p].code):
        diff = issued[pk] - standard[pk]
        out.append(
            {
                "item": items[pk].code,
                "name": items[pk].name,
                "unit": items[pk].unit,
                "issued": _q(issued[pk]),
                "standard": _n(standard[pk], "0.001"),
                "difference": _n(diff, "0.001"),
                "difference_pct": _pct(diff, standard[pk]) if standard[pk] else None,
            }
        )
    regrind = [
        {
            "item": items[pk].code,
            "name": items[pk].name,
            "unit": items[pk].unit,
            "made": _q(regrind_made[pk]),
            "issued": _q(max(issued.get(pk, ZERO), ZERO)),
        }
        for pk in sorted(regrind_made, key=lambda p: items[p].code)
    ]
    return {"rows": out, "regrind": regrind}


# --- Moulds approaching maintenance -----------------------------------------------------------


def moulds_due(user: User) -> list[dict]:
    divisions = set(section_scope(user).values_list("division_id", flat=True))
    out = []
    for m in (
        Mould.objects.filter(division_id__in=divisions, pm_interval_shots__isnull=False)
        .exclude(status=Mould.Status.RETIRED)
        .order_by("code")
    ):
        state = maintenance.state(m)
        if state not in ("due", "approaching"):
            continue
        used = maintenance.since(m)
        out.append(
            {
                "mould": m.code,
                "name": m.name,
                "state": state,
                "shots_since": used,
                "interval": m.pm_interval_shots,
                "used_pct": _pct(used, m.pm_interval_shots),
            }
        )
    out.sort(key=lambda r: (r["state"] != "due", -Decimal(r["used_pct"] or 0)))
    return out
