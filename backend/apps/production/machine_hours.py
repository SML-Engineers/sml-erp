"""Machine hours report (backlog P3-24 e; owner, 15 Nov 2026), from the jobs started and
finished at the machine (P3-24 a):

- **Per machine and period** (day, week from Monday, or month): hours run, downtime reported
  in the shift reports, and utilisation = hours run ÷ the clock hours of the period (24 a
  day; the part of today so far), the same measure as the Dashboard.
- **Per job and order:** actual hours against the estimate, where there is one: a workshop
  operation's setup + run minutes per piece × pieces (completed + rejected), a moulding
  run's shots × the mould's standard cycle time. Over estimate is flagged.
- **Cost** (only for people who may see costs, as on order profitability): hours × the
  machine-hour rate in force on the job's start day; the estimate at the same rate; the
  machines costing more than estimated. Each job and order links to its page, where order
  profitability shows its profit or loss with all costs (P3-17).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

from apps.core.models import User

from . import costs, machine_jobs, rates
from .models import DowntimeEntry, MachineJob

ZERO = Decimal("0")
HOURS = Decimal("0.01")
GROUPS = ("day", "week", "month")


class MachineHoursError(Exception):
    pass


def _h(minutes: Decimal | int) -> str:
    return str((Decimal(minutes) / 60).quantize(HOURS, ROUND_HALF_UP))


def _money(value: Decimal) -> str:
    return str(value.quantize(HOURS, ROUND_HALF_UP))


def _period(day: date, by: str) -> date:
    if by == "week":
        return day - timedelta(days=day.weekday())
    if by == "month":
        return day.replace(day=1)
    return day


def _span(a: datetime, b: datetime, start: datetime, end: datetime) -> list[tuple[date, int]]:
    """Whole minutes of [a, b) inside [start, end), by Sri Lanka day."""
    a, b = max(a, start), min(b, end)
    out = []
    while a < b:
        local = timezone.localtime(a)
        midnight = timezone.make_aware(datetime.combine(local.date() + timedelta(days=1), time()))
        upto = min(b, midnight)
        out.append((local.date(), int((upto - a).total_seconds() // 60)))
        a = upto
    return out


def _estimate_minutes(job: MachineJob) -> Decimal | None:
    if job.ended_at is None:
        return None
    if job.kind == MachineJob.Kind.JOB:
        pieces = (job.completed or ZERO) + (job.rejected or ZERO)
        op = job.operation
        if not (op.run_min or op.setup_min):
            return None
        return (op.setup_min or ZERO) + (op.run_min or ZERO) * pieces
    if job.end_counter is None or not job.mould.cycle_time_s:
        return None
    return Decimal(job.end_counter - job.start_counter) * job.mould.cycle_time_s / 60


def report(user: User, start_day: date, end_day: date, by: str = "day") -> dict:
    if by not in GROUPS:
        raise MachineHoursError("Group by day, week or month.")
    if end_day < start_day:
        raise MachineHoursError("The end date is before the start date.")
    if (end_day - start_day).days > 400:
        raise MachineHoursError("Choose at most about a year.")
    now = timezone.now()
    start = timezone.make_aware(datetime.combine(start_day, time()))
    end = min(timezone.make_aware(datetime.combine(end_day + timedelta(days=1), time())), now)
    show_cost = costs.can_see(user)

    found = list(
        machine_jobs.visible(user)
        .filter(started_at__lt=end)
        .filter(Q(ended_at__gt=start) | Q(ended_at__isnull=True))
        .select_related("operation", "mould", "machine__section")
        .order_by("started_at")
    )
    machines = {m.pk: m for m in machine_jobs.machines(user)}

    # Per machine and period: minutes run.
    run: dict[tuple[int, date], int] = defaultdict(int)
    for j in found:
        for day, minutes in _span(j.started_at, j.ended_at or now, start, end):
            run[(j.machine_id, _period(day, by))] += minutes
    # Downtime reported in the shift reports, by the day it started.
    stopped: dict[tuple[int, date], int] = defaultdict(int)
    for d in DowntimeEntry.objects.filter(
        machine__in=machines.values(), started_at__lt=end, ended_at__gt=start
    ):
        for day, minutes in _span(d.started_at, d.ended_at, start, end):
            stopped[(d.machine_id, _period(day, by))] += minutes
    # Clock minutes of each period inside the range (today: so far).
    clock: dict[date, int] = defaultdict(int)
    for day, minutes in _span(start, end, start, end):
        clock[_period(day, by)] += minutes

    rate_cache: dict[tuple[int, date], Decimal] = {}

    def rate(job: MachineJob) -> Decimal:
        key = (job.machine_id, timezone.localtime(job.started_at).date())
        if key not in rate_cache:
            rate_cache[key] = rates.overhead_on(job.machine.section, job.machine, key[1])
        return rate_cache[key]

    # Per job / order.
    jobs = []
    machine_cost: dict[int, dict[str, Decimal]] = defaultdict(
        lambda: {"actual": ZERO, "estimate": ZERO}
    )
    for j in found:
        minutes = Decimal(machine_jobs.minutes(j, now))
        estimate = _estimate_minutes(j)
        row = {
            "id": j.pk,
            "machine": j.machine.code,
            "kind": j.kind,
            "job": j.job.number if j.job_id else None,
            "job_id": j.job_id,
            "operation": j.operation.seq if j.operation_id else None,
            "operation_name": j.operation.name if j.operation_id else None,
            "order": j.order.number if j.order_id else None,
            "order_id": j.order_id,
            "started_at": timezone.localtime(j.started_at).isoformat(),
            "ended_at": timezone.localtime(j.ended_at).isoformat() if j.ended_at else None,
            "hours": _h(minutes),
            "estimate_hours": None if estimate is None else _h(estimate),
            "over": estimate is not None and minutes > estimate,
            "over_pct": None
            if not estimate
            else str(
                ((minutes - estimate) * 100 / estimate).quantize(Decimal("0.1"), ROUND_HALF_UP)
            ),
        }
        if show_cost:
            r = rate(j)
            actual = minutes / 60 * r
            row["rate"] = _money(r)
            row["cost"] = _money(actual)
            row["estimate_cost"] = None if estimate is None else _money(estimate / 60 * r)
            if estimate is not None:
                machine_cost[j.machine_id]["actual"] += actual
                machine_cost[j.machine_id]["estimate"] += estimate / 60 * r
        jobs.append(row)

    periods = sorted(clock)
    rows = []
    for m in machines.values():
        cells = []
        for p in periods:
            minutes = run.get((m.pk, p), 0)
            cells.append(
                {
                    "period": p.isoformat(),
                    "hours": _h(minutes),
                    "downtime_hours": _h(stopped.get((m.pk, p), 0)),
                    "utilisation": str(
                        (Decimal(minutes) * 100 / Decimal(max(1, clock[p]))).quantize(
                            Decimal("0.1"), ROUND_HALF_UP
                        )
                    ),
                }
            )
        total = sum(run.get((m.pk, p), 0) for p in periods)
        line = {
            "machine": m.code,
            "name": m.name,
            "section": m.section.code,
            "periods": cells,
            "hours": _h(total),
            "downtime_hours": _h(sum(stopped.get((m.pk, p), 0) for p in periods)),
            "utilisation": str(
                (Decimal(total) * 100 / Decimal(max(1, sum(clock.values())))).quantize(
                    Decimal("0.1"), ROUND_HALF_UP
                )
            ),
        }
        if show_cost:
            c = machine_cost.get(m.pk, {"actual": ZERO, "estimate": ZERO})
            line["cost_vs_estimate"] = {
                "actual": _money(c["actual"]),
                "estimate": _money(c["estimate"]),
                "over": c["actual"] > c["estimate"],
            }
        rows.append(line)
    return {
        "start": start_day.isoformat(),
        "end": end_day.isoformat(),
        "by": by,
        "periods": [p.isoformat() for p in periods],
        "machines": rows,
        "jobs": jobs,
        "show_cost": show_cost,
    }
