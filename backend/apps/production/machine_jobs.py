"""Machine time: jobs started and finished live at the machine (backlog P3-24 a; owner,
15 Nov 2026).

The Production Team Leader (or a supervisor) of a section starts a job on one of its
machines and finishes it when the machine stops:

- **Workshop:** a released job order's operation done in the workshop, picked or scanned
  from its job card ("JO26110001/20"). Drawing no. comes from the job and can be changed or
  left blank. On finishing: pieces completed and rejected.
- **Moulding:** a released production order and its mould, with the shot counter at start;
  on finishing, the counter at the end.
- **Checks:** the machine is of one of the person's sections, active (not retired, not
  under maintenance); **one running job per machine** (database too), unless a person with
  Approve on machine time (the Production Manager) starts a second, with a reason; times
  never in the future, the finish after the start.
- The time is worked out from start and finish (running jobs: up to now).

P3-24 c: the jobs of a shift are offered to the section's Work shift report as lines, split
at shift changes with pieces and shots shared by time; a line keeps its link to the job."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.access import division_scope, effective_access
from apps.core.models import User
from apps.masters.models import Machine, Section
from apps.payroll.models import Employee

from .models import JobOperation, JobOrder, MachineJob, Mould, ProductionOrder

AREA = "machine_time"
SECTION_TYPES = (Section.Type.MOULDING, Section.Type.MACHINING)


class MachineJobError(Exception):
    pass


# --- Who may do what ---------------------------------------------------------------------


def can_see(user: User) -> bool:
    return effective_access(user).has(AREA, "view")


def can_enter(user: User) -> bool:
    """Start and finish jobs: Enter (team leader, supervisor) or Approve (the manager)."""
    access = effective_access(user)
    return access.has(AREA, "enter") or access.has(AREA, "approve")


def can_allow_second(user: User) -> bool:
    return effective_access(user).has(AREA, "approve")


def own_sections_only(user: User) -> bool:
    """A team leader or supervisor works in their own sections; a manager sees them all."""
    access = effective_access(user)
    return access.has(AREA, "enter") and not access.has(AREA, "approve")


def sections(user: User):
    found = Section.objects.filter(
        division__in=division_scope(user), section_type__in=SECTION_TYPES, is_active=True
    )
    if own_sections_only(user):
        found = found.filter(Q(supervisors=user) | Q(users=user))
    return found.distinct().order_by("division__code", "code")


def machines(user: User):
    return (
        Machine.objects.filter(section__in=sections(user))
        .exclude(status=Machine.Status.RETIRED)
        .select_related("section", "section__division")
        .order_by("section__code", "code")
    )


def visible(user: User):
    return MachineJob.objects.filter(machine__section__in=sections(user)).select_related(
        "machine",
        "machine__section",
        "job",
        "operation",
        "order",
        "order__item",
        "mould",
        "operator",
        "started_by",
        "ended_by",
    )


# --- Helpers -----------------------------------------------------------------------------


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _moment(value, field: str) -> datetime:
    """A time given by the page (ISO), or now when left out; never in the future."""
    now = timezone.now()
    if value in (None, ""):
        return now
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            raise MachineJobError(f"The {field} time is not a valid date and time.") from None
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    if moment > now + timezone.timedelta(minutes=1):
        raise MachineJobError(f"The {field} time cannot be in the future.")
    return moment


def _quantity(value, field: str) -> Decimal:
    try:
        number = Decimal(str(value if value not in (None, "") else "0"))
    except InvalidOperation:
        raise MachineJobError(f"{field} must be a number.") from None
    if number < 0:
        raise MachineJobError(f"{field} cannot be below zero.")
    return number


def _counter(value, field: str) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise MachineJobError(f"Enter the {field} shot counter.") from None
    if number < 0:
        raise MachineJobError(f"The {field} shot counter cannot be below zero.")
    return number


def _machine(user: User, code) -> Machine:
    code = _text(code, 20).upper()
    machine = machines(user).filter(code=code).first()
    if machine is None:
        raise MachineJobError(f"{code or 'The machine'} is not a machine of your sections.")
    if machine.status == Machine.Status.MAINTENANCE:
        raise MachineJobError(f"{machine.code} is under maintenance; it cannot start a job.")
    return machine


def _job(machine: Machine, value) -> tuple[JobOrder, JobOperation]:
    """A released job of the machine's division and one of its workshop operations, from the
    job number with the operation ("JO26110001/20", as on the job card)."""
    text = " ".join(str(value or "").split()).upper()
    number, _, seq = text.partition("/")
    job = JobOrder.objects.filter(
        number=number.strip(),
        division=machine.section.division,
        status=JobOrder.Status.RELEASED,
    ).first()
    if job is None:
        raise MachineJobError(f"{number or 'The job'} is not a released job of this division.")
    if not seq.strip():
        raise MachineJobError(f"Choose the operation of {job.number} (or scan its job card).")
    try:
        operation = job.operations.get(seq=int(seq))
    except (ValueError, JobOperation.DoesNotExist):
        raise MachineJobError(f"{job.number} has no operation {seq.strip()}.") from None
    if operation.subcontract:
        raise MachineJobError(
            f"Operation {operation.seq} of {job.number} is done by a subcontractor."
        )
    return job, operation


def _order(machine: Machine, value, mould_code) -> tuple[ProductionOrder, Mould]:
    text = " ".join(str(value or "").split()).upper()
    order = (
        ProductionOrder.objects.filter(
            number=text, division=machine.section.division, status=ProductionOrder.Status.RELEASED
        )
        .select_related("mould")
        .first()
    )
    if order is None:
        raise MachineJobError(
            f"{text or 'The order'} is not a released production order of this division."
        )
    code = _text(mould_code, 30).upper()
    if code:
        mould = Mould.objects.filter(code=code).first()
        if mould is None:
            raise MachineJobError(f"There is no mould {code}.")
    elif order.mould_id:
        mould = order.mould
    else:
        raise MachineJobError(f"Choose the mould for {order.number}.")
    return order, mould


def _operator(machine: Machine, value) -> Employee | None:
    code = _text(value, 20)
    if not code:
        return None
    found = Employee.objects.filter(number__iexact=code, division=machine.section.division).first()
    if found is None:
        raise MachineJobError(f"There is no employee {code}.")
    return found


def minutes(job: MachineJob, now: datetime | None = None) -> int:
    """Whole minutes worked: start to finish, or to now while it runs."""
    end = job.ended_at or now or timezone.now()
    return max(0, int((end - job.started_at).total_seconds() // 60))


def hours(job: MachineJob, now: datetime | None = None) -> Decimal:
    return (Decimal(minutes(job, now)) / 60).quantize(Decimal("0.01"), ROUND_HALF_UP)


def running(machine: Machine):
    return MachineJob.objects.filter(machine=machine, ended_at__isnull=True)


# --- Start and finish --------------------------------------------------------------------


def start(user: User, values: dict) -> MachineJob:
    if not can_enter(user):
        raise MachineJobError("You cannot start jobs on machines.")
    machine = _machine(user, values.get("machine"))
    started_at = _moment(values.get("started_at"), "start")
    description = _text(values.get("description"), 200)
    second_reason = _text(values.get("second_reason"), 300)
    job = operation = order = mould = None
    start_counter = None
    drawing = _text(values.get("drawing_no"), 50)
    if machine.section.section_type == Section.Type.MACHINING:
        job, operation = _job(machine, values.get("job"))
        kind = MachineJob.Kind.JOB
        if "drawing_no" not in values:
            drawing = job.drawing_no
        description = description or f"{operation.name}"
    else:
        order, mould = _order(machine, values.get("order"), values.get("mould"))
        kind = MachineJob.Kind.MOULDING
        start_counter = _counter(values.get("start_counter"), "starting")
        description = description or (order.item.code if order.item_id else order.number)

    with transaction.atomic():
        Machine.objects.select_for_update().filter(pk=machine.pk).first()
        busy = running(machine).first()
        allowed_by = None
        if busy is not None:
            what = busy.job.number if busy.job_id else busy.order.number
            if not can_allow_second(user):
                raise MachineJobError(
                    f"{machine.code} is already running {what}. Finish it first, or ask the "
                    "Production Manager to allow a second job."
                )
            if not second_reason:
                raise MachineJobError(
                    f"{machine.code} is already running {what}: say why a second job is allowed."
                )
            allowed_by = user
        try:
            return MachineJob.objects.create(
                machine=machine,
                kind=kind,
                job=job,
                operation=operation,
                order=order,
                mould=mould,
                operator=_operator(machine, values.get("operator")),
                drawing_no=drawing,
                description=description,
                notes=_text(values.get("notes"), 300),
                started_at=started_at,
                started_by=user,
                start_counter=start_counter,
                second_allowed_by=allowed_by,
                second_reason=second_reason if allowed_by else "",
            )
        except IntegrityError:
            raise MachineJobError(f"{machine.code} is already running a job.") from None


def _acting(user: User, pk: int) -> MachineJob:
    job = visible(user).select_for_update(of=("self",)).filter(pk=pk).first()
    if job is None:
        raise MachineJobError("That job is not on a machine of your sections.")
    return job


def finish(user: User, pk: int, values: dict) -> MachineJob:
    if not can_enter(user):
        raise MachineJobError("You cannot finish jobs on machines.")
    with transaction.atomic():
        job = _acting(user, pk)
        if job.ended_at is not None:
            raise MachineJobError("This job is already finished.")
        ended_at = _moment(values.get("ended_at"), "finish")
        if ended_at <= job.started_at:
            raise MachineJobError("The finish must be after the start.")
        if job.kind == MachineJob.Kind.JOB:
            job.completed = _quantity(values.get("completed"), "Pieces completed")
            job.rejected = _quantity(values.get("rejected"), "Pieces rejected")
        else:
            job.end_counter = _counter(values.get("end_counter"), "finishing")
            if job.end_counter < job.start_counter:
                raise MachineJobError("The shot counter at the end is below the one at the start.")
        notes = _text(values.get("notes"), 300)
        if notes:
            job.notes = notes
        job.ended_at = ended_at
        job.ended_by = user
        job.save()
        return job


# --- What the pages read -----------------------------------------------------------------


def _clock(moment: datetime | None) -> str | None:
    return timezone.localtime(moment).isoformat() if moment else None


def payload(job: MachineJob, now: datetime | None = None) -> dict:
    return {
        "id": job.pk,
        "machine": job.machine.code,
        "section": job.machine.section.code,
        "kind": job.kind,
        "job": job.job.number if job.job_id else None,
        "operation": job.operation.seq if job.operation_id else None,
        "operation_name": job.operation.name if job.operation_id else None,
        "order": job.order.number if job.order_id else None,
        "item": job.order.item.code if job.order_id and job.order.item_id else None,
        "mould": job.mould.code if job.mould_id else None,
        "operator": job.operator.full_name if job.operator_id else None,
        "drawing_no": job.drawing_no,
        "description": job.description,
        "notes": job.notes,
        "started_at": _clock(job.started_at),
        "started_by": job.started_by.full_name,
        "ended_at": _clock(job.ended_at),
        "ended_by": job.ended_by.full_name if job.ended_by_id else None,
        "minutes": minutes(job, now),
        "hours": str(hours(job, now)),
        "completed": None if job.completed is None else f"{job.completed.normalize():f}",
        "rejected": None if job.rejected is None else f"{job.rejected.normalize():f}",
        "start_counter": job.start_counter,
        "end_counter": job.end_counter,
        "second_allowed_by": job.second_allowed_by.full_name if job.second_allowed_by_id else None,
        "second_reason": job.second_reason,
    }


def board(user: User) -> dict:
    """Every machine of the person's sections with what it is doing now."""
    now = timezone.now()
    jobs: dict[int, list[MachineJob]] = {}
    for job in visible(user).filter(ended_at__isnull=True).order_by("started_at"):
        jobs.setdefault(job.machine_id, []).append(job)
    out = []
    for m in machines(user):
        current = jobs.get(m.pk, [])
        status = (
            "maintenance"
            if m.status == Machine.Status.MAINTENANCE
            else ("running" if current else "idle")
        )
        out.append(
            {
                "code": m.code,
                "name": m.name,
                "section": m.section.code,
                "section_type": m.section.section_type,
                "status": status,
                "jobs": [payload(j, now) for j in current],
            }
        )
    return {
        "now": _clock(now),
        "machines": out,
        "can_enter": can_enter(user),
        "can_allow_second": can_allow_second(user),
    }


