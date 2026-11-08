"""Production cost rates (backlog P3-05; spec 7.7 "Where each cost comes from"; rule 11).

Dated rates kept by the Accountant (anyone who can enter in Accounting), which standard
costs (BOMs, P3-04) and later order costing (P3-16) use:

- **Labour** per section, LKR per hour. By default the latest approved payroll's labour cost
  per hour (P2B-13), which the Accountant accepts or overrides. A section with fewer than
  three people in the payroll is offered its division's rate instead, so the rate never
  shows one or two people's pay. With no accepted rate, labour is listed as not costed.
- **Overhead** per machine hour, per section or for one machine (a machine's own rate beats
  its section's). **0 until set** (owner, 7 Nov 2026); P3-23 later works it out from past
  data.
- **Regrind** credit per kg: **100% of the original material's cost** (owner, 7 Nov 2026),
  i.e. the material's weighted average stock cost at the time, unless the Accountant sets a
  dated value per kg for that material.
- **Mould amortisation** per shot for **company moulds only**: the mould's cost ÷ its
  expected life in shots. Customer moulds are never amortised (database); a company mould
  with no rate yet costs 0 (its cost is not in the fixed asset register yet, owner).

A rate applies from a date, today or later; a rate in force never changes and is never
deleted, and one entered for a future date can be replaced or removed until then
(database). Everyone in production planning can read the rates; the payroll figures behind
the labour suggestion are shown only to those who keep the rates.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.inventory.issues import cost_of
from apps.inventory.models import Item
from apps.masters.models import Machine, Section
from apps.payroll import labour
from apps.payroll.models import PayrollRun

from .models import CostRate, Mould

K = CostRate.Kind
ZERO = Decimal("0")
CENT = Decimal("0.01")
FOUR = Decimal("0.0001")
MIN_PEOPLE = 3  # fewer people in a section: offer the division's rate (privacy)
MAX_RATE = Decimal("10000000")


class RateError(Exception):
    pass


def can_keep(user: User) -> bool:
    """The Accountant keeps the rates (Accounting, enter); others only read them."""
    return effective_access(user).has("accounting", "enter")


def _check(user: User) -> None:
    if not can_keep(user):
        raise RateError("Only the Accountant keeps the production cost rates.")


# --- Rates in force ------------------------------------------------------------------------------


def _in_force(day: date, **target) -> CostRate | None:
    return (
        CostRate.objects.filter(effective_from__lte=day, **target)
        .order_by("-effective_from")
        .first()
    )


def labour_on(section: Section, day: date | None = None) -> Decimal | None:
    """LKR per hour of the section's labour, or None until a rate is accepted or entered."""
    found = _in_force(day or timezone.localdate(), kind=K.LABOUR, section=section)
    return found.rate if found else None


def overhead_on(section: Section, machine: Machine | None = None, day=None) -> Decimal:
    """LKR per machine hour: the machine's own rate, else its section's, else 0."""
    day = day or timezone.localdate()
    if machine is not None:
        own = _in_force(day, kind=K.OVERHEAD, section=machine.section, machine=machine)
        if own:
            return own.rate
        section = machine.section
    found = _in_force(day, kind=K.OVERHEAD, section=section, machine__isnull=True)
    return found.rate if found else ZERO


def _per_kg(material: Item, value: Decimal) -> Decimal | None:
    if material.unit == Item.Unit.KG:
        return value
    if material.unit == Item.Unit.G:
        return value * 1000
    return None


def regrind_on(material: Item, day: date | None = None) -> dict:
    """The credit per kg of regrind of a material: the Accountant's dated value, else 100%
    of the material's stock cost (None while it has no stock cost)."""
    found = _in_force(day or timezone.localdate(), kind=K.REGRIND, material=material)
    if found:
        return {"per_kg": found.rate, "basis": "set"}
    stock = cost_of(material)
    per_kg = _per_kg(material, stock) if stock else None
    return {
        "per_kg": per_kg.quantize(FOUR, ROUND_HALF_UP) if per_kg is not None else None,
        "basis": "material",
    }


def mould_on(mould: Mould | None, day: date | None = None) -> Decimal:
    """LKR per shot for a company mould; 0 for customer moulds and until a rate is entered."""
    if mould is None or mould.owner != Mould.Owner.COMPANY:
        return ZERO
    found = _in_force(day or timezone.localdate(), kind=K.MOULD, mould=mould)
    return found.rate if found else ZERO


