"""Costing of quotation lines: machining (backlog P15-04) and moulding (P15-05), spec 5.1.
Internal only.

Machining, for one piece, in LKR (spec 5.5):

- Material: the stock weight (from its size and the material's density, plus the cutting
  allowance on the length, or a weight entered directly) × the material's price per kg.
- Machining: for each operation, minutes ÷ 60 × that machine's hourly rate.
- Setup: setup hours × the division's setup rate ÷ the quantity ordered.
- Subcontract: heat treatment, plating, transport and so on, per piece, or for the whole
  order and then shared over the quantity.
- Overhead: the overhead % on the direct cost above. Cost = direct cost + overhead.
- Margin: the margin % on the cost. Suggested price = cost + margin (spec 5.1).

Moulding, for one piece: material = (part weight + runner weight ÷ cavities) × resin price,
plus masterbatch as a % of that weight on top; machine = cycle time ÷ cavities × the press's
hourly rate; rejects add their % to material and machine; packing per piece or per carton;
then setup, subcontract, overhead and margin as for machining.

Tooling (the mould): charged once on its own line (a line marked as tooling), spread over a
quantity (cost ÷ quantity added to the price as it is, without overhead or margin), or owned
by the customer.

The margin of the price actually quoted is (quoted price in LKR − tooling share − cost) ÷
cost. Setup and per-order costs depend on the quantity, so the figures are worked out for
the line's quantity and for every quantity break.

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
    # Moulding (P15-05). `material` is then the resin.
    method: str | None = None  # machining or moulding; by default from the division
    masterbatch: Material | None = None
    masterbatch_pct: object = None
    part_weight_g: object = None
    runner_weight_g: object = None
    cavities: object = None
    machine: Machine | None = None
    cycle_time_s: object = None
    reject_pct: object = None
    packing_amount: object = None
    packing_per: str = "piece"
    pcs_per_carton: object = None
    # The mould: none, separate (its own line), amortised (spread over tooling_qty pieces)
    # or customer (owned by the customer).
    tooling: str = "none"
    tooling_cost: object = None
    tooling_qty: object = None


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
        if places == 0:
            raise SalesError(f"The {what} must be a whole number.")
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


def _moulding(costing: QuotationCosting) -> tuple[Decimal, ...]:
    """Material, machine, rejects and packing for one moulded piece, and the press hours per
    1,000 pieces. The runner is shared by the cavities; masterbatch is added on top of the
    resin as a % of its weight; rejects add their % to material and machine."""
    cavities = Decimal(costing.cavities or 1)
    shot_kg = ((costing.part_weight_g or 0) + (costing.runner_weight_g or 0) / cavities) / 1000
    material = _cent(
        shot_kg * (costing.material_rate or 0)
        + shot_kg * costing.masterbatch_pct / HUNDRED * (costing.masterbatch_rate or 0)
    )
    hours = (costing.cycle_time_s or 0) / cavities / 3600
    machine = _cent(hours * (costing.machine_rate or 0))
    rejects = _cent((material + machine) * costing.reject_pct / HUNDRED)
    packing = costing.packing_amount
    if costing.packing_per == QuotationCosting.PackingPer.CARTON:
        packing = _cent(packing / (costing.pcs_per_carton or 1))
    return material, machine, rejects, packing, (hours * 1000).quantize(CENT, ROUND_HALF_UP)


def figures(costing: QuotationCosting, quantity: Decimal, unit_price, exchange_rate) -> dict:
    """The build-up of one piece for an order of `quantity`, and the margin of the price
    quoted (in the quotation's currency) at that quantity.

    A mould spread over a quantity is added to the price as it is: overhead and margin are
    not charged on it, and the margin of the price quoted leaves it out."""
    extras = list(costing.extras.all())
    rejects = packing = Decimal("0.00")
    hours_per_1000 = None
    if costing.method == QuotationCosting.Method.MOULDING:
        material, machining, rejects, packing, hours_per_1000 = _moulding(costing)
    else:
        operations = list(costing.operations.all())
        material = _cent(costing.weight_kg * (costing.material_rate or 0))
        machining = _cent(sum((op.minutes * op.rate / 60 for op in operations), Decimal(0)))
    setup = _cent(costing.setup_hours * costing.setup_rate / quantity)
    subcontract = _cent(
        sum((e.amount / quantity if e.per_order else e.amount for e in extras), Decimal(0))
    )
    direct = material + machining + rejects + setup + packing + subcontract
    overhead = _cent(direct * costing.overhead_pct / HUNDRED)
    cost = direct + overhead
    margin = _cent(cost * costing.margin_pct / HUNDRED)
    tooling = Decimal("0.00")
    if costing.tooling == QuotationCosting.Tooling.AMORTISED and costing.tooling_qty:
        tooling = _cent(costing.tooling_cost / costing.tooling_qty)
    suggested = cost + margin + tooling
    quoted_lkr = _cent(Decimal(unit_price) * exchange_rate)
    achieved = None
    if cost > 0:
        achieved = ((quoted_lkr - tooling - cost) / cost * HUNDRED).quantize(CENT, ROUND_HALF_UP)
    return {
        "quantity": quantity,
        "material": material,
        "machining": machining,
        "hours_per_1000": hours_per_1000,
        "rejects": rejects,
        "setup": setup,
        "packing": packing,
        "subcontract": subcontract,
        "direct_cost": direct,
        "overhead": overhead,
        "cost": cost,
        "margin": margin,
        "tooling": tooling,
        "suggested_price_lkr": suggested,
        "suggested_price": _cent(suggested / exchange_rate),
        "quoted_price": Decimal(unit_price),
        "quoted_price_lkr": quoted_lkr,
        "quoted_margin_pct": achieved,
        "below_cost": cost > 0 and quoted_lkr < cost + tooling,
    }


def results(costing: QuotationCosting, line: QuotationLine, exchange_rate) -> list[dict]:
    """The figures for the line's quantity, then for each quantity break, at the prices
    after the quotation's discount."""
    keep = 1 - line.quotation.discount_pct / 100

    def after(price):
        return (Decimal(price) * keep).quantize(CENT, ROUND_HALF_UP)

    rows = [figures(costing, line.quantity, after(line.unit_price), exchange_rate)]
    rows += [
        figures(costing, b.quantity, after(b.unit_price), exchange_rate) for b in line.breaks.all()
    ]
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


MACHINING_CLEARED = {
    "size_a_mm": None,
    "size_b_mm": None,
    "length_mm": None,
    "cutting_allowance_mm": Decimal("0"),
    "entered_weight_kg": None,
    "weight_kg": Decimal("0"),
}
MOULDING_CLEARED = {
    "masterbatch": None,
    "masterbatch_rate": None,
    "masterbatch_pct": Decimal("0"),
    "part_weight_g": None,
    "runner_weight_g": None,
    "cavities": None,
    "machine": None,
    "machine_rate": None,
    "cycle_time_s": None,
    "reject_pct": Decimal("0"),
}


def default_method(quotation: Quotation) -> str:
    """Moulding for a division with moulding sections (IM), machining otherwise (WS)."""
    if quotation.division.sections.filter(section_type="moulding").exists():
        return QuotationCosting.Method.MOULDING
    return QuotationCosting.Method.MACHINING


def _priced(material: Material, on, what: str) -> Decimal:
    if not material.is_active:
        raise SalesError(f"{what.capitalize()} {material.code} is inactive.")
    rate = costing_rates.material_rate_on(material, on)
    if rate is None:
        raise SalesError(
            f"{what.capitalize()} {material.code} has no price per kg on {on:%d/%m/%Y}. "
            "Ask the Accountant to enter one."
        )
    return rate


def _moulding_values(quotation: Quotation, data: CostingInput) -> dict:
    """Resin and masterbatch, the part and runner weights, cavities, the press and its cycle
    time, and the expected rejects."""
    on = quotation.quote_date
    resin = data.material
    if resin is None:
        raise SalesError("Choose the resin.")
    if resin.kind == Material.Kind.MASTERBATCH:
        raise SalesError(f"{resin.code} is a masterbatch: choose the resin.")
    values = {
        "material": resin,
        "material_rate": _priced(resin, on, "resin"),
        "density": resin.density,
        "form": resin.form,
        **MACHINING_CLEARED,
    }
    part = _number(data.part_weight_g, "part weight", 3, positive=True)
    if part is None:
        raise SalesError("Enter the part weight in grams.")
    runner = _number(data.runner_weight_g, "runner weight", 3)
    cavities = _number(data.cavities, "number of cavities", 0, positive=True, maximum=Decimal(512))
    if cavities is None:
        raise SalesError("Enter the number of cavities of the mould.")
    pct = _number(data.masterbatch_pct, "masterbatch %", 2, maximum=Decimal("100"))
    masterbatch = data.masterbatch
    if masterbatch is not None:
        if masterbatch.kind != Material.Kind.MASTERBATCH:
            raise SalesError(f"{masterbatch.code} is not a masterbatch.")
        if not pct:
            raise SalesError("Enter the masterbatch %, for example 2.")
        mb_rate = _priced(masterbatch, on, "masterbatch")
    elif pct:
        raise SalesError("Choose the masterbatch for the masterbatch %.")
    else:
        mb_rate = None
    machine = data.machine
    if not isinstance(machine, Machine):
        raise SalesError("Choose the moulding machine.")
    if machine.section.division_id != quotation.division_id or not machine.is_active:
        raise SalesError(
            f"Machine {machine.code} is not a working machine of {quotation.division.code}."
        )
    machine_rate = masters.rate_on(machine, on)
    if machine_rate is None:
        raise SalesError(f"Machine {machine.code} has no hourly rate on {on:%d/%m/%Y}.")
    cycle = _number(data.cycle_time_s, "cycle time", 2, positive=True, maximum=Decimal("99999"))
    if cycle is None:
        raise SalesError("Enter the cycle time in seconds.")
    reject = _number(data.reject_pct, "reject %", 2) or Decimal("0")
    if reject >= 100:
        raise SalesError("The reject % must be below 100.")
    return values | {
        "masterbatch": masterbatch,
        "masterbatch_rate": mb_rate,
        "masterbatch_pct": pct or Decimal("0"),
        "part_weight_g": part,
        "runner_weight_g": runner,
        "cavities": int(cavities),
        "machine": machine,
        "machine_rate": machine_rate,
        "cycle_time_s": cycle,
        "reject_pct": reject,
    }


def _packing_and_tooling(data: CostingInput) -> dict:
    packing = _number(data.packing_amount, "packing cost", 2) or Decimal("0")
    per = data.packing_per or QuotationCosting.PackingPer.PIECE
    if per not in QuotationCosting.PackingPer.values:
        raise SalesError("Packing is per piece or per carton.")
    per_carton = None
    if per == QuotationCosting.PackingPer.CARTON:
        per_carton = _number(data.pcs_per_carton, "pieces per carton", 0, positive=True)
        if per_carton is None:
            raise SalesError("Enter how many pieces go in a carton.")
        per_carton = int(per_carton)
    tooling = data.tooling or QuotationCosting.Tooling.NONE
    if tooling not in QuotationCosting.Tooling.values:
        raise SalesError("Choose how the tooling is charged.")
    cost = _number(data.tooling_cost, "tooling cost", 2) or Decimal("0")
    spread = None
    if tooling == QuotationCosting.Tooling.AMORTISED:
        spread = _number(data.tooling_qty, "quantity to spread the tooling over", 3, positive=True)
        if not cost or spread is None:
            raise SalesError(
                "To spread the tooling, enter its cost and the number of pieces to spread it over."
            )
    elif tooling == QuotationCosting.Tooling.NONE:
        cost = Decimal("0")
    return {
        "packing_amount": packing,
        "packing_per": per,
        "pcs_per_carton": per_carton,
        "tooling": tooling,
        "tooling_cost": cost,
        "tooling_qty": spread,
    }


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
        method = data.method or default_method(quotation)
        if method not in QuotationCosting.Method.values:
            raise SalesError("Choose machining or moulding costing.")
        if method == QuotationCosting.Method.MOULDING:
            values = _moulding_values(quotation, data)
            operations = []
        else:
            values = _material(quotation, data) | MOULDING_CLEARED
            operations = _operations(quotation, data)
        values |= _packing_and_tooling(data)
        extras = _extras(data)
        pct = Decimal("999.99")
        overhead = _number(data.overhead_pct, "overhead %", 2, maximum=pct)
        margin = _number(data.margin_pct, "margin %", 2, maximum=pct)
        values |= {
            "method": method,
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
        for material in (costing.material, costing.masterbatch):
            if material is not None:
                masters.mark_used(material)
        for machine in {op["machine"] for op in operations} | {costing.machine} - {None}:
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


def _ref(record) -> dict | None:
    return None if record is None else {"id": record.id, "code": record.code, "name": record.name}


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
        "method": costing.method,
        "masterbatch": _ref(costing.masterbatch),
        "masterbatch_rate": _text(costing.masterbatch_rate),
        "masterbatch_pct": str(costing.masterbatch_pct),
        "part_weight_g": _text(costing.part_weight_g),
        "runner_weight_g": _text(costing.runner_weight_g),
        "cavities": costing.cavities,
        "machine": _ref(costing.machine),
        "machine_rate": _text(costing.machine_rate),
        "cycle_time_s": _text(costing.cycle_time_s),
        "reject_pct": str(costing.reject_pct),
        "packing_amount": str(costing.packing_amount),
        "packing_per": costing.packing_per,
        "pcs_per_carton": costing.pcs_per_carton,
        "tooling": costing.tooling,
        "tooling_cost": str(costing.tooling_cost),
        "tooling_qty": _text(costing.tooling_qty),
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
        "default_method": default_method(quotation),
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
                        "kind": material.kind,
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
        "costing__material",
        "costing__masterbatch",
        "costing__machine",
        "costing__updated_by",
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
                "is_tooling": line.is_tooling,
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