def options(user: User, code) -> dict:
    """What can be started on a machine: the released jobs of its division with their
    workshop operations (this machine's first), or the released production orders."""
    machine = _machine(user, code)
    division = machine.section.division
    if machine.section.section_type == Section.Type.MACHINING:
        out = []
        found = (
            JobOrder.objects.filter(division=division, status=JobOrder.Status.RELEASED)
            .select_related("item")
            .order_by("number")
        )
        for job in found:
            ops = [
                {
                    "seq": op.seq,
                    "name": op.name,
                    "card": f"{job.number}/{op.seq}",
                    "here": op.machine_id == machine.pk,
                }
                for op in job.operations.filter(subcontract=False).order_by("seq")
            ]
            if ops:
                out.append(
                    {
                        "number": job.number,
                        "item": job.item.code if job.item_id else "",
                        "description": job.description,
                        "drawing_no": job.drawing_no,
                        "operations": ops,
                    }
                )
        out.sort(key=lambda j: not any(op["here"] for op in j["operations"]))
        return {"kind": MachineJob.Kind.JOB, "jobs": out, "orders": []}
    orders = (
        ProductionOrder.objects.filter(division=division, status=ProductionOrder.Status.RELEASED)
        .select_related("item", "mould")
        .order_by("number")
    )
    return {
        "kind": MachineJob.Kind.MOULDING,
        "jobs": [],
        "orders": [
            {
                "number": o.number,
                "item": o.item.code if o.item_id else "",
                "mould": o.mould.code if o.mould_id else "",
            }
            for o in orders
        ],
    }