# --- The payroll's labour rates ------------------------------------------------------------------


def suggestions() -> dict[int, dict]:
    """Per section id: the labour rate offered from the latest approved payroll of each
    division. A section with fewer than three people is offered the division's rate."""
    out: dict[int, dict] = {}
    runs = PayrollRun.objects.filter(status=PayrollRun.Status.APPROVED).order_by(
        "division", "-month"
    )
    seen = set()
    for run in runs.select_related("division"):
        if run.division_id in seen:
            continue
        seen.add(run.division_id)
        figures = labour.cost(run)
        for s in figures["sections"]:
            if s["section_id"] is None:
                continue
            own = s["employees"] >= MIN_PEOPLE and s["per_hour"] is not None
            per_hour = s["per_hour"] if own else figures["per_hour"]
            if per_hour is None:
                continue
            out[s["section_id"]] = {
                "per_hour": per_hour,
                "basis": "section" if own else "division",
                "run": run,
                "label": f"{run.division.code} {run.month:%b %Y}",
            }
    return out


# --- Keeping the rates ---------------------------------------------------------------------------


def _text(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def _day(values: dict) -> date:
    today = timezone.localdate()
    try:
        day = date.fromisoformat(_text(values.get("effective_from")) or today.isoformat())
    except ValueError:
        raise RateError("Give the date it applies from, e.g. 2026-12-01.") from None
    if day < today:
        raise RateError("A rate applies from today or later; earlier documents keep theirs.")
    return day


def _amount(value, label: str, places: int = 2, *, positive=False) -> Decimal:
    text = _text(value).replace(",", "")
    if not text:
        raise RateError(f"Give the {label}.")
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise RateError(f"The {label} is a number.") from None
    if not number.is_finite() or number < 0 or number >= MAX_RATE or (positive and not number):
        raise RateError(f"The {label} is {'more than' if positive else 'at least'} 0.")
    if number != number.quantize(Decimal(1).scaleb(-places)):
        raise RateError(f"The {label} has at most {places} decimal places.")
    return number


def _section(user: User, code) -> Section:
    found = Section.objects.filter(
        code=_text(code).upper(), division__in=division_scope(user)
    ).first()
    if found is None:
        raise RateError("Choose the section.")
    if not found.is_active:
        raise RateError(f"{found.code} is not active.")
    return found


@dataclass
class _Target:
    fields: dict
    label: str


def _target(user: User, kind: str, values: dict) -> _Target:
    if kind == K.LABOUR:
        section = _section(user, values.get("section"))
        return _Target({"section": section}, section.code)
    if kind == K.OVERHEAD:
        code = _text(values.get("machine")).upper()
        if code:
            machine = Machine.objects.filter(
                code=code, section__division__in=division_scope(user)
            ).first()
            if machine is None:
                raise RateError(f"There is no machine {code}.")
            if machine.status == Machine.Status.RETIRED:
                raise RateError(f"{machine.code} is retired.")
            return _Target({"section": machine.section, "machine": machine}, machine.code)
        section = _section(user, values.get("section"))
        return _Target({"section": section}, section.code)
    if kind == K.REGRIND:
        code = _text(values.get("material")).upper()
        material = Item.objects.filter(code=code).first()
        if material is None:
            raise RateError(f"There is no item {code or '(blank)'}.")
        if material.category != Item.Category.RAW_MATERIAL or _per_kg(material, ZERO) is None:
            raise RateError(f"{material.code} is not a raw material counted in kg or g.")
        return _Target({"material": material}, material.code)
    if kind == K.MOULD:
        code = _text(values.get("mould")).upper()
        mould = Mould.objects.filter(code=code, division__in=division_scope(user)).first()
        if mould is None:
            raise RateError(f"There is no mould {code or '(blank)'}.")
        if mould.owner != Mould.Owner.COMPANY:
            raise RateError(f"{mould.code} is a customer's mould: those are not amortised.")
        if mould.status == Mould.Status.RETIRED:
            raise RateError(f"{mould.code} is retired.")
        return _Target({"mould": mould}, mould.code)
    raise RateError("Choose labour, overhead, regrind or mould.")


def _save(user: User, kind: str, target: _Target, day: date, fields: dict) -> CostRate:
    key = {"kind": kind, "effective_from": day, "section": None, "machine": None}
    key |= {"material": None, "mould": None} | target.fields
    if day <= timezone.localdate() and CostRate.objects.filter(**key).exists():
        raise RateError(
            f"{target.label} already has a rate in force from {day}: enter the new one from a "
            "later date."
        )
    with audit_context("production_cost_rate", f"{kind} {target.label} from {day}"):
        with transaction.atomic():
            # A rate already entered for the same future date is replaced (not yet in force).
            rate, _ = CostRate.objects.update_or_create(
                **key,
                defaults=fields | {"created_by": user, "created_at": timezone.now()},
            )
            return rate


def add(user: User, values: dict) -> CostRate:
    """Enter a rate (labour, overhead and regrind in LKR; a mould's cost and life in shots)."""
    _check(user)
    kind = _text(values.get("kind")).lower()
    target = _target(user, kind, values)
    day = _day(values)
    reason = _text(values.get("reason"))[:200]
    if not reason:
        raise RateError("Give the reason for the rate.")
    fields: dict = {"reason": reason, "source": CostRate.Source.MANUAL, "payroll_run": None}
    if kind == K.MOULD:
        cost = _amount(values.get("mould_cost"), "mould cost")
        try:
            shots = int(_text(values.get("life_shots")).replace(",", "") or 0)
        except ValueError:
            raise RateError("The expected life is a whole number of shots.") from None
        if not 0 < shots < 10**12:
            raise RateError("Give the mould's expected life in shots.")
        fields |= {
            "mould_cost": cost,
            "life_shots": shots,
            "rate": (cost / shots).quantize(FOUR, ROUND_HALF_UP),
        }
    else:
        label = {K.LABOUR: "rate per hour", K.OVERHEAD: "rate per machine hour"}.get(
            kind, "credit per kg"
        )
        fields |= {"rate": _amount(values.get("rate"), label), "mould_cost": None}
        fields["life_shots"] = None
    return _save(user, kind, target, day, fields)


def accept(user: User, values: dict) -> list[CostRate]:
    """Accept the payroll's labour rate for the sections listed (all offered when none are)."""
    _check(user)
    day = _day(values)
    offered = suggestions()
    codes = [c for c in (_text(x).upper() for x in values.get("sections") or []) if c]
    sections = (
        [_section(user, c) for c in codes]
        if codes
        else list(
            Section.objects.filter(
                pk__in=offered, division__in=division_scope(user), is_active=True
            )
        )
    )
    if not sections:
        raise RateError("No approved payroll has a labour rate to accept yet.")
    saved = []
    with transaction.atomic():
        for section in sections:
            s = offered.get(section.pk)
            if s is None:
                raise RateError(f"No approved payroll has a labour rate for {section.code}.")
            reason = f"Payroll {s['label']}" + (
                " (division rate)" if s["basis"] == "division" else ""
            )
            fields = {
                "rate": s["per_hour"],
                "source": CostRate.Source.PAYROLL,
                "payroll_run": s["run"],
                "reason": reason,
                "mould_cost": None,
                "life_shots": None,
            }
            target = _Target({"section": section}, section.code)
            saved.append(_save(user, K.LABOUR, target, day, fields))
    return saved


def remove(user: User, rate: CostRate) -> None:
    """Take back a rate before its date; a rate in force stays (database)."""
    _check(user)
    if rate.effective_from <= timezone.localdate():
        raise RateError("This rate is in force: add a new one instead.")
    with audit_context("production_cost_rate_removed", f"{rate.kind} {rate.effective_from}"):
        with transaction.atomic():
            rate.delete()


# --- Reading -------------------------------------------------------------------------------------


def _money(value: Decimal | None) -> str:
    return "" if value is None else f"{value:.2f}"


def _target_label(r: CostRate) -> str:
    if r.machine_id:
        return r.machine.code
    if r.section_id:
        return r.section.code
    if r.material_id:
        return r.material.code
    return r.mould.code


def row(r: CostRate, today: date) -> dict:
    return {
        "id": r.pk,
        "kind": r.kind,
        "kind_label": r.get_kind_display(),
        "target": _target_label(r),
        "effective_from": r.effective_from,
        "rate": f"{r.rate:.4f}" if r.kind == K.MOULD else _money(r.rate),
        "mould_cost": _money(r.mould_cost),
        "life_shots": r.life_shots,
        "source": r.source,
        "reason": r.reason,
        "created_by": r.created_by.full_name if r.created_by_id else "",
        "in_force": r.effective_from <= today,
    }


def _next(rates: list[CostRate], today: date) -> CostRate | None:
    future = [r for r in rates if r.effective_from > today]
    return min(future, key=lambda r: r.effective_from) if future else None


def _now(rates: list[CostRate], today: date) -> CostRate | None:
    past = [r for r in rates if r.effective_from <= today]
    return max(past, key=lambda r: r.effective_from) if past else None


def _brief(r: CostRate | None) -> dict | None:
    if r is None:
        return None
    rate = f"{r.rate:.4f}" if r.kind == K.MOULD else _money(r.rate)
    return {"id": r.pk, "rate": rate, "effective_from": r.effective_from, "source": r.source}


def overview(user: User) -> dict:
    """Everything the cost rates page shows: per section, machine, material and company
    mould the rate in force and the next one, and the payroll's labour offers (keepers)."""
    today = timezone.localdate()
    keeper = can_keep(user)
    scope = division_scope(user)
    rates = list(
        CostRate.objects.select_related("section", "machine", "material", "mould", "created_by")
    )

    def of(kind: str, **target):
        return [
            r
            for r in rates
            if r.kind == kind and all(getattr(r, f"{k}_id") == v for k, v in target.items())
        ]

    offered = suggestions() if keeper else {}
    sections = Section.objects.filter(
        division__in=scope, is_active=True, division__code__in=["IM", "WS"]
    ).select_related("division")
    section_rows = []
    for s in sections.order_by("division__code", "code"):
        lab = of(kind=K.LABOUR, section=s.pk)
        ovh = of(kind=K.OVERHEAD, section=s.pk, machine=None)
        offer = offered.get(s.pk)
        section_rows.append(
            {
                "code": s.code,
                "name": s.name,
                "division": s.division.code,
                "labour": _brief(_now(lab, today)),
                "labour_next": _brief(_next(lab, today)),
                "overhead": _brief(_now(ovh, today)),
                "overhead_next": _brief(_next(ovh, today)),
                "payroll": (
                    {
                        "per_hour": _money(offer["per_hour"]),
                        "basis": offer["basis"],
                        "payroll": offer["label"],
                    }
                    if offer
                    else None
                ),
            }
        )
    machine_rows = []
    machines = Machine.objects.filter(section__in=sections).exclude(status=Machine.Status.RETIRED)
    for m in machines.select_related("section").order_by("code"):
        own = of(kind=K.OVERHEAD, machine=m.pk)
        machine_rows.append(
            {
                "code": m.code,
                "name": m.name,
                "section": m.section.code,
                "overhead": _brief(_now(own, today)),
                "overhead_next": _brief(_next(own, today)),
                "in_force": _money(overhead_on(m.section, m, today)),
            }
        )
    material_rows = []
    materials = Item.objects.filter(
        category=Item.Category.RAW_MATERIAL, unit__in=[Item.Unit.KG, Item.Unit.G], is_active=True
    )
    for item in materials.order_by("code"):
        set_rates = of(kind=K.REGRIND, material=item.pk)
        credit = regrind_on(item, today)
        material_rows.append(
            {
                "code": item.code,
                "name": item.name,
                "per_kg": _money(credit["per_kg"]),
                "basis": credit["basis"],
                "set": _brief(_now(set_rates, today)),
                "set_next": _brief(_next(set_rates, today)),
            }
        )
    mould_rows = []
    company = Mould.objects.filter(owner=Mould.Owner.COMPANY, division__in=scope).exclude(
        status=Mould.Status.RETIRED
    )
    for mould in company.order_by("code"):
        own = of(kind=K.MOULD, mould=mould.pk)
        now = _now(own, today)
        mould_rows.append(
            {
                "code": mould.code,
                "name": mould.name,
                "rate": _brief(now),
                "mould_cost": _money(now.mould_cost) if now else "",
                "life_shots": now.life_shots if now else None,
                "next": _brief(_next(own, today)),
            }
        )
    return {
        "sections": section_rows,
        "machines": machine_rows,
        "materials": material_rows,
        "moulds": mould_rows,
        "history": [row(r, today) for r in rates],
        "can_keep": keeper,
        "today": today,
    }
