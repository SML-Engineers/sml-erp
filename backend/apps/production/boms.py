"""Bills of materials (backlog P3-04; spec 7.1B).

- A BOM lists what makes its **base quantity** of an item (usually 1): raw material,
  masterbatch and additives (as a % of the resin), bought-out parts, sub-assemblies (which
  have their own BOMs: multi-level), subcontract services and packing. Each line has its
  quantity in the component's unit, a scrap allowance %, the routing operation it is used at,
  manual issue or **backflush** (deducted when output is approved), and whether the customer
  supplies it.
- **Machining** lines can hold the stock (size, bar length) and how each piece is cut (cut
  length, facing and saw-cut allowance, mm): the quantity per piece follows in the
  component's unit (kg from its standard kg per m, m or mm of bar, or whole bars), with
  pieces per bar and the blank's weight shown.
- **Moulding** BOMs take the mould: the parts it makes (outputs) with their cavities and part
  weight; resin per shot = (parts x cavities + runner) x (1 + reject allowance %), per piece
  for a single part; a **family mould**'s BOM is one shot with each part as an output.
  Masterbatch follows as a % of the resin; the maximum regrind % is shown.
- **Revisions** (as routings): the Planner drafts and sends, the **Production Manager
  approves** (approval engine "bom"; never the preparer) or sends back; the approved
  revision replaces the BOM in force. Approved and obsolete BOMs never change and are never
  deleted (database). A BOM never contains its own item at any level.
- **Standard cost** rolled up through all levels: materials at their stock average cost
  (customer-supplied at nil), sub-assemblies at their own BOM's cost, subcontract services
  at their cost, and the routing's run time at the machine hourly rates (a section's average
  when no machine is named), plus labour at the section's labour rate, overhead per machine
  hour and, for a company mould, its amortisation per shot (P3-05 cost rates). Missing costs
  are listed, never guessed.
- Copy (a new revision or another item), compare two revisions, where-used, Excel.
"""

import io
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils.exceptions import InvalidFileException

from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalLog, ApprovalState, Division, User
from apps.inventory.issues import cost_of
from apps.inventory.models import Item
from apps.masters.models import Machine, Supplier
from apps.masters.services import rate_on

from . import rates, routings
from .models import Bom, BomLine, BomOutput, Mould

DOC = "bom"
MAX_BYTES = 5 * 1024 * 1024
St = Bom.Status
T = BomLine.Type
ZERO = Decimal("0")
CENT = Decimal("0.01")
QTY = Decimal("0.000001")
MAX_LEVELS = 10


class BomError(Exception):
    pass


class ImportRefused(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("Nothing was imported.")
        self.errors = errors


def can_prepare(user: User) -> bool:
    return effective_access(user).has("production_planning", "enter")


def _check(user: User) -> None:
    if not can_prepare(user):
        raise BomError("Only the Production Planner prepares bills of materials.")


def _text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value if value is not None else "").split())


def _decimal(value, label: str, places: int, *, required=False) -> Decimal | None:
    text = _text(value).replace(",", "").rstrip("%").strip()
    if not text:
        if required:
            raise BomError(f"Give the {label}.")
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise BomError(f"The {label} is a number.") from None
    if not number.is_finite() or number < 0:
        raise BomError(f"The {label} is 0 or more.")
    if number != number.quantize(Decimal(1).scaleb(-places)):
        raise BomError(f"The {label} has at most {places} decimal places.")
    return number


def _yes(value) -> bool:
    return _text(value).lower() in ("true", "1", "yes", "y")


def _item(code) -> Item:
    code = _text(code).upper()
    item = Item.objects.filter(code=code).first()
    if item is None:
        raise BomError(f"There is no item {code or '(blank)'}.")
    return item


# --- Calculators ---------------------------------------------------------------------------------