def recent(user: User, limit: int = 50) -> list[dict]:
    """The latest jobs of the person's sections, running and finished."""
    now = timezone.now()
    return [payload(j, now) for j in visible(user).order_by("-started_at", "-id")[:limit]]


# --- Into the shift report (P3-24 c) -----------------------------------------------------


def _hhmm(moment: datetime) -> str:
    return f"{timezone.localtime(moment):%H:%M}"


def for_report(report, start: datetime, end: datetime) -> list[dict]:
    """The Team Leader's jobs on the section's machines in this shift, as report lines ready
    to add: the part of each job inside the shift (a job across a shift change is split at
    it; its pieces or shots shared by time), those not yet in this report. A job still
    running is offered once the shift is over, up to the shift's end."""
    now = timezone.now()
    linked = set(report.runs.exclude(machine_job=None).values_list("machine_job_id", flat=True))
    linked |= set(
        report.job_entries.exclude(machine_job=None).values_list("machine_job_id", flat=True)
    )
    found = (
        MachineJob.objects.filter(machine__section=report.section, started_at__lt=end)
        .filter(Q(ended_at__gt=start) | Q(ended_at__isnull=True))
        .exclude(pk__in=linked)
        .select_related("machine", "job", "operation", "order", "mould", "operator", "started_by")
        .order_by("machine__code", "started_at")
    )
    out = []
    for j in found:
        finish = j.ended_at
        if finish is None:
            if now < end:
                continue  # still running in this shift: offered when it finishes or the shift ends
            finish = end
        a, b = max(j.started_at, start), min(finish, end)
        if b <= a:
            continue
        row = {
            "machine_job": j.pk,
            "machine": j.machine.code,
            "operator": j.operator.number if j.operator_id else "",
            "start_time": _hhmm(a),
            "end_time": _hhmm(b),
            "started_by": j.started_by.full_name,
            "running": j.ended_at is None,
        }
        if j.kind == MachineJob.Kind.JOB:
            row |= {
                "kind": "job",
                "job": j.job.number,
                "operation": j.operation.seq,
                "operation_name": j.operation.name,
                "completed": _piece_part(j, j.completed, a, b, finish),
                "rejected": _piece_part(j, j.rejected, a, b, finish),
                "notes": j.notes,
            }
        else:
            total = None if j.end_counter is None else j.end_counter - j.start_counter
            row |= {
                "kind": "moulding",
                "order": j.order_id,
                "order_number": j.order.number,
                "mould": j.mould.code,
                "start_counter": j.start_counter
                + (_upto(total, j.started_at, a, finish) if total is not None else 0),
                "end_counter": None
                if total is None
                else j.start_counter + _upto(total, j.started_at, b, finish),
            }
        out.append(row)
    return out


