"""Moulding shift reports, entered by the supervisor (backlog P3-08; spec 7.4, 7.5). A
machining section's report has job card operations instead of runs (P3-12, `job_cards`).

- One report per **moulding section, day and shift** (a night shift belongs to the day it
  starts), opened and kept by a supervisor of the section (shop floor, Enter; their own
  sections only).
- **Runs** per machine: the released production order (usually from the plan) and its
  mould, the material batch (a lot in the division's stock, scanned from its label), the
  operator, start and end time, the shot counter at start and end, and rejects by reason.
  **Good quantity** = shots × the part's cavities − rejects; **actual cycle time** = the
  run's time less the machine's downtime in it, over the shots.
- **Downtime** per machine with a downtime reason; **material** issued from stores, returned
  and regrind made (by lot); **manpower**: people per machine or for the section, overtime.
- **Checks:** the shot counter on a machine never goes down (from one run to the next, in
  any report), rejects never exceed shots × cavities, times on one machine never overlap
  (database too), times fall within the shift, and entry is allowed only from the shift's
  start until the grace period after its end (production settings, 4 hours). A report sent
  back by the Production Manager (P3-09) can be corrected.
- **Submit** locks the report (database). Nothing touches stock, moulds or costs until the
  Production Manager approves it (P3-09).

The whole report is saved at once (runs, downtime, material, manpower, notes), so a phone
can keep a draft and send it when it is back on Wi-Fi (P3-21).
"""

from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.inventory.models import Item, StockMovement
from apps.masters.models import Machine, Section, Shift
from apps.masters.services import section_scope
from apps.payroll.models import Employee

from . import job_cards, plan
from .job_cards import JobCardError
from .models import (
    DowntimeEntry,
    JobCardEntry,
    JobCardReject,
    JobOrder,
    ManpowerEntry,
    MaterialEntry,
    MouldingRun,
    PlanEntry,
    ProductionOrder,
    ReasonCode,
    RejectEntry,
    ShiftReport,
)
from .reasons import setting_on

St = ShiftReport.Status
EDITABLE = (St.DRAFT, St.RETURNED)
ZERO = Decimal("0")
MAX_ROWS = 200


class ShiftReportError(Exception):
    pass


class ShiftReportConflict(ShiftReportError):
    """P3-21: the report was saved elsewhere after the copy this save was made on."""


def version_of(report: ShiftReport) -> str:
    return report.updated_at.isoformat()


def can_enter(user: User) -> bool:
    return effective_access(user).has("shop_floor", "enter")


REPORTED = (Section.Type.MOULDING, Section.Type.MACHINING)


def sections(user: User):
    """The moulding and machining (P3-12) sections the user supervises (or may work in)."""
    return section_scope(user).filter(section_type__in=REPORTED, is_active=True)


def visible(user: User):
    found = ShiftReport.objects.select_related("section", "shift", "created_by", "submitted_by")
    if plan.own_sections_only(user):
        return found.filter(section__in=section_scope(user))
    return found.filter(section__division__in=division_scope(user))


# --- The shift's time window ---------------------------------------------------------------------


def window(day, shift: Shift) -> tuple[datetime, datetime, datetime]:
    """The shift's start and end, and when entry closes (end + grace period)."""
    start = timezone.make_aware(datetime.combine(day, shift.start_time))
    end = start + timedelta(minutes=shift.length_minutes)
    grace = setting_on(day).grace_hours
    return start, end, end + timedelta(hours=float(grace))


def is_open(report: ShiftReport, now: datetime | None = None) -> bool:
    """Open for entry: during the shift and its grace period, or until an approved
    correction's new deadline (P3-09)."""
    start, _, close = window(report.day, report.shift)
    now = now or timezone.now()
    if report.reopened_until and now <= report.reopened_until:
        return True
    return start <= now <= close


