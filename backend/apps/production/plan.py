"""The moulding production plan (backlog P3-07; spec 7.3, 3A.1, 3A.2).

- The Production Planner picks which **released production order** runs on which
  **moulding machine** on which **shift** of a date (a night shift belongs to the date it
  starts), for the whole shift or some minutes of it. The order brings its mould.
- **Planned quantity** = whole shots in the planned time (minutes × 60 ÷ the mould's
  standard cycle time) × the part's cavities in the mould.
- **Warnings** (shown, never blocking, as the Planner may know better): the mould is too
  big for the machine (3A.1 sizes), the machine or the mould is under maintenance, the
  machine is planned twice on a shift or for more minutes than the shift has, the mould is
  on two machines in the same shift, the section has no crew on that shift (roster, 3A.2),
  the order is short of material, and the plan makes more than the order still needs.
- A plan is made for today or later; a past day's plan never changes (database). Entries
  after today are taken off the plan when their order is completed or cancelled.
- Supervisors see the plan of their own sections (shown again on their entry page, P3-08).
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_FLOOR, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.masters import rosters
from apps.masters.models import Machine, Section, Shift
from apps.masters.services import section_scope

from . import moulds, orders
from .models import Mould, PlanEntry, ProductionOrder

St = ProductionOrder.Status
ZERO = Decimal("0")
MAX_DAYS = 31


class PlanError(Exception):
    pass


# Owner's testing (T1, 10 Nov 2026): shown when a run was removed while someone was moving it.
GONE = "This run is no longer in the plan. It may have been removed; the plan has been reloaded."


def can_plan(user: User) -> bool:
    return effective_access(user).has("production_planning", "enter")


def _check(user: User) -> None:
    if not can_plan(user):
        raise PlanError("Only the Production Planner changes the production plan.")


def own_sections_only(user: User) -> bool:
    """A supervisor (shop floor, not planning or approving) sees only their own sections."""
    access = effective_access(user)
    return (
        access.has("shop_floor", "enter")
        and not access.has("production_planning", "enter")
        and not access.has("production_approvals", "approve")
    )


def visible(user: User):
    """Plan entries of the user's divisions; a supervisor sees their own sections."""
    found = PlanEntry.objects.select_related(
        "shift", "machine", "machine__section", "order", "order__item", "mould", "created_by"
    )
    if own_sections_only(user):
        return found.filter(machine__section__in=section_scope(user))
    return found.filter(order__division__in=division_scope(user))


# --- Working out ---------------------------------------------------------------------------------


def cavities(order: ProductionOrder) -> int:
    """The part's cavities in the order's mould (its BOM output, else the mould's part)."""
    if order.bom_id:
        out = order.bom.outputs.filter(item=order.item).first()
        if out is not None:
            return out.cavities
    part = order.mould.parts.filter(item=order.item).first() if order.mould_id else None
    return part.cavities if part else 1


def planned_quantity(order: ProductionOrder, minutes: int) -> Decimal:
    shots = (Decimal(minutes) * 60 / order.mould.cycle_time_s).to_integral_value(ROUND_FLOOR)
    return shots * cavities(order)


# --- Changing the plan ---------------------------------------------------------------------------


