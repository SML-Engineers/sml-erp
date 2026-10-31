"""Machining costing of quotation lines (backlog P15-04, spec 5.1). Internal only.

For one piece, in LKR (spec 5.5):

- Material: the stock weight (from its size and the material's density, plus the cutting
  allowance on the length, or a weight entered directly) × the material's price per kg.
- Machining: for each operation, minutes ÷ 60 × that machine's hourly rate.
- Setup: setup hours × the division's setup rate ÷ the quantity ordered.
- Subcontract: heat treatment, plating, transport and so on, per piece, or for the whole
  order and then shared over the quantity.
- Overhead: the overhead % on the direct cost above. Cost = direct cost + overhead.
- Margin: the margin % on the cost. Suggested price = cost + margin (spec 5.1).

The margin of the price actually quoted is (quoted price in LKR − cost) ÷ cost. Setup and
per-order costs depend on the quantity, so the figures are worked out for the line's
quantity and for every quantity break.

Rates come from the tables in force on the quotation's date and are copied onto the costing
when it is saved, so a later change of rate never alters it (rule 11). Money is Decimal,
each element rounded half-up to the cent (rule 1).

Who sees the costing (owner's decisions, 31 Oct 2026): the quotation's creator, the Sales
Manager and the Director (Sales: Approve), and the Accountant (Accounting: Enter or more);
not other Sales Executives, and not the Auditor. Only the creator changes it, while the
quotation is a draft. It is never part of anything the customer receives.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.masters import costing_rates
from apps.masters import services as masters
from apps.masters.models import Machine, Material

from .models import (
    Quotation,
    QuotationCosting,
    QuotationCostingExtra,
    QuotationCostingOperation,
    QuotationLine,
)
from .services import SalesError, can_edit, visible

CENT = Decimal("0.01")
KG = Decimal("0.0001")
HUNDRED = Decimal("100")
PI = Decimal("3.14159265358979323846")
HEX_AREA = Decimal("0.86602540378443864676")  # area of a hexagon = 0.866 × across flats²
MAX_OPERATIONS = 30
MAX_EXTRAS = 20
FORMS_BY_SIZE = {
    Material.Form.ROUND_BAR: ("diameter",),
    Material.Form.HEX_BAR: ("size across flats",),
    Material.Form.FLAT_BAR: ("width", "thickness"),
    Material.Form.PLATE: ("width", "thickness"),
    Material.Form.TUBE: ("outside diameter", "inside diameter"),
}


@dataclass
class OperationInput:
    machine: Machine | None
    minutes: object
    description: str = ""


@dataclass
class ExtraInput:
    description: str
    amount: object
    per_order: bool = False


@dataclass
class CostingInput:
    material: Material | None = None
    size_a_mm: object = None
    size_b_mm: object = None
    length_mm: object = None
    cutting_allowance_mm: object = None
    weight_kg: object = None
    setup_hours: object = None
    overhead_pct: object = None
    margin_pct: object = None
    notes: str = ""
    operations: list[OperationInput] = field(default_factory=list)
    extras: list[ExtraInput] = field(default_factory=list)


# --- Who may see and change it ----------------------------------------------------------


def can_see(user: User, quotation: Quotation) -> bool:
    if not visible(user).filter(pk=quotation.pk).exists():
        return False
    access = effective_access(user)
    return (
        quotation.created_by_id == user.pk
        or access.has("sales", "approve")
        # The Accountant (Accounting: Manage); not the Auditor, who only views (owner, 31
        # Oct 2026).
        or access.has("accounting", "enter")
    )


# --- Working it out ---------------------------------------------------------------------


def _number(value, what: str, places: int, *, positive=False, maximum=Decimal("1e12")):
    """An exact number from text (rule 1); None when left empty."""
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, float):
        raise SalesError(f"The {what} must be an exact number.")
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except ArithmeticError:
        raise SalesError(f"The {what} must be a number.") from None
    step = Decimal(1).scaleb(-places)
    if not number.is_finite():
        raise SalesError(f"The {what} must be a number.")
    if number != number.quantize(step):
        raise SalesError(f"The {what} can have at most {places} decimal places.")
    if number < 0 or (positive and number == 0):
        raise SalesError(
            f"The {what} must be more than 0." if positive else f"The {what} cannot be negative."
        )
    if number > maximum:
        raise SalesError(f"The {what} is too large.")
    return number.quantize(step)


def stock_weight(form: str, density: Decimal, a, b, length, allowance) -> Decimal:
    """Weight in kg of one piece of stock, from its size in mm and the density in g/cm³.
    The cutting allowance is added to the length."""
    if form == Material.Form.ROUND_BAR:
        area = PI / 4 * a * a
    elif form == Material.Form.HEX_BAR:
        area = HEX_AREA * a * a
    elif form in (Material.Form.FLAT_BAR, Material.Form.PLATE):
        area = a * b
    elif form == Material.Form.TUBE:
        area = PI / 4 * (a * a - b * b)
    else:  # pragma: no cover - only forms in FORMS_BY_SIZE are worked out
        raise SalesError("Enter the weight per piece for this material.")
    # mm³ × g/cm³ ÷ 1,000 = g; ÷ 1,000 again = kg.
    return (area * (length + allowance) * density / Decimal(1_000_000)).quantize(KG, ROUND_HALF_UP)


def _cent(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


def figures(costing: QuotationCosting, quantity: Decimal, unit_price, exchange_rate) -> dict:
    """The build-up of one piece for an order of `quantity`, and the margin of the price
    quoted (in the quotation's currency) at that quantity."""
    operations = list(costing.operations.all())
    extras = list(costing.extras.all())
    material = _cent(costing.weight_kg * (costing.material_rate or 0))
    machining = _cent(sum((op.minutes * op.rate / 60 for op in operations), Decimal(0)))
    setup = _cent(costing.setup_hours * costing.setup_rate / quantity)
    subcontract = _cent(
        sum((e.amount / quantity if e.per_order else e.amount for e in extras), Decimal(0))
    )
    direct = material + machining + setup + subcontract
    overhead = _cent(direct * costing.overhead_pct / HUNDRED)
    cost = direct + overhead
    margin = _cent(cost * costing.margin_pct / HUNDRED)
    suggested = cost + margin
    quoted_lkr = _cent(Decimal(unit_price) * exchange_rate)
    achieved = None
    if cost > 0:
        achieved = ((quoted_lkr - cost) / cost * HUNDRED).quantize(CENT, ROUND_HALF_UP)
    return {
        "quantity": quantity,
        "material": material,
        "machining": machining,
        "setup": setup,
        "subcontract": subcontract,
        "direct_cost": direct,
        "overhead": overhead,
        "cost": cost,
        "margin": margin,
        "suggested_price_lkr": suggested,
        "suggested_price": _cent(suggested / exchange_rate),
        "quoted_price": Decimal(unit_price),
        "quoted_price_lkr": quoted_lkr,
        "quoted_margin_pct": achieved,
        "below_cost": cost > 0 and quoted_lkr < cost,
    }


def results(costing: QuotationCosting, line: QuotationLine, exchange_rate) -> list[dict]:
    """The figures for the line's quantity, then for each quantity break."""
    rows = [figures(costing, line.quantity, line.unit_price, exchange_rate)]
    rows += [figures(costing, b.quantity, b.unit_price, exchange_rate) for b in line.breaks.all()]
    return rows


# --- Saving -----------------------------------------------------------------------------


def _material(quotation: Quotation, data: CostingInput) -> dict:
    on = quotation.quote_date
    sizes = {
        "size_a_mm": _number(data.size_a_mm, "first size", 2, positive=True),
        "size_b_mm": _number(data.size_b_mm, "second size", 2, positive=True),
        "length_mm": _number(data.length_mm, "length", 2, positive=True),
        "cutting_allowance_mm": _number(data.cutting_allowance_mm, "cutting allowance", 2)
        or Decimal("0"),
    }
    entered = _number(data.weight_kg, "weight per piece", 4, positive=True)
    material = data.material
    if material is None:  # the customer supplies the material, or there is none
        return {
            "material": None,
            "material_rate": None,
            "density": None,
            "form": "",
            "entered_weight_kg": None,
            "weight_kg": Decimal("0"),
            **{k: None for k in ("size_a_mm", "size_b_mm", "length_mm")},
            "cutting_allowance_mm": Decimal("0"),
        }
    if not material.is_active:
        raise SalesError(f"Material {material.code} is inactive.")
    rate = costing_rates.material_rate_on(material, on)
    if rate is None:
        raise SalesError(
            f"Material {material.code} has no price per kg on {on:%d/%m/%Y}. "
            "Ask the Accountant to enter one."
        )
    weight = entered
    if weight is None:
        needed = FORMS_BY_SIZE.get(material.form)
        if needed is None or material.density is None:
            raise SalesError(
                f"Enter the weight per piece: the size of material {material.code} "
                "cannot be turned into a weight (its form or density is not set)."
            )
        for key, what in zip(("size_a_mm", "size_b_mm"), needed, strict=False):
            if sizes[key] is None:
                raise SalesError(f"Enter the {what} of the stock, or the weight per piece.")
        if sizes["length_mm"] is None:
            raise SalesError("Enter the length of stock per piece, or the weight per piece.")
        if material.form == Material.Form.TUBE and sizes["size_b_mm"] >= sizes["size_a_mm"]:
            raise SalesError("The inside diameter must be smaller than the outside diameter.")
        weight = stock_weight(
            material.form,
            material.density,
            sizes["size_a_mm"],
            sizes["size_b_mm"],
            sizes["length_mm"],
            sizes["cutting_allowance_mm"],
        )
        if weight == 0:
            raise SalesError("The stock is too small to weigh. Enter the weight per piece.")
    return {
        "material": material,
        "material_rate": rate,
        "density": material.density,
        "form": material.form,
        "entered_weight_kg": entered,
        "weight_kg": weight,
        **sizes,
    }


def _operations(quotation: Quotation, data: CostingInput) -> list[dict]:
    if len(data.operations) > MAX_OPERATIONS:
        raise SalesError(f"At most {MAX_OPERATIONS} operations.")
    rows = []
    for n, op in enumerate(data.operations, start=1):
        where = f"Operation {n}: "
        machine = op.machine
        if not isinstance(machine, Machine):
            raise SalesError(where + "choose the machine.")
        if machine.section.division_id != quotation.division_id or not machine.is_active:
            raise SalesError(
                where + f"machine {machine.code} is not a working machine of "
                f"{quotation.division.code}."
            )
        try:
            minutes = _number(op.minutes, "minutes per piece", 3, positive=True)
        except SalesError as error:
            raise SalesError(where + str(error)) from None
        if minutes is None:
            raise SalesError(where + "enter the minutes per piece.")
        rate = masters.rate_on(machine, quotation.quote_date)
        if rate is None:
            raise SalesError(
                where + f"machine {machine.code} has no hourly rate on "
                f"{quotation.quote_date:%d/%m/%Y}."
            )
        rows.append(
            {
                "seq": n,
                "machine": machine,
                "minutes": minutes,
                "rate": rate,
                "description": (op.description or "").strip()[:100],
            }
        )
    return rows


def _extras(data: CostingInput) -> list[dict]:
    if len(data.extras) > MAX_EXTRAS:
        raise SalesError(f"At most {MAX_EXTRAS} subcontract costs.")
    rows = []
    for n, extra in enumerate(data.extras, start=1):
        where = f"Subcontract cost {n}: "
        description = (extra.description or "").strip()[:100]
        if not description:
            raise SalesError(where + "say what it is, for example heat treatment.")
        try:
            amount = _number(extra.amount, "amount", 2)
        except SalesError as error:
            raise SalesError(where + str(error)) from None
        if amount is None:
            raise SalesError(where + "enter the amount.")
        rows.append(
            {
                "seq": n,
                "description": description,
                "amount": amount,
                "per_order": bool(extra.per_order),
            }
        )
    return rows


def save(user: User, quotation: Quotation, line_no: int, data: CostingInput) -> QuotationCosting:
    """Record or change the costing of one line of a draft quotation."""
    with audit_context("quotation_costing_saved"), transaction.atomic():
        quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
        if not can_edit(user, quotation):
            raise SalesError(
                "Only the person who made the quotation changes its costing, while it is a draft."
            )
        line = quotation.lines.filter(line_no=line_no).first()
        if line is None:
            raise SalesError(f"The quotation has no line {line_no}.")
        rates = costing_rates.costing_rate_on(quotation.division, quotation.quote_date)
        if rates is None:
            raise SalesError(
                f"There are no costing rates for {quotation.division.code} on "
                f"{quotation.quote_date:%d/%m/%Y}. Ask the Accountant to enter them."
            )
        values = _material(quotation, data)
        operations = _operations(quotation, data)
        extras = _extras(data)
        pct = Decimal("999.99")
        overhead = _number(data.overhead_pct, "overhead %", 2, maximum=pct)
        margin = _number(data.margin_pct, "margin %", 2, maximum=pct)
        values |= {
            "method": QuotationCosting.Method.MACHINING,
            "rates_date": quotation.quote_date,
            "setup_hours": _number(data.setup_hours, "setup hours", 2, maximum=Decimal("99999"))
            or Decimal("0"),
            "setup_rate": rates.setup_rate,
            "overhead_pct": rates.overhead_pct if overhead is None else overhead,
            "margin_pct": rates.margin_pct if margin is None else margin,
            "notes": (data.notes or "").strip()[:2000],
            "updated_by": user,
            "updated_at": timezone.now(),
        }
        costing, _created = QuotationCosting.objects.update_or_create(line=line, defaults=values)
        costing.operations.all().delete()
        costing.extras.all().delete()
        QuotationCostingOperation.objects.bulk_create(
            QuotationCostingOperation(costing=costing, **op) for op in operations
        )
        QuotationCostingExtra.objects.bulk_create(
            QuotationCostingExtra(costing=costing, **extra) for extra in extras
        )
        # From now on their codes are fixed (rule 9).
        if costing.material is not None:
            masters.mark_used(costing.material)
        for machine in {op["machine"] for op in operations}:
            masters.mark_used(machine)
        return costing


def remove(user: User, quotation: Quotation, line_no: int) -> None:
    with audit_context("quotation_costing_removed"), transaction.atomic():
        quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
        if not can_edit(user, quotation):
            raise SalesError(
                "Only the person who made the quotation changes its costing, while it is a draft."
            )
        QuotationCosting.objects.filter(line__quotation=quotation, line__line_no=line_no).delete()


# --- What the costing page shows --------------------------------------------------------


def _text(value) -> str | None:
    return None if value is None else str(value)


def _costing_body(costing: QuotationCosting) -> dict:
    return {
        "rates_date": costing.rates_date,
        "material": None
        if costing.material is None
        else {
            "id": costing.material_id,
            "code": costing.material.code,
            "name": costing.material.name,
        },
        "material_rate": _text(costing.material_rate),
        "density": _text(costing.density),
        "form": costing.form,
        "size_a_mm": _text(costing.size_a_mm),
        "size_b_mm": _text(costing.size_b_mm),
        "length_mm": _text(costing.length_mm),
        "cutting_allowance_mm": str(costing.cutting_allowance_mm),
        "entered_weight_kg": _text(costing.entered_weight_kg),
        "weight_kg": str(costing.weight_kg),
        "setup_hours": str(costing.setup_hours),
        "setup_rate": str(costing.setup_rate),
        "overhead_pct": str(costing.overhead_pct),
        "margin_pct": str(costing.margin_pct),
        "notes": costing.notes,
        "operations": [
            {
                "machine": {"id": op.machine_id, "code": op.machine.code, "name": op.machine.name},
                "description": op.description,
                "minutes": str(op.minutes),
                "rate": str(op.rate),
            }
            for op in costing.operations.select_related("machine")
        ],
        "extras": [
            {"description": e.description, "amount": str(e.amount), "per_order": e.per_order}
            for e in costing.extras.all()
        ],
        "updated_by": costing.updated_by.full_name,
        "updated_at": costing.updated_at,
    }


def page(user: User, quotation: Quotation) -> dict:
    """Everything the costing screen needs: each line's costing and results, and, for the
    creator of a draft, the rates in force on the quotation's date to choose from."""
    on = quotation.quote_date
    editable = can_edit(user, quotation)
    body = {
        "quotation_id": quotation.id,
        "number": quotation.number,
        "revision": quotation.revision,
        "division": quotation.division.code,
        "currency": quotation.currency.code,
        "exchange_rate": str(quotation.exchange_rate),
        "quote_date": on,
        "can_edit": editable,
        "defaults": None,
        "materials": [],
        "machines": [],
        "lines": [],
    }
    rates = costing_rates.costing_rate_on(quotation.division, on)
    if rates is not None:
        body["defaults"] = {
            "overhead_pct": str(rates.overhead_pct),
            "margin_pct": str(rates.margin_pct),
            "setup_rate": str(rates.setup_rate),
        }
    if editable:
        for material in Material.objects.filter(is_active=True):
            rate = costing_rates.material_rate_on(material, on)
            if rate is not None:
                body["materials"].append(
                    {
                        "id": material.id,
                        "code": material.code,
                        "name": material.name,
                        "form": material.form,
                        "density": _text(material.density),
                        "rate": str(rate),
                    }
                )
        machines = Machine.objects.filter(section__division=quotation.division).exclude(
            status=Machine.Status.RETIRED
        )
        for machine in machines:
            rate = masters.rate_on(machine, on)
            if rate is not None:
                body["machines"].append(
                    {
                        "id": machine.id,
                        "code": machine.code,
                        "name": machine.name,
                        "rate": str(rate),
                    }
                )
    lines = quotation.lines.prefetch_related("breaks").select_related(
        "costing__material", "costing__updated_by"
    )
    for line in lines:
        costing = getattr(line, "costing", None)
        body["lines"].append(
            {
                "line_no": line.line_no,
                "description": line.description,
                "drawing_no": line.drawing_no,
                "quantity": str(line.quantity),
                "unit": line.unit,
                "unit_price": str(line.unit_price),
                "costing": None if costing is None else _costing_body(costing),
                "results": None
                if costing is None
                else [
                    {
                        key: _text(value) if key != "below_cost" else value
                        for key, value in row.items()
                    }
                    for row in results(costing, line, quotation.exchange_rate)
                ],
            }
        )
    return body