def _upto(total, started: datetime, moment: datetime, finish: datetime) -> int:
    """The part of a total done by a moment, shared by time, in whole pieces or shots, so
    the parts of a job split at shift changes always add up to the total."""
    span = Decimal((finish - started).total_seconds())
    return int(Decimal(total) * Decimal((moment - started).total_seconds()) // span)


def _piece_part(j: MachineJob, total, a: datetime, b: datetime, finish: datetime) -> str:
    if j.ended_at is None or total is None:
        return ""  # pieces are counted when the job finishes
    if a == j.started_at and b == finish:
        return f"{total.normalize():f}"
    return str(_upto(total, j.started_at, b, finish) - _upto(total, j.started_at, a, finish))


def check_link(report, machine, value, started_at, ended_at) -> MachineJob | None:
    """A line names the machine job it was filled from: of this machine, overlapping it."""
    if value in (None, ""):
        return None
    try:
        pk = int(str(value))
    except ValueError:
        return None
    found = MachineJob.objects.filter(pk=pk, machine=machine, started_at__lt=ended_at).filter(
        Q(ended_at__gt=started_at) | Q(ended_at__isnull=True)
    )
    return found.first()


# --- The Dashboard: machines now (P3-24 d) -------------------------------------------------


def today(user: User) -> dict:
    """The Dashboard's machine panel: how many machines are running, idle and under
    maintenance, what each running one is doing, the jobs finished today with their times,
    and the hours each machine ran today (Sri Lanka day, running jobs up to now)."""
    now = timezone.now()
    local = timezone.localtime(now)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    current = board(user)
    counts = {"running": 0, "idle": 0, "maintenance": 0}
    for m in current["machines"]:
        counts[m["status"]] += 1
    day_jobs = (
        visible(user)
        .filter(started_at__lt=now)
        .filter(Q(ended_at__gt=start) | Q(ended_at__isnull=True))
    )
    minutes_by_machine: dict[str, int] = {}
    for j in day_jobs:
        a = max(j.started_at, start)
        b = j.ended_at or now
        if b > a:
            minutes_by_machine[j.machine.code] = minutes_by_machine.get(j.machine.code, 0) + int(
                (b - a).total_seconds() // 60
            )
    finished = [
        payload(j, now)
        for j in visible(user)
        .filter(ended_at__gte=start, ended_at__lte=now)
        .order_by("-ended_at", "-id")[:20]
    ]
    return {
        "now": current["now"],
        "counts": counts,
        "running": [m for m in current["machines"] if m["status"] == "running"],
        "idle": [m["code"] for m in current["machines"] if m["status"] == "idle"],
        "maintenance": [m["code"] for m in current["machines"] if m["status"] == "maintenance"],
        "finished": finished,
        "hours": [
            {
                "machine": m["code"],
                "name": m["name"],
                "minutes": minutes_by_machine.get(m["code"], 0),
                # Share of the day so far the machine ran (utilisation today).
                "pct": str(
                    (
                        Decimal(minutes_by_machine.get(m["code"], 0))
                        * 100
                        / Decimal(max(1, int((now - start).total_seconds() // 60)))
                    ).quantize(Decimal("0.1"), ROUND_HALF_UP)
                ),
            }
            for m in current["machines"]
        ],
    }