def machining(
    component: Item, *, bar_length_mm, cut_length_mm, facing_mm=None, saw_mm=None
) -> dict:
    """How a piece is cut from bar or plate stock, and the stock used per piece in the
    component's unit."""
    cut = cut_length_mm or ZERO
    if cut <= 0:
        raise BomError("Give the cut length (mm).")
    facing, saw = facing_mm or ZERO, saw_mm or ZERO
    per_piece = cut + facing + saw
    pieces = int(bar_length_mm // per_piece) if bar_length_mm else None
    if bar_length_mm and not pieces:
        raise BomError("The piece is longer than the bar.")
    kg_per_m = component.standard_kg_per_m
    blank_kg = (kg_per_m * (cut + facing) / 1000).quantize(Decimal("0.0001")) if kg_per_m else None
    unit = component.unit
    if unit == Item.Unit.KG:
        if not kg_per_m:
            raise BomError(
                f"{component.code} has no standard kg per metre: set it on the item, or give "
                "the quantity."
            )
        quantity = kg_per_m * per_piece / 1000
    elif unit == Item.Unit.M:
        quantity = per_piece / 1000
    elif unit == Item.Unit.MM:
        quantity = per_piece
    elif unit == Item.Unit.PCS and pieces:
        quantity = Decimal(1) / pieces
    else:
        raise BomError(f"Give the quantity: {component.code} is counted in {unit}.")
    return {
        "length_per_piece_mm": f"{per_piece.normalize():f}",
        "pieces_per_bar": pieces,
        "blank_weight_kg": f"{blank_kg}" if blank_kg is not None else "",
        "quantity": quantity.quantize(QTY, ROUND_HALF_UP),
        "unit": unit,
    }


def moulding(mould: Mould | None, outputs: list[dict], reject_pct: Decimal) -> dict:
    """Resin per shot and per piece from the parts, cavities and runner."""
    if not outputs:
        raise BomError("Give the part(s) the mould makes with their cavities and weight.")
    runner = mould.runner_weight_g if mould else ZERO
    parts = sum((o["part_weight_g"] * o["cavities"] for o in outputs), ZERO)
    shot = (parts + runner) * (1 + reject_pct / 100)
    pieces = sum(o["cavities"] for o in outputs)
    return {
        "shot_g": shot.quantize(Decimal("0.01"), ROUND_HALF_UP),
        "per_piece_g": (shot / pieces).quantize(Decimal("0.0001"), ROUND_HALF_UP),
        "pieces_per_shot": pieces,
        "family": len(outputs) > 1,
    }


def _resin_quantity(calc: dict, unit: str, base: Decimal) -> Decimal:
    grams = calc["shot_g"] if calc["family"] else calc["per_piece_g"]
    grams *= base
    if unit == Item.Unit.KG:
        return (grams / 1000).quantize(QTY, ROUND_HALF_UP)
    if unit == Item.Unit.G:
        return grams.quantize(QTY, ROUND_HALF_UP)
    raise BomError("Resin is counted in kg or g to be worked out from the mould.")


# --- Values --------------------------------------------------------------------------------------


def _outputs(item: Item, mould: Mould | None, rows) -> list[dict]:
    if not rows and mould is not None:
        rows = [
            {"item": p.item.code, "cavities": p.cavities}
            for p in mould.parts.select_related("item")
        ]
    out, seen = [], set()
    for row in rows or []:
        part = _item(row.get("item"))
        if part.pk in seen:
            raise BomError(f"Output {part.code} is listed twice.")
        seen.add(part.pk)
        try:
            cavities = int(_text(row.get("cavities")) or 0)
        except ValueError:
            raise BomError(f"{part.code}: the cavities are a whole number.") from None
        if cavities < 1:
            raise BomError(f"{part.code}: give the cavities.")
        weight = _decimal(row.get("part_weight_g"), f"part weight of {part.code} (g)", 2)
        if not weight:
            raise BomError(f"Give the part weight of {part.code} (g).")
        out.append({"item": part, "cavities": cavities, "part_weight_g": weight})
    if out and item.pk not in seen:
        raise BomError(f"{item.code} is one of the parts the mould makes; list it as an output.")
    return out


def _header(user: User, values: dict, current: Bom | None) -> dict:
    out: dict = {}
    if current is None:
        out["item"] = _item(values.get("item"))
    item = out.get("item") or current.item
    if current is None or "kind" in values:
        kind = _text(values.get("kind") or "general").lower()
        if kind not in Bom.Kind.values:
            raise BomError("The kind is general, machining or moulding.")
        out["kind"] = kind
    kind = out.get("kind") or current.kind
    if current is None or "division" in values:
        default = "IM" if kind == Bom.Kind.MOULDING else "WS"
        code = _text(values.get("division") or default).upper()
        division = Division.objects.filter(code=code, pk__in=division_scope(user)).first()
        if division is None:
            raise BomError(f"Division {code} is not one of yours.")
        out["division"] = division
    if "drawing_revision" in values:
        out["drawing_revision"] = _text(values.get("drawing_revision"))[:20]
    if "notes" in values:
        out["notes"] = str(values.get("notes") or "").strip()[:2000]
    if current is None or "base_quantity" in values:
        base = _decimal(values.get("base_quantity") or "1", "base quantity", 4)
        if not base:
            raise BomError("The base quantity is more than 0.")
        out["base_quantity"] = base
    if "effective_from" in values and _text(values.get("effective_from")):
        from datetime import date

        try:
            out["effective_from"] = date.fromisoformat(_text(values["effective_from"]))
        except ValueError:
            raise BomError("Give the date it applies from, e.g. 2026-12-01.") from None
    if current is None or "reject_pct" in values:
        reject = _decimal(values.get("reject_pct"), "reject allowance %", 2) or ZERO
        if reject >= 100:
            raise BomError("The reject allowance is under 100%.")
        out["reject_pct"] = reject
    if "max_regrind_pct" in values:
        regrind = _decimal(values.get("max_regrind_pct"), "maximum regrind %", 2)
        if regrind is not None and regrind > 100:
            raise BomError("The maximum regrind is at most 100%.")
        out["max_regrind_pct"] = regrind
    mould = current.mould if current else None
    if "mould" in values:
        code = _text(values.get("mould")).upper()
        mould = Mould.objects.filter(code=code).first() if code else None
        if code and mould is None:
            raise BomError(f"There is no mould {code}.")
    if kind == Bom.Kind.MOULDING:
        if mould is None:
            raise BomError("A moulding BOM needs the mould.")
        if not mould.parts.filter(item=item).exists():
            raise BomError(f"Mould {mould.code} does not make {item.code}.")
    else:
        mould = None
    out["mould"] = mould
    if kind == Bom.Kind.MOULDING and ("outputs" in values or current is None or "mould" in values):
        out["outputs"] = _outputs(item, mould, values.get("outputs"))
    return out


def _lines(user: User, rows, *, item: Item, kind: str, base: Decimal, resin: dict | None):
    if not rows:
        raise BomError("Give at least one line.")
    out, seqs = [], set()
    for n, row in enumerate(rows, start=1):
        try:
            seq = int(_text(row.get("seq")) or n * 10)
        except ValueError:
            raise BomError(f"Line {n}: the number is a whole number, e.g. 10.") from None
        if not 1 <= seq <= 9999 or seq in seqs:
            raise BomError(f"Line {n}: the line numbers are 1 to 9999, each once.")
        seqs.add(seq)
        where = f"Line {seq}"
        line_type = _text(row.get("line_type")).lower()
        labels = {label.lower(): code for code, label in T.choices}
        line_type = labels.get(line_type, line_type)
        if line_type not in T.values:
            raise BomError(f"{where}: choose what the line is (raw material, bought-out part ...).")
        line = {
            "seq": seq,
            "line_type": line_type,
            "component": None,
            "description": _text(row.get("description"))[:150],
            "supplier": None,
            "scrap_pct": _decimal(row.get("scrap_pct"), "scrap allowance %", 2) or ZERO,
            "pct_of_resin": None,
            "customer_supplied": _yes(row.get("customer_supplied")),
            "unit_cost": None,
            "stock_size": _text(row.get("stock_size"))[:50],
            "notes": _text(row.get("notes"))[:300],
        }
        if line["scrap_pct"] >= 100:
            raise BomError(f"{where}: the scrap allowance is under 100%.")
        for field in ("bar_length_mm", "cut_length_mm", "facing_mm", "saw_mm"):
            line[field] = _decimal(
                row.get(field), field.replace("_mm", " (mm)").replace("_", " "), 1
            )
        op = _text(row.get("operation_seq"))
        line["operation_seq"] = int(op) if op.isdigit() else None
        if op and line["operation_seq"] is None:
            raise BomError(f"{where}: the operation is its routing number, e.g. 20.")
        method = _text(row.get("issue_method")).lower()
        if not method:
            method = (
                "backflush"
                if kind == Bom.Kind.MOULDING and line_type in (T.RAW, T.MASTERBATCH, T.PACKING)
                else "manual"
            )
        if method not in BomLine.Issue.values:
            raise BomError(f"{where}: the issue is manual or backflush.")
        line["issue_method"] = method
        quantity = _decimal(row.get("quantity"), "quantity", 6)
        if line_type == T.SUBCONTRACT:
            code = _text(row.get("supplier")).upper()
            line["supplier"] = Supplier.objects.filter(code=code).first() if code else None
            if line["supplier"] is None:
                raise BomError(f"{where}: give the supplier who does the work.")
            if not line["description"]:
                raise BomError(f"{where}: describe the service, e.g. Hard chrome plating.")
            line["unit"] = _text(row.get("unit") or "pcs")[:10]
            line["unit_cost"] = _decimal(row.get("unit_cost"), "cost per unit", 2)
            quantity = quantity or base
        else:
            component = _item(row.get("component"))
            if component.pk == item.pk:
                raise BomError(f"{where}: {item.code} cannot be made from itself.")
            line["component"] = component
            line["unit"] = component.unit
            if line_type == T.MASTERBATCH and _text(row.get("pct_of_resin")):
                line["pct_of_resin"] = _decimal(row.get("pct_of_resin"), "% of resin", 2)
            if not quantity and line["cut_length_mm"]:
                quantity = (
                    machining(
                        component,
                        bar_length_mm=line["bar_length_mm"],
                        cut_length_mm=line["cut_length_mm"],
                        facing_mm=line["facing_mm"],
                        saw_mm=line["saw_mm"],
                    )["quantity"]
                    * base
                ).quantize(QTY, ROUND_HALF_UP)
            if not quantity and line_type == T.RAW and resin is not None:
                quantity = _resin_quantity(resin, component.unit, base)
        line["quantity"] = quantity
        out.append(line)
    # Masterbatch as a % of the resin's weight (kg or g lines of raw material).
    resin_kg = sum(
        (
            x["quantity"] / (1000 if x["unit"] == Item.Unit.G else 1)
            for x in out
            if x["line_type"] == T.RAW and x["quantity"] and x["unit"] in ("kg", "g")
        ),
        ZERO,
    )
    for x in out:
        if x["pct_of_resin"] is not None and not x["quantity"]:
            if not resin_kg:
                raise BomError(f"Line {x['seq']}: there is no resin in kg or g to take a % of.")
            kg = resin_kg * x["pct_of_resin"] / 100
            x["quantity"] = (kg * (1000 if x["unit"] == Item.Unit.G else 1)).quantize(
                QTY, ROUND_HALF_UP
            )
        if not x["quantity"]:
            raise BomError(f"Line {x['seq']}: give the quantity.")
    return sorted(out, key=lambda x: x["seq"])


def _no_loop(item: Item, lines: list[dict]) -> None:
    """The item never appears below itself through its sub-assemblies' BOMs in force."""
    seen: set[int] = set()

    def walk(component: Item, depth: int, path: list[str]):
        if depth > MAX_LEVELS:
            raise BomError("The BOM is more than 10 levels deep.")
        if component.pk == item.pk:
            raise BomError(
                f"{item.code} would be made from itself: {' > '.join(path + [item.code])}."
            )
        if component.pk in seen:
            return
        seen.add(component.pk)
        below = in_force(component)
        for line in below.lines.select_related("component") if below else []:
            if line.component_id:
                walk(line.component, depth + 1, path + [component.code])

    for line in lines:
        if line["component"] is not None and line["line_type"] == T.SUB_ASSEMBLY:
            walk(line["component"], 1, [item.code])


# --- Saving --------------------------------------------------------------------------------------


def _next_revision(item: Item) -> int:
    return (Bom.objects.filter(item=item).aggregate(top=Max("revision"))["top"] or 0) + 1


def _open(item: Item) -> Bom | None:
    return Bom.objects.filter(item=item, status__in=[St.DRAFT, St.AWAITING]).first()


def in_force(item: Item) -> Bom | None:
    return Bom.objects.filter(item=item, status=St.APPROVED).first()


def _save_parts(bom: Bom, outputs, lines) -> None:
    if outputs is not None:
        bom.outputs.all().delete()
        BomOutput.objects.bulk_create(BomOutput(bom=bom, **o) for o in outputs)
    if lines is not None:
        bom.lines.all().delete()
        BomLine.objects.bulk_create(BomLine(bom=bom, **x) for x in lines)


def _resin(header: dict, bom: Bom | None) -> dict | None:
    kind = header.get("kind") or (bom.kind if bom else "")
    if kind != Bom.Kind.MOULDING:
        return None
    outputs = header.get("outputs")
    if outputs is None and bom is not None:
        outputs = [
            {"item": o.item, "cavities": o.cavities, "part_weight_g": o.part_weight_g}
            for o in bom.outputs.select_related("item")
        ]
    reject = header.get("reject_pct", bom.reject_pct if bom else ZERO)
    return moulding(header.get("mould") or (bom.mould if bom else None), outputs, reject)


def create(user: User, values: dict) -> Bom:
    _check(user)
    header = _header(user, values, None)
    item = header["item"]
    resin = _resin(header, None)
    base = header["base_quantity"]
    lines = _lines(
        user, values.get("lines"), item=item, kind=header["kind"], base=base, resin=resin
    )
    _no_loop(item, lines)
    outputs = header.pop("outputs", None)
    with audit_context("bom_drafted", item.code), transaction.atomic():
        if _open(item):
            raise BomError(f"{item.code} already has a BOM being prepared.")
        bom = Bom.objects.create(revision=_next_revision(item), created_by=user, **header)
        _save_parts(bom, outputs, lines)
        return bom


def update(user: User, bom: Bom, values: dict) -> Bom:
    _check(user)
    if bom.status != St.DRAFT:
        raise BomError(f"Revision {bom.revision} is {bom.get_status_display().lower()}.")
    header = _header(user, values, bom)
    resin = _resin(header, bom)
    base = header.get("base_quantity", bom.base_quantity)
    kind = header.get("kind", bom.kind)
    lines = None
    if "lines" in values:
        lines = _lines(user, values["lines"], item=bom.item, kind=kind, base=base, resin=resin)
        _no_loop(bom.item, lines)
    outputs = header.pop("outputs", None)
    with audit_context("bom_changed", bom.item.code), transaction.atomic():
        bom = Bom.objects.select_for_update().get(pk=bom.pk)
        for key, value in header.items():
            setattr(bom, key, value)
        bom.save()
        if kind != Bom.Kind.MOULDING:
            bom.outputs.all().delete()
        _save_parts(bom, outputs, lines)
        return bom


def _fields(obj, skip=("id", "bom")) -> dict:
    return {
        f.name: getattr(obj, f.name)
        for f in obj._meta.concrete_fields
        if f.name not in skip and not f.name.endswith("_ptr")
    }


def copy(user: User, source: Bom, item_code: str | None = None) -> Bom:
    """A draft copy: the next revision of the same item, or a new BOM for another item."""
    _check(user)
    item = _item(item_code) if item_code else source.item
    if item.pk != source.item_id and source.kind == Bom.Kind.MOULDING:
        raise BomError("A moulding BOM belongs to its mould's part; start one for the new part.")
    with audit_context("bom_copied", f"{source.item.code} rev {source.revision}"):
        with transaction.atomic():
            if _open(item):
                raise BomError(f"{item.code} already has a BOM being prepared.")
            if item.pk != source.item_id:
                lines = [_fields(x) for x in source.lines.all()]
                _no_loop(item, [{**x, "component": x["component"]} for x in lines])
            header = _fields(
                source,
                skip=(
                    "id",
                    "item",
                    "revision",
                    "status",
                    "created_by",
                    "created_at",
                    "approved_at",
                ),
            )
            header["effective_from"] = timezone.localdate()
            if item.pk != source.item_id:
                header["drawing_revision"] = ""
            bom = Bom.objects.create(
                item=item, revision=_next_revision(item), created_by=user, **header
            )
            BomLine.objects.bulk_create(BomLine(bom=bom, **_fields(x)) for x in source.lines.all())
            BomOutput.objects.bulk_create(
                BomOutput(bom=bom, **_fields(x)) for x in source.outputs.all()
            )
            return bom


def delete(user: User, bom: Bom) -> None:
    _check(user)
    if bom.status != St.DRAFT:
        raise BomError("Only a draft is deleted; an approved BOM becomes obsolete.")
    with audit_context("bom_draft_deleted", bom.item.code), transaction.atomic():
        bom.delete()


def submit(user: User, bom: Bom) -> Bom:
    _check(user)
    with transaction.atomic():
        bom = Bom.objects.select_for_update().select_related("item").get(pk=bom.pk)
        if bom.status != St.DRAFT:
            raise BomError("Only a draft is sent for approval.")
        if not bom.lines.exists():
            raise BomError("Give at least one line.")
        try:
            approvals.submit(
                user,
                DOC,
                bom.pk,
                created_by=bom.created_by,
                division=bom.division,
                title=f"BOM {bom.item.code} rev {bom.revision}: {bom.item.name}",
                link="/boms",
            )
        except ApprovalError as error:
            raise BomError(str(error)) from None
        with audit_context("bom_submitted", bom.item.code):
            bom.status = St.AWAITING
            bom.save(update_fields=["status"])
        return bom


def decide(user: User, bom: Bom, action: str, reason: str = "") -> Bom:
    reason = " ".join((reason or "").split())
    with transaction.atomic():
        bom = Bom.objects.select_for_update().select_related("item").get(pk=bom.pk)
        if bom.status != St.AWAITING:
            raise BomError("This BOM is not waiting for approval.")
        try:
            if action == "approve":
                state = approvals.approve(user, DOC, bom.pk, reason)
                if state.status != ApprovalState.Status.APPROVED:
                    return bom
                with audit_context("bom_approved", bom.item.code):
                    Bom.objects.filter(item=bom.item, status=St.APPROVED).update(status=St.OBSOLETE)
                    bom.status, bom.approved_at = St.APPROVED, timezone.now()
                    bom.save(update_fields=["status", "approved_at"])
            elif action == "send_back":
                approvals.send_back(user, DOC, bom.pk, reason)
                with audit_context("bom_sent_back", reason):
                    bom.status = St.DRAFT
                    bom.save(update_fields=["status"])
            else:
                raise BomError("Unknown action.")
        except ApprovalError as error:
            raise BomError(str(error)) from None
        return bom


# --- Standard cost -------------------------------------------------------------------------------


def _operation_cost(item: Item, day) -> tuple[dict, list[str]]:
    """Per piece, from the routing's run time: machine time at the machine hourly rates,
    labour at the section's labour rate and overhead at the overhead rate per machine hour
    (P3-05), and the subcontract costs. Setup time is costed on the orders (P3-16)."""
    out = {"machine": ZERO, "labour": ZERO, "overhead": ZERO}
    routing = routings.in_force(item)
    if routing is None:
        return out, [f"{item.code}: no routing in force (machine time not costed)"]
    missing = []
    for op in routing.operations.select_related("machine", "section"):
        if op.subcontract:
            if op.subcontract_cost is None:
                missing.append(f"{item.code} op {op.seq}: no subcontract cost")
            out["machine"] += op.subcontract_cost or ZERO
            continue
        hours = op.run_min / 60
        machines = (
            [op.machine]
            if op.machine_id
            else list(
                Machine.objects.filter(section=op.section).exclude(status=Machine.Status.RETIRED)
            )
        )
        hourly = [r for r in (rate_on(m, day) for m in machines) if r is not None]
        if hourly:
            out["machine"] += hours * sum(hourly, ZERO) / len(hourly)
        else:
            missing.append(f"{item.code} op {op.seq}: no machine rate")
        overheads = [rates.overhead_on(op.section, m, day) for m in machines] or [
            rates.overhead_on(op.section, None, day)
        ]
        out["overhead"] += hours * sum(overheads, ZERO) / len(overheads)
        labour = rates.labour_on(op.section, day)
        if labour is None:
            missing.append(f"{item.code} op {op.seq}: no labour rate for {op.section.code}")
        else:
            out["labour"] += hours * labour
    return out, missing


def _mould_cost(bom: Bom, day) -> Decimal:
    """Mould amortisation per unit: the company mould's rate per shot, over the pieces a shot
    makes (a family mould's BOM is per shot already). Customer moulds cost nothing."""
    if bom.kind != Bom.Kind.MOULDING or bom.mould_id is None:
        return ZERO
    per_shot = rates.mould_on(bom.mould, day)
    outputs = list(bom.outputs.all())
    if not per_shot or len(outputs) > 1:
        return per_shot
    pieces = outputs[0].cavities if outputs else sum(p.cavities for p in bom.mould.parts.all())
    return per_shot / pieces if pieces else per_shot


def cost(bom: Bom, *, day=None, depth: int = 0) -> dict:
    """Standard cost of the BOM's base quantity and per unit, through all levels."""
    day = day or timezone.localdate()
    if depth > MAX_LEVELS:
        raise BomError("The BOM is more than 10 levels deep.")
    lines, missing, material = [], [], ZERO
    for x in bom.lines.select_related("component"):
        needed = x.quantity * (1 + x.scrap_pct / 100)
        if x.customer_supplied:
            unit = ZERO
        elif x.line_type == T.SUBCONTRACT:
            unit = x.unit_cost
            if unit is None:
                missing.append(f"line {x.seq}: no cost for the service")
        elif x.line_type == T.SUB_ASSEMBLY and in_force(x.component):
            below = cost(in_force(x.component), day=day, depth=depth + 1)
            unit = below["per_unit"]
            missing += [f"{x.component.code}: {m}" for m in below["missing"]]
        else:
            unit = cost_of(x.component)
            if not unit:
                missing.append(f"{x.component.code}: no stock cost yet")
        value = (needed * (unit or ZERO)).quantize(CENT, ROUND_HALF_UP)
        material += value
        lines.append({"seq": x.seq, "unit_cost": f"{unit or ZERO:.2f}", "value": f"{value:.2f}"})
    ops, more = _operation_cost(bom.item, day)
    missing += more
    mould = _mould_cost(bom, day)
    per_unit = material / bom.base_quantity + sum(ops.values(), ZERO) + mould
    return {
        "material": material,
        **{k: v.quantize(CENT, ROUND_HALF_UP) for k, v in ops.items()},
        "mould": mould.quantize(CENT, ROUND_HALF_UP),
        "per_unit": per_unit.quantize(CENT, ROUND_HALF_UP),
        "lines": lines,
        "missing": missing,
    }


# --- Reading -------------------------------------------------------------------------------------


def _n(value: Decimal | None) -> str:
    return "" if value is None else f"{value.normalize():f}"


def _returned(bom: Bom) -> str | None:
    if bom.status != St.DRAFT:
        return None
    log = (
        ApprovalLog.objects.filter(document_type=DOC, document_id=bom.pk)
        .order_by("-acted_at", "-pk")
        .first()
    )
    return log.reason if log is not None and log.action == ApprovalLog.Action.RETURN else None


def payload(bom: Bom, user: User) -> dict:
    lines = list(bom.lines.select_related("component", "supplier"))
    outputs = list(bom.outputs.select_related("item"))
    state = approvals.state_of(DOC, bom.pk) if bom.status == St.AWAITING else None
    resin = None
    if bom.kind == Bom.Kind.MOULDING and outputs:
        resin = moulding(
            bom.mould,
            [{"cavities": o.cavities, "part_weight_g": o.part_weight_g} for o in outputs],
            bom.reject_pct,
        )
    standard = cost(bom)
    by_seq = {c["seq"]: c for c in standard["lines"]}
    return {
        "id": bom.pk,
        "item": bom.item.code,
        "item_name": bom.item.name,
        "item_unit": bom.item.unit,
        "revision": bom.revision,
        "kind": bom.kind,
        "kind_label": bom.get_kind_display(),
        "division": bom.division.code,
        "drawing_revision": bom.drawing_revision,
        "effective_from": bom.effective_from,
        "base_quantity": _n(bom.base_quantity),
        "mould": bom.mould.code if bom.mould_id else "",
        "reject_pct": _n(bom.reject_pct),
        "max_regrind_pct": _n(bom.max_regrind_pct),
        "status": bom.status,
        "status_label": bom.get_status_display(),
        "notes": bom.notes,
        "created_by": bom.created_by.full_name,
        "outputs": [
            {
                "item": o.item.code,
                "name": o.item.name,
                "cavities": o.cavities,
                "part_weight_g": _n(o.part_weight_g),
            }
            for o in outputs
        ],
        "resin": (
            {k: (f"{v}" if isinstance(v, Decimal) else v) for k, v in resin.items()}
            if resin
            else None
        ),
        "lines": [
            {
                "seq": x.seq,
                "line_type": x.line_type,
                "line_type_label": x.get_line_type_display(),
                "component": x.component.code if x.component_id else "",
                "component_name": x.component.name if x.component_id else "",
                "description": x.description,
                "supplier": x.supplier.code if x.supplier_id else "",
                "quantity": _n(x.quantity),
                "unit": x.unit,
                "scrap_pct": _n(x.scrap_pct),
                "pct_of_resin": _n(x.pct_of_resin),
                "operation_seq": x.operation_seq,
                "issue_method": x.issue_method,
                "customer_supplied": x.customer_supplied,
                "unit_cost": _n(x.unit_cost),
                "stock_size": x.stock_size,
                "bar_length_mm": _n(x.bar_length_mm),
                "cut_length_mm": _n(x.cut_length_mm),
                "facing_mm": _n(x.facing_mm),
                "saw_mm": _n(x.saw_mm),
                "notes": x.notes,
                "standard_value": by_seq.get(x.seq, {}).get("value", ""),
            }
            for x in lines
        ],
        "cost": {
            "material": f"{standard['material']:.2f}",
            "machine": f"{standard['machine']:.2f}",
            "labour": f"{standard['labour']:.2f}",
            "overhead": f"{standard['overhead']:.2f}",
            "mould": f"{standard['mould']:.2f}",
            "per_unit": f"{standard['per_unit']:.2f}",
            "missing": standard["missing"],
        },
        "returned_reason": _returned(bom),
        "can_edit": bom.status == St.DRAFT and can_prepare(user),
        "can_decide": state is not None and approvals.why_not(user, state) is None,
    }


def search(q: str = "", status: str = ""):
    found = Bom.objects.select_related("item", "division", "mould", "created_by")
    if q:
        found = found.filter(Q(item__code__icontains=q) | Q(item__name__icontains=q))
    if status:
        found = found.filter(status=status)
    else:
        found = found.exclude(status=St.OBSOLETE)
    return found[:300]


def where_used(item: Item) -> dict:
    lines = BomLine.objects.filter(component=item).select_related("bom", "bom__item")
    return {
        "item": item.code,
        "name": item.name,
        "boms": [
            {
                "id": x.bom_id,
                "item": x.bom.item.code,
                "item_name": x.bom.item.name,
                "revision": x.bom.revision,
                "status": x.bom.status,
                "quantity": _n(x.quantity),
                "unit": x.unit,
            }
            for x in lines.exclude(bom__status=St.OBSOLETE).order_by(
                "bom__item__code", "-bom__revision"
            )
        ],
    }


def compare(a: Bom, b: Bom) -> list[dict]:
    """Two BOMs side by side, line by component (or service)."""

    def key(x: BomLine) -> str:
        return x.component.code if x.component_id else f"{x.supplier.code}: {x.description}"

    left = {key(x): x for x in a.lines.select_related("component", "supplier")}
    right = {key(x): x for x in b.lines.select_related("component", "supplier")}
    out = []
    for k in sorted(set(left) | set(right)):
        x, y = left.get(k), right.get(k)
        out.append(
            {
                "component": k,
                "a": f"{_n(x.quantity)} {x.unit}" if x else "",
                "b": f"{_n(y.quantity)} {y.unit}" if y else "",
                "changed": (x is None)
                or (y is None)
                or (x.quantity, x.scrap_pct, x.issue_method)
                != (y.quantity, y.scrap_pct, y.issue_method),
            }
        )
    return out


# --- Excel ---------------------------------------------------------------------------------------

COLUMNS = [
    ("item", "Item code"),
    ("kind", "Kind"),
    ("revision", "Revision"),
    ("base_quantity", "Base quantity"),
    ("seq", "Line no"),
    ("line_type", "Line type"),
    ("component", "Component code"),
    ("description", "Service description"),
    ("supplier", "Supplier code"),
    ("quantity", "Quantity"),
    ("scrap_pct", "Scrap %"),
    ("pct_of_resin", "% of resin"),
    ("operation_seq", "Operation no"),
    ("issue_method", "Issue (manual/backflush)"),
    ("customer_supplied", "Customer supplies (yes/no)"),
    ("unit_cost", "Service cost per unit"),
    ("stock_size", "Stock size"),
    ("bar_length_mm", "Bar length (mm)"),
    ("cut_length_mm", "Cut length (mm)"),
    ("facing_mm", "Facing (mm)"),
    ("saw_mm", "Saw cut (mm)"),
]


def export_workbook() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "BOMs"
    sheet.append([label for _, label in COLUMNS])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    found = Bom.objects.filter(status__in=[St.APPROVED, St.DRAFT]).select_related("item")
    for bom in found:
        for x in bom.lines.select_related("component", "supplier"):
            sheet.append(
                [
                    bom.item.code,
                    bom.kind,
                    bom.revision,
                    bom.base_quantity,
                    x.seq,
                    x.get_line_type_display(),
                    x.component.code if x.component_id else "",
                    x.description,
                    x.supplier.code if x.supplier_id else "",
                    x.quantity,
                    x.scrap_pct,
                    x.pct_of_resin,
                    x.operation_seq,
                    x.issue_method,
                    "yes" if x.customer_supplied else "no",
                    x.unit_cost,
                    x.stock_size,
                    x.bar_length_mm,
                    x.cut_length_mm,
                    x.facing_mm,
                    x.saw_mm,
                ]
            )
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 15
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def import_workbook(user: User, content: bytes, *, dry_run: bool) -> dict:
    """Each item in the file becomes a draft (a new revision), or replaces its open draft.
    Moulding BOMs keep their mould and outputs from the page; their lines come from here."""
    if not can_prepare(user):
        raise ImportRefused(["Only the Production Planner prepares bills of materials."])
    if len(content) > MAX_BYTES:
        raise ImportRefused(["The file must be 5 MB or smaller."])
    try:
        rows = list(
            load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            .worksheets[0]
            .iter_rows(values_only=True)
        )
    except (InvalidFileException, OSError, KeyError, ValueError):
        raise ImportRefused(["The file is not an Excel workbook (.xlsx)."]) from None
    if not rows:
        raise ImportRefused(["The file is empty."])
    head = [_text(c).lower() for c in rows[0]]
    index = {key: head.index(label.lower()) for key, label in COLUMNS if label.lower() in head}
    if "item" not in index or "line_type" not in index:
        raise ImportRefused(["The first row must hold the column names of the export."])
    items: dict[str, dict] = {}
    for row in rows[1:]:
        values = {k: row[i] for k, i in index.items() if i < len(row)}
        code = _text(values.get("item")).upper()
        if not code:
            continue
        entry = items.setdefault(code, {"kind": "", "base_quantity": "", "lines": []})
        entry["kind"] = entry["kind"] or _text(values.get("kind")).lower()
        entry["base_quantity"] = entry["base_quantity"] or _text(values.get("base_quantity"))
        entry["lines"].append(values)
    errors, made = [], 0
    with transaction.atomic():
        for code, entry in items.items():
            try:
                with transaction.atomic():
                    item = _item(code)
                    current = _open(item)
                    if current is not None and current.status == St.AWAITING:
                        raise BomError("its BOM is waiting for approval.")
                    if current is not None:
                        update(user, current, {"lines": entry["lines"]})
                    else:
                        source = in_force(item)
                        if source is not None and source.kind == Bom.Kind.MOULDING:
                            update(user, copy(user, source), {"lines": entry["lines"]})
                        else:
                            create(
                                user,
                                {
                                    "item": code,
                                    "kind": entry["kind"] or "general",
                                    "base_quantity": entry["base_quantity"] or "1",
                                    "lines": entry["lines"],
                                },
                            )
                    made += 1
            except BomError as error:
                errors.append(f"{code}: {error}")
        if errors:
            transaction.set_rollback(True)
            raise ImportRefused(errors[:50])
        if dry_run:
            transaction.set_rollback(True)
    return {"drafts": made, "saved": not dry_run}