def _text(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def _values(user: User, values: dict, current: PlanEntry | None) -> dict:
    today = timezone.localdate()
    try:
        day = date.fromisoformat(_text(values.get("day", current.day if current else "")))
    except ValueError:
        raise PlanError("Give the date, e.g. 2026-12-01.") from None
    if day < today:
        raise PlanError("The plan is made for today or later.")
    shift = Shift.objects.filter(
        code=_text(values.get("shift", current.shift.code if current else "")).upper(),
        is_active=True,
    ).first()
    if shift is None:
        raise PlanError("Choose the shift.")
    code = _text(values.get("machine", current.machine.code if current else "")).upper()
    machine = (
        Machine.objects.filter(code=code, section__division__in=division_scope(user))
        .select_related("section")
        .first()
    )
    if machine is None:
        raise PlanError(f"There is no machine {code or '(blank)'}.")
    if machine.section.section_type != Section.Type.MOULDING:
        raise PlanError(f"{machine.code} is not a moulding machine.")
    if machine.status == Machine.Status.RETIRED:
        raise PlanError(f"{machine.code} is retired.")
    try:
        pk = int(_text(values.get("order", current.order_id if current else "")))
    except ValueError:
        raise PlanError("Choose the production order.") from None
    order = orders.visible(user).filter(pk=pk).first()
    if order is None:
        raise PlanError("Choose the production order.")
    if order.status != St.RELEASED:
        raise PlanError(f"{order.number} is not released.")
    if order.division_id != machine.section.division_id:
        raise PlanError(f"{order.number} is for division {order.division.code}.")
    if order.mould.status == Mould.Status.RETIRED:
        raise PlanError(f"Mould {order.mould.code} is retired.")
    text = _text(values.get("minutes", current.minutes if current else ""))
    try:
        minutes = int(text) if text else shift.working_minutes
    except ValueError:
        raise PlanError("The planned minutes are a whole number.") from None
    if not 0 < minutes <= shift.working_minutes:
        raise PlanError(
            f"The planned minutes are 1 to {shift.working_minutes} ({shift.name} working time)."
        )
    return {
        "day": day,
        "shift": shift,
        "machine": machine,
        "order": order,
        "mould": order.mould,
        "minutes": minutes,
        "quantity": planned_quantity(order, minutes),
        "notes": _text(values.get("notes", current.notes if current else ""))[:200],
    }


def add(user: User, values: dict) -> PlanEntry:
    _check(user)
    fields = _values(user, values, None)
    with audit_context("production_plan_added", fields["order"].number), transaction.atomic():
        return PlanEntry.objects.create(created_by=user, **fields)


def change(user: User, entry: PlanEntry, values: dict) -> PlanEntry:
    """Move an entry to another machine, shift or day, or change its minutes."""
    _check(user)
    if entry.day < timezone.localdate():
        raise PlanError("The plan of a past day never changes.")
    fields = _values(user, values, entry)
    with audit_context("production_plan_changed", entry.order.number), transaction.atomic():
        for key, value in fields.items():
            setattr(entry, key, value)
        entry.save()
        return entry


def copy_day(user: User, source: date, target: date) -> int:
    """Plan a day like another: each of its entries whose order is still released."""
    _check(user)
    if target < timezone.localdate():
        raise PlanError("The plan is made for today or later.")
    if source == target:
        raise PlanError("Choose another day to copy to.")
    entries = visible(user).filter(day=source, order__status=St.RELEASED)
    if not entries:
        raise PlanError(f"There is nothing planned on {source} to copy.")
    with audit_context("production_plan_copied", f"{source} to {target}"), transaction.atomic():
        for e in entries:
            PlanEntry.objects.create(
                day=target,
                shift=e.shift,
                machine=e.machine,
                order=e.order,
                mould=e.mould,
                minutes=e.minutes,
                quantity=e.quantity,
                notes=e.notes,
                created_by=user,
            )
    return len(entries)


def remove(user: User, entry: PlanEntry) -> None:
    _check(user)
    if entry.day < timezone.localdate():
        raise PlanError("The plan of a past day never changes.")
    with audit_context("production_plan_removed", entry.order.number), transaction.atomic():
        entry.delete()


# --- Reading, with the warnings ------------------------------------------------------------------


def _range(start, days) -> tuple[date, int]:
    try:
        first = date.fromisoformat(_text(start)) if start else timezone.localdate()
        count = int(days or 7)
    except ValueError:
        raise PlanError("Give the first day and the number of days.") from None
    if not 1 <= count <= MAX_DAYS:
        raise PlanError(f"Show 1 to {MAX_DAYS} days.")
    return first, count


def _crewed(sections: set, first: date, count: int) -> dict:
    """(section id, day) → the shift ids with someone rostered."""
    out: dict = defaultdict(set)
    for section in Section.objects.filter(pk__in=sections).select_related("division"):
        for day, entries in rosters.schedule(section.division, first, count, section):
            out[(section.pk, day)] |= {e.shift.pk for e in entries}
    return out


def warnings_for(entries: list[PlanEntry], first: date, count: int) -> dict[int, list[str]]:
    """Each entry's warnings."""
    found: dict[int, list[str]] = defaultdict(list)
    by_machine = defaultdict(list)
    by_mould = defaultdict(list)
    for e in entries:
        by_machine[(e.day, e.shift_id, e.machine_id)].append(e)
        by_mould[(e.day, e.shift_id, e.mould_id)].append(e)
    crewed = _crewed({e.machine.section_id for e in entries}, first, count)
    short: dict[int, bool] = {}
    planned = dict(
        PlanEntry.objects.filter(order__in={e.order_id for e in entries})
        .values("order")
        .annotate(total=Sum("quantity"))
        .values_list("order", "total")
    )
    fits: dict[tuple, list[str]] = {}
    for e in entries:
        w = found[e.pk]
        key = (e.mould_id, e.machine_id)
        if key not in fits:
            fits[key] = moulds.fit(e.mould, e.machine)
        w += [f"Too big: {x}" for x in fits[key]]
        if e.machine.status == Machine.Status.MAINTENANCE:
            w.append(f"{e.machine.code} is under maintenance.")
        if e.mould.status == Mould.Status.MAINTENANCE:
            w.append(f"Mould {e.mould.code} is under maintenance.")
        same = by_machine[(e.day, e.shift_id, e.machine_id)]
        if len(same) > 1:
            w.append(f"{e.machine.code} is planned {len(same)} times on this shift.")
            if sum(x.minutes for x in same) > e.shift.working_minutes:
                w.append(f"{e.machine.code} is planned for more than the shift's working time.")
        others = [x for x in by_mould[(e.day, e.shift_id, e.mould_id)] if x.pk != e.pk]
        if any(x.machine_id != e.machine_id for x in others):
            w.append(f"Mould {e.mould.code} is also planned on another machine on this shift.")
        if e.shift_id not in crewed[(e.machine.section_id, e.day)]:
            w.append(f"No crew is rostered on {e.shift.name} in {e.machine.section.code}.")
        if e.order_id not in short:
            short[e.order_id] = any(
                r["buy"] and r["shortage"] > 0 for r in orders.requirements(e.order)
            )
        if short[e.order_id]:
            w.append(f"{e.order.number} is short of material.")
        if (planned.get(e.order_id) or ZERO) > e.order.quantity:
            w.append(f"The plan makes more than {e.order.number} needs.")
    return found


def _n(value: Decimal) -> str:
    return f"{value.normalize():f}" if value else "0"


def entry_row(e: PlanEntry, warnings: list[str]) -> dict:
    return {
        "id": e.pk,
        "day": e.day,
        "shift": e.shift.code,
        "machine": e.machine.code,
        "section": e.machine.section.code,
        "order": e.order_id,
        "order_number": e.order.number,
        "item": e.order.item.code,
        "item_name": e.order.item.name,
        "mould": e.mould.code,
        "minutes": e.minutes,
        "quantity": _n(e.quantity),
        "notes": e.notes,
        "past": e.day < timezone.localdate(),
        "warnings": warnings,
    }


def board(user: User, start=None, days=None) -> dict:
    """The plan for a date range: the shifts, moulding machines, entries with their
    warnings, and the released orders with what is planned of each."""
    first, count = _range(start, days)
    last = first + timedelta(days=count - 1)
    entries = list(visible(user).filter(day__range=(first, last)))
    warnings = warnings_for(entries, first, count)
    if own_sections_only(user):
        sections = section_scope(user)
    else:
        sections = Section.objects.filter(division__in=division_scope(user))
    machines = (
        Machine.objects.filter(section__section_type=Section.Type.MOULDING, section__in=sections)
        .exclude(status=Machine.Status.RETIRED)
        .select_related("section")
        .order_by("code")
    )
    supervised = set(
        Section.supervisors.through.objects.filter(
            section__in={m.section_id for m in machines}, user__is_active=True
        ).values_list("section_id", flat=True)
    )
    released = orders.visible(user).filter(status=St.RELEASED).order_by("number")
    planned = dict(
        PlanEntry.objects.filter(order__in=released)
        .values("order")
        .annotate(total=Sum("quantity"))
        .values_list("order", "total")
    )
    return {
        "first": first,
        "days": [first + timedelta(days=n) for n in range(count)],
        "shifts": [
            {"code": s.code, "name": s.name, "minutes": s.working_minutes}
            for s in Shift.objects.filter(is_active=True)
        ],
        "machines": [
            {
                "code": m.code,
                "name": m.name,
                "section": m.section.code,
                "status": m.status,
                # Owner's testing (T4): without a supervisor, nobody gets this machine's work
                # shift report, so its runs are never reported.
                "supervised": m.section_id in supervised,
            }
            for m in machines
        ],
        "entries": [entry_row(e, warnings[e.pk]) for e in entries],
        "orders": [
            {
                "id": o.pk,
                "number": o.number,
                "item": o.item.code,
                "item_name": o.item.name,
                "mould": o.mould.code if o.mould_id else "",
                "quantity": _n(o.quantity),
                "planned": _n(planned.get(o.pk) or ZERO),
                "first_due": min((d.due_date for d in o.dues.all()), default=None),
            }
            for o in released.prefetch_related("dues")
        ],
        "can_plan": can_plan(user),
    }


def mine(user: User) -> dict:
    """Today's and tomorrow's plan of the sections the user may work in (supervisors)."""
    today = timezone.localdate()
    entries = list(
        PlanEntry.objects.filter(
            day__range=(today, today + timedelta(days=1)),
            machine__section__in=section_scope(user),
        ).select_related("shift", "machine", "machine__section", "order", "order__item", "mould")
    )
    return {"entries": [entry_row(e, []) for e in entries]}