def open_shifts(user: User) -> list[dict]:
    """The section shifts the user can enter now (yesterday's night shift included), with
    any report already made."""
    now = timezone.now()
    today = timezone.localdate()
    out = []
    shifts = list(Shift.objects.filter(is_active=True))
    reports = {
        (r.section_id, r.day, r.shift_id): r
        for r in ShiftReport.objects.filter(
            section__in=sections(user), day__gte=today - timedelta(days=1)
        )
    }
    for section in sections(user).order_by("code"):
        for day in (today - timedelta(days=1), today):
            for shift in shifts:
                start, end, close = window(day, shift)
                if not start <= now <= close:
                    continue
                r = reports.get((section.pk, day, shift.pk))
                out.append(
                    {
                        "section": section.code,
                        "section_name": section.name,
                        "section_type": section.section_type,
                        "day": day,
                        "shift": shift.code,
                        "shift_name": shift.name,
                        "closes_at": close,
                        "report": r.pk if r else None,
                        "status": r.status if r else "",
                    }
                )
    return out


# --- Opening, saving and submitting --------------------------------------------------------------


def _text(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def open_report(user: User, values: dict) -> ShiftReport:
    if not can_enter(user):
        raise ShiftReportError("Only a supervisor enters shift reports.")
    section = sections(user).filter(code=_text(values.get("section")).upper()).first()
    if section is None:
        raise ShiftReportError("Choose one of your sections.")
    shift = Shift.objects.filter(code=_text(values.get("shift")).upper(), is_active=True).first()
    if shift is None:
        raise ShiftReportError("Choose the shift.")
    try:
        day = datetime.fromisoformat(_text(values.get("day"))).date()
    except ValueError:
        raise ShiftReportError("Give the shift's date.") from None
    start, _, close = window(day, shift)
    if not start <= timezone.now() <= close:
        raise ShiftReportError(
            f"{shift.name} of {day} is open for entry from "
            f"{timezone.localtime(start):%d %b %H:%M} to {timezone.localtime(close):%d %b %H:%M}."
        )
    with audit_context("shift_report_opened", f"{section.code} {day} {shift.code}"):
        report, _ = ShiftReport.objects.get_or_create(
            section=section, day=day, shift=shift, defaults={"created_by": user}
        )
    return report


def _editable(user: User, report: ShiftReport) -> None:
    if not can_enter(user) or not sections(user).filter(pk=report.section_id).exists():
        raise ShiftReportError("Only a supervisor of the section enters its shift report.")
    if report.status not in EDITABLE:
        raise ShiftReportError(f"The report is {report.get_status_display().lower()}: locked.")
    if report.status == St.DRAFT and not is_open(report):
        raise ShiftReportError(
            "The shift's entry time and grace period are over: ask for a correction."
        )


def _at(report: ShiftReport, value, label: str) -> datetime:
    """A clock time (HH:MM) within the report's shift, on the right date."""
    text = _text(value)
    if len(text) == 4 and text[1] == ":":
        text = "0" + text  # 7:30 as 07:30
    try:
        clock = time.fromisoformat(text)
    except ValueError:
        raise ShiftReportError(f"Give the {label} as HH:MM.") from None
    day = report.day
    if report.shift.crosses_midnight and clock < report.shift.start_time:
        day += timedelta(days=1)
    moment = timezone.make_aware(datetime.combine(day, clock))
    start, end, _ = window(report.day, report.shift)
    if not start <= moment <= end:
        raise ShiftReportError(
            f"The {label} {clock:%H:%M} is outside {report.shift.name} "
            f"({report.shift.start_time:%H:%M}–{report.shift.end_time:%H:%M})."
        )
    return moment


def _whole(value, label: str, *, positive=False) -> int:
    text = _text(value).replace(",", "")
    try:
        number = int(text)
    except ValueError:
        raise ShiftReportError(f"The {label} is a whole number.") from None
    if number < 0 or (positive and number == 0) or number >= 10**15:
        raise ShiftReportError(f"The {label} is {'more than' if positive else 'at least'} 0.")
    return number


def _decimal(value, label: str, places: int) -> Decimal:
    try:
        number = Decimal(_text(value).replace(",", ""))
    except InvalidOperation:
        raise ShiftReportError(f"Give the {label}.") from None
    if not number.is_finite() or number < 0 or number >= Decimal("1e12"):
        raise ShiftReportError(f"The {label} is at least 0.")
    if number != number.quantize(Decimal(1).scaleb(-places)):
        raise ShiftReportError(f"The {label} has at most {places} decimal places.")
    return number


def _rows(values: dict, key: str) -> list[dict]:
    rows = values.get(key) or []
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ShiftReportError(f"Too many {key} lines.")
    return rows


class _Lookups:
    def __init__(self, report: ShiftReport):
        division = report.section.division
        self.division = division
        self.machines = {
            m.code: m
            for m in Machine.objects.filter(section=report.section).exclude(
                status=Machine.Status.RETIRED
            )
        }
        self.orders = {
            o.pk: o
            for o in ProductionOrder.objects.filter(
                division=division, status=ProductionOrder.Status.RELEASED
            ).select_related("item", "mould", "bom")
        }
        # P3-12: the released job orders of the division, for a machining section.
        self.jobs = {}
        if report.section.section_type == Section.Type.MACHINING:
            self.jobs = {
                j.number: j
                for j in JobOrder.objects.filter(
                    division=division, status=JobOrder.Status.RELEASED
                ).select_related("item")
            }
        reasons = ReasonCode.objects.filter(division=division, is_active=True)
        self.rejects = {r.code: r for r in reasons if r.kind == ReasonCode.Kind.REJECT}
        self.downtime = {r.code: r for r in reasons if r.kind == ReasonCode.Kind.DOWNTIME}

    def machine(self, value, label="machine") -> Machine:
        code = _text(value).upper()
        if code not in self.machines:
            raise ShiftReportError(f"{code or 'The ' + label} is not a machine of this section.")
        return self.machines[code]

    def lot(self, value) -> tuple[str, Item | None]:
        lot = _text(value).upper()
        if not lot:
            return "", None
        found = (
            StockMovement.objects.filter(lot_no__iexact=lot, division=self.division)
            .select_related("item")
            .first()
        )
        if found is None:
            raise ShiftReportError(f"There is no material batch {lot} in this division's stock.")
        return found.lot_no, found.item


def _runs(report: ShiftReport, values: dict, look: _Lookups) -> list[dict]:
    out = []
    for n, r in enumerate(_rows(values, "runs"), start=1):
        machine = look.machine(r.get("machine"))
        label = f"run {n} ({machine.code})"
        try:
            order = look.orders[int(_text(r.get("order")))]
        except (ValueError, KeyError):
            raise ShiftReportError(f"Choose a released production order for {label}.") from None
        started = _at(report, r.get("start_time"), f"start time of {label}")
        ended = _at(report, r.get("end_time"), f"end time of {label}")
        if ended <= started:
            raise ShiftReportError(f"The end time of {label} is after its start.")
        first = _whole(r.get("start_counter"), f"shot counter at the start of {label}")
        last = _whole(r.get("end_counter"), f"shot counter at the end of {label}")
        if last < first:
            raise ShiftReportError(f"The shot counter of {label} goes down ({first} to {last}).")
        lot, material = look.lot(r.get("material_lot"))
        number = _text(r.get("operator")).upper()
        operator = None
        if number:
            operator = Employee.objects.filter(
                number=number, division=look.division, leaving_date__isnull=True
            ).first()
            if operator is None:
                raise ShiftReportError(f"There is no employee {number} for {label}.")
        cavities = plan.cavities(order)
        rejects = []
        for x in r.get("rejects") or []:
            code = _text(x.get("reason")).upper()
            if code not in look.rejects:
                raise ShiftReportError(f"Choose a reject reason for {label}.")
            qty = _whole(x.get("quantity"), f"rejects of {label}", positive=True)
            rejects.append((look.rejects[code], qty))
        made = (last - first) * cavities
        rejected = sum(q for _, q in rejects)
        if rejected > made:
            raise ShiftReportError(
                f"The rejects of {label} ({rejected}) are more than it made "
                f"({last - first} shots × {cavities} = {made})."
            )
        entry = None
        if r.get("plan_entry"):
            entry = PlanEntry.objects.filter(
                pk=_whole(r.get("plan_entry"), "plan entry"),
                day=report.day,
                shift=report.shift,
            ).first()
        out.append(
            {
                "machine": machine,
                "order": order,
                "mould": order.mould,
                "plan_entry": entry,
                "material": material,
                "material_lot": lot,
                "operator": operator,
                "started_at": started,
                "ended_at": ended,
                "start_counter": first,
                "end_counter": last,
                "cavities": cavities,
                "good_quantity": Decimal(made - rejected),
                "rejects": rejects,
                "label": label,
            }
        )
    return out


def _downtime(report: ShiftReport, values: dict, look: _Lookups) -> list[dict]:
    out = []
    for n, d in enumerate(_rows(values, "downtime"), start=1):
        machine = look.machine(d.get("machine"))
        label = f"downtime {n} ({machine.code})"
        code = _text(d.get("reason")).upper()
        if code not in look.downtime:
            raise ShiftReportError(f"Choose the reason for {label}.")
        started = _at(report, d.get("start_time"), f"start time of {label}")
        ended = _at(report, d.get("end_time"), f"end time of {label}")
        if ended <= started:
            raise ShiftReportError(f"The end time of {label} is after its start.")
        out.append(
            {
                "machine": machine,
                "reason": look.downtime[code],
                "started_at": started,
                "ended_at": ended,
                "remarks": _text(d.get("remarks"))[:200],
                "label": label,
            }
        )
    return out


def _overlaps(rows: list[dict], kind: str, other) -> None:
    """Times on one machine never overlap, within the report or with other reports."""
    by_machine = defaultdict(list)
    for x in rows:
        by_machine[x["machine"].pk].append(x)
    for items in by_machine.values():
        items.sort(key=lambda x: x["started_at"])
        for a, b in zip(items, items[1:], strict=False):
            if b["started_at"] < a["ended_at"]:
                raise ShiftReportError(f"The times of {a['label']} and {b['label']} overlap.")
        for x in items:
            clash = other.filter(
                machine=x["machine"], started_at__lt=x["ended_at"], ended_at__gt=x["started_at"]
            ).first()
            if clash is not None:
                raise ShiftReportError(
                    f"The times of {x['label']} overlap {kind} on {x['machine'].code} in "
                    f"the report of {clash.report.day} {clash.report.shift.name}."
                )


def _counters(report: ShiftReport, runs: list[dict]) -> None:
    """A machine's shot counter never goes down from one run to the next."""
    by_machine = defaultdict(list)
    for x in runs:
        by_machine[x["machine"].pk].append(x)
    for items in by_machine.values():
        items.sort(key=lambda x: x["started_at"])
        before = (
            MouldingRun.objects.filter(
                machine=items[0]["machine"], started_at__lt=items[0]["started_at"]
            )
            .exclude(report=report)
            .aggregate(last=Max("end_counter"))["last"]
        )
        last = before
        for x in items:
            if last is not None and x["start_counter"] < last:
                raise ShiftReportError(
                    f"The shot counter of {x['label']} starts at {x['start_counter']}, below the "
                    f"last reading {last} on {x['machine'].code}."
                )
            last = x["end_counter"]


def _cycle(run: dict, downtime: list[dict]) -> Decimal | None:
    shots = run["end_counter"] - run["start_counter"]
    if not shots:
        return None
    seconds = (run["ended_at"] - run["started_at"]).total_seconds()
    for d in downtime:
        if d["machine"].pk == run["machine"].pk:
            overlap = min(d["ended_at"], run["ended_at"]) - max(d["started_at"], run["started_at"])
            seconds -= max(overlap.total_seconds(), 0)
    return (Decimal(str(max(seconds, 0))) / shots).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _materials(values: dict, look: _Lookups) -> list[dict]:
    out = []
    for n, m in enumerate(_rows(values, "materials"), start=1):
        kind = _text(m.get("kind")).lower()
        if kind not in MaterialEntry.Kind.values:
            raise ShiftReportError(f"Material line {n} is issued, returned or regrind.")
        lot, item = look.lot(m.get("lot_no"))
        if item is None:
            code = _text(m.get("item")).upper()
            item = Item.objects.filter(code=code).first()
            if item is None:
                raise ShiftReportError(f"Give the batch or the item of material line {n}.")
        if kind != MaterialEntry.Kind.REGRIND and not lot:
            raise ShiftReportError(f"Give the batch of material line {n} ({item.code}).")
        if kind == MaterialEntry.Kind.REGRIND and item.category != Item.Category.RAW_MATERIAL:
            raise ShiftReportError(f"Regrind is of a raw material, not {item.code}.")
        quantity = _decimal(m.get("quantity"), f"quantity of material line {n}", 3)
        if not quantity:
            raise ShiftReportError(f"The quantity of material line {n} is more than 0.")
        out.append({"kind": kind, "item": item, "lot_no": lot, "quantity": quantity})
    return out


def _manpower(values: dict, look: _Lookups) -> list[dict]:
    out = []
    for n, p in enumerate(_rows(values, "manpower"), start=1):
        machine = look.machine(p.get("machine")) if _text(p.get("machine")) else None
        people = _whole(p.get("people"), f"people on manpower line {n}", positive=True)
        if people > 999:
            raise ShiftReportError(f"Manpower line {n} has too many people.")
        overtime = _decimal(p.get("overtime_hours") or "0", f"overtime of manpower line {n}", 2)
        out.append({"machine": machine, "people": people, "overtime_hours": overtime})
    return out


def save(user: User, report: ShiftReport, values: dict) -> ShiftReport:
    """Save the whole report: runs with rejects, downtime, material, manpower and notes."""
    with transaction.atomic():
        report = (
            ShiftReport.objects.select_for_update()
            .select_related("section__division", "shift")
            .get(pk=report.pk)
        )
        _editable(user, report)
        # P3-21: a save made offline names the version it started from; if the report was
        # saved since, it is refused (never silently overwritten) and the supervisor chooses.
        base = values.get("base_version")
        if base and str(base) != version_of(report):
            raise ShiftReportConflict(
                "This report was saved by someone else after your copy: compare and choose."
            )
        look = _Lookups(report)
        machining = report.section.section_type == Section.Type.MACHINING
        if machining and _rows(values, "runs"):
            raise ShiftReportError("A machining section enters job card operations, not runs.")
        if not machining and _rows(values, "operations"):
            raise ShiftReportError("A moulding section enters machine runs, not job cards.")
        runs = _runs(report, values, look)
        downtime = _downtime(report, values, look)
        helpers = {"at": _at, "decimal": _decimal, "rows": _rows}
        try:
            work = job_cards.parse(report, values, look, helpers) if machining else []
            job_cards.check_flow(report, work)
        except JobCardError as error:
            raise ShiftReportError(str(error)) from None
        _overlaps(
            work,
            "work",
            JobCardEntry.objects.exclude(report=report).select_related("report__shift"),
        )
        others = MouldingRun.objects.exclude(report=report).select_related("report__shift")
        _overlaps(runs, "a run", others)
        stops = DowntimeEntry.objects.exclude(report=report).select_related("report__shift")
        _overlaps(downtime, "downtime", stops)
        _counters(report, runs)
        materials = _materials(values, look)
        manpower = _manpower(values, look)
        with audit_context("shift_report_saved", f"{report.section.code} {report.day}"):
            report.runs.all().delete()
            report.downtime.all().delete()
            report.materials.all().delete()
            report.manpower.all().delete()
            for r in runs:
                rejects = r.pop("rejects")
                r.pop("label")
                run = MouldingRun.objects.create(
                    report=report, actual_cycle_s=_cycle(r, downtime), **r
                )
                RejectEntry.objects.bulk_create(
                    RejectEntry(run=run, reason=reason, quantity=q) for reason, q in rejects
                )
            for d in downtime:
                d.pop("label")
                DowntimeEntry.objects.create(report=report, **d)
            job_cards.store(report, work, downtime)
            MaterialEntry.objects.bulk_create(MaterialEntry(report=report, **m) for m in materials)
            ManpowerEntry.objects.bulk_create(ManpowerEntry(report=report, **p) for p in manpower)
            if "notes" in values:
                report.notes = str(values.get("notes") or "")[:2000]
            report.updated_at = timezone.now()
            report.save(update_fields=["notes", "updated_at"])
        return report


def submit(user: User, report: ShiftReport) -> ShiftReport:
    with transaction.atomic():
        report = ShiftReport.objects.select_for_update().get(pk=report.pk)
        _editable(user, report)
        if not (report.runs.exists() or report.job_entries.exists() or report.downtime.exists()):
            raise ShiftReportError(
                "Enter at least one run, job card or downtime before submitting."
            )
        with audit_context("shift_report_submitted", f"{report.section.code} {report.day}"):
            used = (
                set(RejectEntry.objects.filter(run__report=report).values_list("reason", flat=True))
                | set(report.downtime.values_list("reason", flat=True))
                | set(
                    JobCardReject.objects.filter(entry__report=report).values_list(
                        "reason", flat=True
                    )
                )
            )
            ReasonCode.objects.filter(pk__in=used, first_used_at__isnull=True).update(
                first_used_at=timezone.now()
            )
            report.status = St.SUBMITTED
            report.submitted_by = user
            report.submitted_at = timezone.now()
            report.save()
            from . import shift_approval  # P3-09: the Production Manager approves it

            shift_approval.send(user, report)
        return report


# --- Reading -------------------------------------------------------------------------------------


def _n(value) -> str:
    if value is None:
        return ""
    value = Decimal(value)
    return f"{value.normalize():f}" if value else "0"


def _clock(moment: datetime) -> str:
    return f"{timezone.localtime(moment):%H:%M}"


def summary(report: ShiftReport) -> dict:
    runs = list(report.runs.select_related("machine", "order", "mould", "plan_entry"))
    rejects = defaultdict(int)
    for x in RejectEntry.objects.filter(run__report=report).select_related("reason"):
        rejects[f"{x.reason.code} {x.reason.name}"] += x.quantity
    stops = defaultdict(int)
    for d in report.downtime.select_related("reason"):
        stops[f"{d.reason.code} {d.reason.name}"] += int(
            (d.ended_at - d.started_at).total_seconds() // 60
        )
    good = sum((r.good_quantity for r in runs), ZERO)
    made = sum(r.shots * r.cavities for r in runs)
    rejected = sum(rejects.values())
    used = defaultdict(lambda: ZERO)
    for m in report.materials.select_related("item"):
        sign = {"issue": 1, "return": -1}.get(m.kind)
        if sign:
            used[(m.item.code, m.item.unit)] += sign * m.quantity
    regrind = sum((m.quantity for m in report.materials.all() if m.kind == "regrind"), ZERO)
    per_piece = []
    for (code, unit), quantity in used.items():
        good_with = (
            sum((r.good_quantity for r in runs if r.material and r.material.code == code), ZERO)
            or good
        )
        grams = quantity * (1000 if unit == "kg" else 1) if unit in ("kg", "g") else None
        per_piece.append(
            {
                "item": code,
                "used": _n(quantity),
                "unit": unit,
                "grams_per_good": _n((grams / good_with).quantize(Decimal("0.001")))
                if grams is not None and good_with
                else "",
            }
        )
    people = sum(p.people for p in report.manpower.all())
    overtime = sum((p.overtime_hours for p in report.manpower.all()), ZERO)
    return {
        "shots": sum(r.shots for r in runs),
        "made": made,
        "good": _n(good),
        "rejects": rejected,
        "reject_pct": _n((Decimal(rejected) * 100 / made).quantize(Decimal("0.01")))
        if made
        else "0",
        "rejects_by_reason": [{"reason": k, "quantity": v} for k, v in rejects.items()],
        "downtime_minutes": sum(stops.values()),
        "downtime_by_reason": [{"reason": k, "minutes": v} for k, v in stops.items()],
        "material": per_piece,
        "regrind": _n(regrind),
        "people": people,
        "overtime_hours": _n(overtime),
    }


def row(report: ShiftReport) -> dict:
    return {
        "id": report.pk,
        "section": report.section.code,
        "section_type": report.section.section_type,
        "day": report.day,
        "shift": report.shift.code,
        "shift_name": report.shift.name,
        "status": report.status,
        "status_label": report.get_status_display(),
        "created_by": report.created_by.full_name,
        "submitted_at": report.submitted_at,
    }


def payload(report: ShiftReport, user: User) -> dict:
    look = _Lookups(report)
    start, end, close = window(report.day, report.shift)
    editable = True
    try:
        _editable(user, report)
    except ShiftReportError:
        editable = False
    runs = []
    for r in report.runs.select_related("machine", "order__item", "mould", "operator", "material"):
        runs.append(
            {
                "machine": r.machine.code,
                "order": r.order_id,
                "order_number": r.order.number,
                "item": r.order.item.code,
                "mould": r.mould.code,
                "plan_entry": r.plan_entry_id,
                "material_lot": r.material_lot,
                "material": r.material.code if r.material_id else "",
                "operator": r.operator.number if r.operator_id else "",
                "start_time": _clock(r.started_at),
                "end_time": _clock(r.ended_at),
                "start_counter": r.start_counter,
                "end_counter": r.end_counter,
                "shots": r.shots,
                "cavities": r.cavities,
                "good_quantity": _n(r.good_quantity),
                "actual_cycle_s": _n(r.actual_cycle_s),
                "standard_cycle_s": _n(r.mould.cycle_time_s),
                "planned_quantity": _n(r.plan_entry.quantity) if r.plan_entry_id else "",
                "rejects": [
                    {"reason": x.reason.code, "quantity": x.quantity}
                    for x in r.rejects.select_related("reason")
                ],
            }
        )
    planned = PlanEntry.objects.filter(
        day=report.day, shift=report.shift, machine__section=report.section
    ).select_related("machine", "order__item", "mould")
    return row(report) | {
        "section_name": report.section.name,
        "shift_start": start,
        "shift_end": end,
        "closes_at": close,
        "notes": report.notes,
        "runs": runs,
        "downtime": [
            {
                "machine": d.machine.code,
                "reason": d.reason.code,
                "start_time": _clock(d.started_at),
                "end_time": _clock(d.ended_at),
                "remarks": d.remarks,
            }
            for d in report.downtime.select_related("machine", "reason")
        ],
        "materials": [
            {"kind": m.kind, "item": m.item.code, "lot_no": m.lot_no, "quantity": _n(m.quantity)}
            for m in report.materials.select_related("item")
        ],
        "manpower": [
            {
                "machine": p.machine.code if p.machine_id else "",
                "people": p.people,
                "overtime_hours": _n(p.overtime_hours),
            }
            for p in report.manpower.select_related("machine")
        ],
        "summary": summary(report) | {"machining": job_cards.summary(report)},
        "operations": job_cards.read(report),
        "editable": editable,
        "version": version_of(report),
        "options": {
            "machines": [{"code": c, "name": m.name} for c, m in sorted(look.machines.items())],
            "orders": [
                {
                    "id": o.pk,
                    "number": o.number,
                    "item": o.item.code,
                    "mould": o.mould.code if o.mould_id else "",
                }
                for o in look.orders.values()
            ],
            "plan": [
                {
                    "id": e.pk,
                    "machine": e.machine.code,
                    "order": e.order_id,
                    "order_number": e.order.number,
                    "item": e.order.item.code,
                    "mould": e.mould.code,
                    "quantity": _n(e.quantity),
                    "minutes": e.minutes,
                }
                for e in planned
            ],
            "jobs": job_cards.options(look),
            "reject_reasons": [{"code": c, "name": r.name} for c, r in look.rejects.items()],
            "downtime_reasons": [{"code": c, "name": r.name} for c, r in look.downtime.items()],
            "operators": [
                {"number": e.number, "name": e.full_name}
                for e in Employee.objects.filter(
                    section=report.section, leaving_date__isnull=True
                ).order_by("full_name")
            ],
        },
    }
