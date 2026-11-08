"""Mould maintenance (backlog P3-10; spec 7.4 "Mould maintenance", 7.5 `mould_maintenance`).

- A mould with a maintenance interval (shots, set on the mould, P3-01) is **due** when the
  shots since its last preventive maintenance reach the interval, and **approaching** from
  90% of it. Shot counts come from approved shift reports (P3-09).
- When approval takes a mould into "approaching" or "due", the **Production Manager** of the
  division is told (notification "mould_maintenance_due"); the maintenance page lists the
  moulds approaching or due.
- **Records**: preventive maintenance or a repair, with the date, the shot count then, the
  work done, its cost and who did it (a person or company; "our workshop" marks work done
  by the machining workshop, which will be an internal job, P3-15). Preventive maintenance
  restarts the count towards the next one. A record can also put a mould under
  maintenance or back into service. Records are never changed or deleted (database).
- Recorded by the Production Manager or the Planner; everyone in production planning reads
  them. The cost is recorded for the mould's history; spending is paid through vouchers.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, Notification, User
from apps.core.notifications import notify

from .models import Mould, MouldMaintenance

APPROACHING = Decimal("0.9")
K = MouldMaintenance.Kind


class MaintenanceError(Exception):
    pass


def can_record(user: User) -> bool:
    access = effective_access(user)
    return access.has("production_planning", "enter") or access.has(
        "production_approvals", "approve"
    )


# --- When maintenance is due ---------------------------------------------------------------------


def since(mould: Mould) -> int:
    return mould.shot_count - mould.shots_at_last_pm


def state(mould: Mould) -> str:
    """ "due", "approaching", "ok", or "" for a mould without an interval."""
    if not mould.pm_interval_shots:
        return ""
    used = since(mould)
    if used >= mould.pm_interval_shots:
        return "due"
    if used >= mould.pm_interval_shots * APPROACHING:
        return "approaching"
    return "ok"


def _managers(division: Division) -> list[User]:
    found = []
    for user in User.objects.filter(is_active=True).prefetch_related("divisions"):
        if not effective_access(user).has("production_approvals", "approve"):
            continue
        if division_scope(user).filter(pk=division.pk).exists():
            found.append(user)
    return found


def after_shots(mould_ids) -> None:
    """Called when shot counts went up (shift report approval): tell the Production Manager
    of each mould that has just become approaching or due, once per stage."""
    for mould in Mould.objects.filter(pk__in=list(mould_ids)).select_related("division"):
        stage = state(mould)
        if stage in ("approaching", "due") and not _already_told(mould, stage):
            _tell(mould, stage)


def _title(mould: Mould, stage: str) -> str:
    if stage == "due":
        return f"Mould {mould.code} is due for maintenance"
    return f"Mould {mould.code} is approaching maintenance"


def _already_told(mould: Mould, stage: str) -> bool:
    """Told of this stage since the mould's last preventive maintenance."""
    last = (
        MouldMaintenance.objects.filter(mould=mould, kind=K.PLANNED)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    found = Notification.objects.filter(event="mould_maintenance_due", title=_title(mould, stage))
    if last is not None:
        found = found.filter(created_at__gte=last)
    return found.exists()


def _tell(mould: Mould, stage: str) -> None:
    notify(
        _managers(mould.division),
        "mould_maintenance_due",
        title=_title(mould, stage),
        body=f"{mould.name}: {since(mould):,} shots since the last preventive maintenance; "
        f"the interval is {mould.pm_interval_shots:,}.",
        link="/mould-maintenance",
    )


# --- Recording -----------------------------------------------------------------------------------


def _text(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def record(user: User, values: dict) -> MouldMaintenance:
    if not can_record(user):
        raise MaintenanceError("The Production Manager or the Planner records maintenance.")
    code = _text(values.get("mould")).upper()
    kind = _text(values.get("kind")).lower()
    if kind not in K.values:
        raise MaintenanceError("Choose preventive maintenance or a repair.")
    try:
        done_on = date.fromisoformat(
            _text(values.get("done_on")) or timezone.localdate().isoformat()
        )
    except ValueError:
        raise MaintenanceError("Give the date, e.g. 2026-11-08.") from None
    if done_on > timezone.localdate():
        raise MaintenanceError("Maintenance is recorded once it is done, not in advance.")
    work = str(values.get("work_done") or "").strip()[:2000]
    if not work:
        raise MaintenanceError("Say what work was done.")
    done_by = _text(values.get("done_by"))[:100]
    if not done_by:
        raise MaintenanceError("Say who did the work.")
    try:
        cost = Decimal(_text(values.get("cost") or "0").replace(",", ""))
    except InvalidOperation:
        raise MaintenanceError("The cost is a number.") from None
    if not cost.is_finite() or cost < 0 or cost >= Decimal("1e15"):
        raise MaintenanceError("The cost is at least 0.")
    if cost != cost.quantize(Decimal("0.01")):
        raise MaintenanceError("The cost has at most 2 decimal places.")
    status = _text(values.get("status")).lower()
    if status and status not in (Mould.Status.ACTIVE, Mould.Status.MAINTENANCE):
        raise MaintenanceError("A record puts the mould under maintenance or back in service.")
    with audit_context("mould_maintenance", f"{code} {kind}"), transaction.atomic():
        mould = (
            Mould.objects.select_for_update()
            .filter(code=code, division__in=division_scope(user))
            .first()
        )
        if mould is None:
            raise MaintenanceError(f"There is no mould {code or '(blank)'}.")
        if mould.status == Mould.Status.RETIRED:
            raise MaintenanceError(f"Mould {mould.code} is retired.")
        entry = MouldMaintenance.objects.create(
            mould=mould,
            kind=kind,
            done_on=done_on,
            shot_count=mould.shot_count,
            work_done=work,
            cost=cost,
            done_by=done_by,
            by_workshop=bool(values.get("by_workshop")),
            created_by=user,
        )
        if kind == K.PLANNED:
            mould.shots_at_last_pm = mould.shot_count
        if status:
            mould.status = status
        mould.save()
        return entry


# --- Reading -------------------------------------------------------------------------------------


def row(m: MouldMaintenance) -> dict:
    return {
        "id": m.pk,
        "mould": m.mould.code,
        "kind": m.kind,
        "kind_label": m.get_kind_display(),
        "done_on": m.done_on,
        "shot_count": m.shot_count,
        "work_done": m.work_done,
        "cost": f"{m.cost:.2f}",
        "done_by": m.done_by,
        "by_workshop": m.by_workshop,
        "created_by": m.created_by.full_name,
    }


def mould_row(mould: Mould) -> dict:
    interval = mould.pm_interval_shots
    return {
        "code": mould.code,
        "name": mould.name,
        "owner": mould.owner,
        "status": mould.status,
        "status_label": mould.get_status_display(),
        "shot_count": mould.shot_count,
        "since": since(mould),
        "interval": interval,
        "left": max(interval - since(mould), 0) if interval else None,
        "state": state(mould),
    }


def overview(user: User, mould: str = "") -> dict:
    moulds = Mould.objects.filter(division__in=division_scope(user)).exclude(
        status=Mould.Status.RETIRED
    )
    rows = [mould_row(m) for m in moulds.order_by("code")]
    order = {"due": 0, "approaching": 1, "ok": 2, "": 3}
    rows.sort(key=lambda r: (order[r["state"]], r["left"] if r["left"] is not None else 0))
    history = MouldMaintenance.objects.filter(
        mould__division__in=division_scope(user)
    ).select_related("mould", "created_by")
    if mould:
        history = history.filter(mould__code=mould.upper())
    history = list(history[:200])
    return {
        "moulds": rows,
        "history": [row(m) for m in history],
        "total_cost": f"{sum((m.cost for m in history), Decimal(0)):.2f}",
        "can_record": can_record(user),
    }
