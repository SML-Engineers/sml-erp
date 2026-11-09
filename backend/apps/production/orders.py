"""Moulding production orders (backlog P3-06; spec 7.3, 7.7, 7.1B).

- A **production order** makes a part (a finished item with an approved moulding BOM) in a
  quantity, with one or more due dates whose quantities add up to the order's. It is **for a
  sales order line** (its delivery schedule is offered as the due dates, and the orders of a
  line never add up to more than the line's quantity) **or for stock**. Numbered from the
  number series ("MO") when it is made. The Production Planner (production planning, Enter)
  makes, releases, completes and closes orders.
- **Release** copies the BOM in force to the order, each line with the quantity the whole
  order needs, so a later BOM change never alters it (database). A part made in a family
  mould uses the family BOM (per shot): the order needs quantity ÷ the part's cavities
  shots, rounded up. The mould comes from the BOM.
- **Material requirements:** for each line, what the order needs against the division's main
  stores, open purchase orders and purchase requests, less what other released orders need.
  A shortage of something bought is offered as a draft purchase request (raised by the
  stores person or purchasing, then approved as usual); on release the stores person and
  purchasing are told of any shortage. Customer-supplied material is shown but never bought.
- **Statuses** Draft → Released → Completed → Closed; a draft or released order is
  cancelled with a reason. Orders are never deleted and only move forward (database).
- **Where used:** the open orders that make a part, and the released orders that need it.
"""

from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F, Q, QuerySet, Sum
from django.utils import timezone

from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, User
from apps.core.notifications import notify
from apps.core.numbering import NumberSeriesError, allocate
from apps.inventory.models import Item, StockMovement, Store
from apps.purchasing import requests as purchase_requests
from apps.purchasing.models import PurchaseOrderLine, PurchaseRequestLine
from apps.purchasing.orders import PurchasingError
from apps.sales.models import SalesOrder, SalesOrderLine

from . import costs
from .models import (
    Bom,
    BomLine,
    JobOrder,
    Mould,
    OrderBomLine,
    PlanEntry,
    ProductionOrder,
    ProductionOrderDue,
)

DOC = "production_order"
St = ProductionOrder.Status
T = BomLine.Type
ZERO = Decimal("0")
QTY = Decimal("0.001")
NEED = Decimal("0.000001")
OPEN = (St.DRAFT, St.RELEASED)
SALES_OPEN = (SalesOrder.Status.OPEN, SalesOrder.Status.PARTLY_DELIVERED)
MAX_DUES = 50
# Line types that are bought when short (sub-assemblies are made; services are not stock).
BOUGHT = (T.RAW, T.MASTERBATCH, T.BOUGHT, T.PACKING)


class OrderError(Exception):
    pass


def can_plan(user: User) -> bool:
    return effective_access(user).has("production_planning", "enter")


def _check(user: User) -> None:
    if not can_plan(user):
        raise OrderError("Only the Production Planner makes and changes production orders.")


def visible(user: User) -> QuerySet[ProductionOrder]:
    return ProductionOrder.objects.filter(division__in=division_scope(user)).select_related(
        "item", "division", "bom", "mould", "sales_line__order__customer", "created_by"
    )


def _fresh(order: ProductionOrder) -> ProductionOrder:
    return ProductionOrder.objects.select_for_update().get(pk=order.pk)


# --- Values --------------------------------------------------------------------------------------


def _text(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def _quantity(value, label: str) -> Decimal:
    try:
        number = Decimal(_text(value).replace(",", ""))
    except InvalidOperation:
        raise OrderError(f"Give the {label}.") from None
    if not number.is_finite() or number <= 0 or number >= Decimal("1e15"):
        raise OrderError(f"The {label} is more than 0.")
    if number != number.quantize(QTY):
        raise OrderError(f"The {label} has at most 3 decimal places.")
    return number


def _date(value, label: str) -> date:
    try:
        return date.fromisoformat(_text(value))
    except ValueError:
        raise OrderError(f"Give the {label}, e.g. 2026-12-01.") from None


def _bom_for(item: Item) -> tuple[Bom | None, int]:
    """The moulding BOM in force that makes the item, and the item's cavities if it is a
    family mould's BOM (per shot); cavities 0 for a BOM of the item itself."""
    own = Bom.objects.filter(item=item, status=Bom.Status.APPROVED).first()
    if own is not None:
        outputs = list(own.outputs.all())
        if len(outputs) > 1:
            return own, next(o.cavities for o in outputs if o.item_id == item.pk)
        return own, 0
    family = (
        Bom.objects.filter(status=Bom.Status.APPROVED, kind=Bom.Kind.MOULDING, outputs__item=item)
        .distinct()
        .first()
    )
    if family is not None:
        return family, family.outputs.get(item=item).cavities
    return None, 0


def _factor(bom: Bom, cavities: int, quantity: Decimal) -> tuple[Decimal, Decimal | None]:
    """How many BOM base quantities the order needs, and the shots for a family mould."""
    if cavities:
        shots = (quantity / cavities).to_integral_value(ROUND_CEILING)
        return shots / bom.base_quantity, shots
    return quantity / bom.base_quantity, None


def _needs(bom: Bom, factor: Decimal) -> list[dict]:
    out = []
    for x in bom.lines.select_related("component", "supplier"):
        required = (x.quantity * (1 + x.scrap_pct / 100) * factor).quantize(NEED, ROUND_HALF_UP)
        out.append(
            {
                "seq": x.seq,
                "line_type": x.line_type,
                "component": x.component,
                "description": x.description,
                "supplier": x.supplier,
                "per_base": x.quantity,
                "scrap_pct": x.scrap_pct,
                "required": max(required, NEED),
                "unit": x.unit,
                "operation_seq": x.operation_seq,
                "issue_method": x.issue_method,
                "customer_supplied": x.customer_supplied,
                "unit_cost": x.unit_cost,
            }
        )
    return out


def _sales_line(user: User, value, division: Division) -> SalesOrderLine:
    try:
        pk = int(_text(value))
    except ValueError:
        raise OrderError("Choose the sales order line.") from None
    line = (
        SalesOrderLine.objects.select_related("order")
        .filter(pk=pk, order__division__in=division_scope(user))
        .first()
    )
    if line is None:
        raise OrderError("Choose the sales order line.")
    if line.order.status not in SALES_OPEN:
        raise OrderError(f"Sales order {line.order.number} is not open.")
    if line.order.division_id != division.pk:
        raise OrderError(f"Sales order {line.order.number} is for division {line.order.division}.")
    if line.is_tooling:
        raise OrderError("A tooling line is not moulded.")
    return line


def planned_for(
    line: SalesOrderLine, *, but: ProductionOrder | None = None, but_job=None
) -> Decimal:
    """What the line's production orders and job orders (P3-11), not cancelled, already
    make."""
    found = ProductionOrder.objects.filter(sales_line=line).exclude(status=St.CANCELLED)
    if but is not None:
        found = found.exclude(pk=but.pk)
    jobs = JobOrder.objects.filter(sales_line=line).exclude(status=JobOrder.Status.CANCELLED)
    if but_job is not None:
        jobs = jobs.exclude(pk=but_job.pk)
    return (found.aggregate(total=Sum("quantity"))["total"] or ZERO) + (
        jobs.aggregate(total=Sum("quantity"))["total"] or ZERO
    )


def _dues(values: dict, quantity: Decimal, line: SalesOrderLine | None) -> list[tuple]:
    rows = values.get("dues")
    if not rows and line is not None:
        # The line's delivery schedule, as far as the order's quantity goes.
        rows, left = [], quantity
        for s in line.schedule.all():
            if left <= 0:
                break
            take = min(s.quantity, left)
            rows.append({"due_date": s.due_date, "quantity": take})
            left -= take
        if left > 0 and rows:
            rows[-1]["quantity"] += left
    if not rows and values.get("due_date"):
        rows = [{"due_date": values["due_date"], "quantity": quantity}]
    if not rows:
        raise OrderError("Give the due date.")
    if len(rows) > MAX_DUES:
        raise OrderError(f"An order has at most {MAX_DUES} due dates.")
    out = []
    for n, row in enumerate(rows, start=1):
        when = row["due_date"]
        if not isinstance(when, date):
            when = _date(when, f"due date {n}")
        out.append((when, _quantity(row.get("quantity"), f"quantity due on {when}")))
    total = sum((q for _, q in out), ZERO)
    if total != quantity:
        raise OrderError(
            f"The due quantities add up to {_n(total)}, not the order's {_n(quantity)}."
        )
    return sorted(out)


def _fields(user: User, values: dict, current: ProductionOrder | None) -> dict:
    code = _text(values.get("item", current.item.code if current else "")).upper()
    item = Item.objects.filter(code=code).first()
    if item is None:
        raise OrderError(f"There is no item {code or '(blank)'}.")
    if item.category != Item.Category.FINISHED or not item.is_active:
        raise OrderError(f"{item.code} is not an active finished part.")
    bom, _ = _bom_for(item)
    division = bom.division if bom else item.division
    if division is None:
        raise OrderError(f"{item.code} has no approved BOM yet to say which division makes it.")
    if not division_scope(user).filter(pk=division.pk).exists():
        raise OrderError(f"You do not work in division {division.code}.")
    if current is not None and division.pk != current.division_id:
        raise OrderError(f"{item.code} is made in another division: make a new order.")
    quantity = _quantity(values.get("quantity", current.quantity if current else ""), "quantity")
    purpose = _text(values.get("purpose", current.purpose if current else "stock")).lower()
    line = None
    if purpose == ProductionOrder.Purpose.SALES:
        line = _sales_line(
            user, values.get("sales_line", current.sales_line_id if current else ""), division
        )
        left = line.quantity - planned_for(line, but=current)
        if quantity > left:
            raise OrderError(
                f"Sales order {line.order.number} line {line.line_no} has {_n(left)} {line.unit} "
                "left to plan; make the rest for stock."
            )
    elif purpose != ProductionOrder.Purpose.STOCK:
        raise OrderError("The order is for a sales order or for stock.")
    if "dues" in values or "due_date" in values or current is None or "quantity" in values:
        dues = _dues(values, quantity, line)
    else:
        dues = None
    return {
        "item": item,
        "division": division,
        "quantity": quantity,
        "purpose": purpose,
        "sales_line": line,
        "dues": dues,
        "notes": str(values.get("notes", current.notes if current else ""))[:2000],
    }


def _save_dues(order: ProductionOrder, dues) -> None:
    if dues is None:
        return
    order.dues.all().delete()
    ProductionOrderDue.objects.bulk_create(
        ProductionOrderDue(order=order, due_date=d, quantity=q) for d, q in dues
    )


# --- Making and changing -------------------------------------------------------------------------


def create(user: User, values: dict) -> ProductionOrder:
    _check(user)
    fields = _fields(user, values, None)
    dues = fields.pop("dues")
    with audit_context("production_order_created"), transaction.atomic():
        try:
            number = allocate(DOC, division=fields["division"], on_date=timezone.localdate())
        except NumberSeriesError as error:
            raise OrderError(str(error)) from None
        order = ProductionOrder.objects.create(number=number, created_by=user, **fields)
        _save_dues(order, dues)
        return order


def update(user: User, order: ProductionOrder, values: dict) -> ProductionOrder:
    _check(user)
    with audit_context("production_order_changed", order.number), transaction.atomic():
        order = _fresh(order)
        if order.status != St.DRAFT:
            raise OrderError(f"{order.number} is {order.get_status_display().lower()}.")
        fields = _fields(user, values, order)
        dues = fields.pop("dues")
        for key, value in fields.items():
            setattr(order, key, value)
        order.save()
        _save_dues(order, dues)
        return order


def release(user: User, order: ProductionOrder) -> ProductionOrder:
    """Copy the BOM in force to the order and release it to the shop floor."""
    _check(user)
    with audit_context("production_order_released", order.number), transaction.atomic():
        order = _fresh(order)
        if order.status != St.DRAFT:
            raise OrderError(f"Only a draft is released; {order.number} is {order.status}.")
        bom, cavities = _bom_for(order.item)
        if bom is None:
            raise OrderError(f"{order.item.code} has no approved BOM.")
        if bom.kind != Bom.Kind.MOULDING or bom.mould_id is None:
            raise OrderError(f"{order.item.code}'s BOM is not a moulding BOM with a mould.")
        if bom.mould.status == Mould.Status.RETIRED:
            raise OrderError(f"Mould {bom.mould.code} is retired.")
        if order.purpose == ProductionOrder.Purpose.SALES:
            if order.sales_line.order.status not in SALES_OPEN:
                raise OrderError(f"Sales order {order.sales_line.order.number} is not open.")
        factor, _ = _factor(bom, cavities, order.quantity)
        order.status = St.RELEASED
        order.bom = bom
        order.mould = bom.mould
        order.released_by = user
        order.released_at = timezone.now()
        order.save()
        OrderBomLine.objects.bulk_create(
            OrderBomLine(order=order, **x) for x in _needs(bom, factor)
        )
        short = [r for r in requirements(order) if r["shortage"] > 0 and r["buy"]]
        if short:
            transaction.on_commit(lambda: _tell_shortage(order, short))
        return order


def _tell_shortage(order: ProductionOrder, short: list[dict]) -> None:
    items = ", ".join(f"{r['code']} {r['shortage']:,.3f} {r['unit']}" for r in short[:10])
    notify(
        purchase_requests._people(order.division),
        "material_shortage",
        title=f"Production order {order.number} is short of material",
        body=f"{order.item.code} × {order.quantity:,.3f}: short of {items}. "
        "Raise a purchase request from the order.",
        link=f"/production-orders?order={order.pk}",
    )


def _move(user: User, order: ProductionOrder, event: str, to: str, before: tuple, **more):
    _check(user)
    with audit_context(event, order.number), transaction.atomic():
        order = _fresh(order)
        if order.status not in before:
            raise OrderError(
                f"{order.number} is {order.get_status_display().lower()}: it cannot be "
                f"{ProductionOrder.Status(to).label.lower()}."
            )
        order.status = to
        for key, value in more.items():
            setattr(order, key, value)
        order.save()
        if to in (St.COMPLETED, St.CANCELLED):
            # P3-07: a finished or cancelled order leaves the plan after today.
            PlanEntry.objects.filter(order=order, day__gt=timezone.localdate()).delete()
        return order


def complete(user: User, order: ProductionOrder) -> ProductionOrder:
    return _move(
        user,
        order,
        "production_order_completed",
        St.COMPLETED,
        (St.RELEASED,),
        completed_at=timezone.now(),
    )


def close(user: User, order: ProductionOrder) -> ProductionOrder:
    return _move(
        user, order, "production_order_closed", St.CLOSED, (St.COMPLETED,), closed_at=timezone.now()
    )


def cancel(user: User, order: ProductionOrder, reason: str) -> ProductionOrder:
    reason = _text(reason)[:300]
    if not reason:
        raise OrderError("Give the reason for cancelling.")
    return _move(user, order, "production_order_cancelled", St.CANCELLED, OPEN, end_reason=reason)


# --- Material requirements -----------------------------------------------------------------------


def _lines(order: ProductionOrder) -> list[dict]:
    """The order's copied BOM; a draft shows what the BOM in force would need."""
    if order.status != St.DRAFT:
        return [
            {
                "seq": x.seq,
                "line_type": x.line_type,
                "component": x.component,
                "description": x.description,
                "required": x.required,
                "unit": x.unit,
                "customer_supplied": x.customer_supplied,
            }
            for x in order.bom_lines.select_related("component")
        ]
    bom, cavities = _bom_for(order.item)
    if bom is None:
        return []
    return _needs(bom, _factor(bom, cavities, order.quantity)[0])


def requirements(order: ProductionOrder) -> list[dict]:
    """Per line: needed, in the division's main stores, coming (open purchase orders and
    requests), needed by the other released orders, and the shortage."""
    lines = [x for x in _lines(order) if x["component"] is not None]
    items = {x["component"].pk for x in lines}
    division = order.division_id
    stock = dict(
        StockMovement.objects.filter(
            item_id__in=items, store__kind=Store.Kind.MAIN, store__division_id=division
        )
        .values("item_id")
        .annotate(total=Sum("quantity"))
        .values_list("item_id", "total")
    )
    ordered = dict(
        PurchaseOrderLine.objects.filter(
            item_id__in=items,
            order__division_id=division,
            order__status__in=purchase_requests.COMING,
        )
        .values("item_id")
        .annotate(total=Sum(F("quantity") - F("received_quantity")))
        .values_list("item_id", "total")
    )
    requested = dict(
        PurchaseRequestLine.objects.filter(
            item_id__in=items,
            request__division_id=division,
            request__status__in=purchase_requests.REQUESTED,
        )
        .values("item_id")
        .annotate(total=Sum("quantity"))
        .values_list("item_id", "total")
    )
    others = dict(
        OrderBomLine.objects.filter(
            component_id__in=items, order__division_id=division, order__status=St.RELEASED
        )
        .exclude(order=order)
        .values("component_id")
        .annotate(total=Sum("required"))
        .values_list("component_id", "total")
    )
    out = []
    for x in lines:
        c = x["component"]
        on_hand = stock.get(c.pk) or ZERO
        coming = max(ordered.get(c.pk) or ZERO, ZERO) + (requested.get(c.pk) or ZERO)
        other = others.get(c.pk) or ZERO
        free = on_hand + coming - other
        shortage = min(max(x["required"] - free, ZERO), x["required"])
        out.append(
            {
                "seq": x["seq"],
                "code": c.code,
                "name": c.name,
                "item": c,
                "line_type": x["line_type"],
                "required": x["required"],
                "unit": x["unit"],
                "on_hand": on_hand,
                "coming": coming,
                "other_orders": other,
                "shortage": shortage.quantize(QTY, ROUND_CEILING),
                "customer_supplied": x["customer_supplied"],
                "buy": x["line_type"] in BOUGHT and not x["customer_supplied"],
            }
        )
    return out


def raise_request(user: User, order: ProductionOrder):
    """A draft purchase request for the bought materials the order is short of, raised by
    the stores person or purchasing and approved as usual."""
    if not purchase_requests.can_raise(user):
        raise OrderError("The stores person or purchasing raises purchase requests.")
    if not visible(user).filter(pk=order.pk).exists():
        raise OrderError("You do not work in this order's division.")
    if order.status not in OPEN:
        raise OrderError(f"{order.number} is {order.get_status_display().lower()}.")
    short: dict[int, dict] = {}
    for r in requirements(order):
        if r["buy"] and r["shortage"] > 0:
            # The same material on two lines is requested once.
            row = short.setdefault(r["item"].pk, {"item": r["item"], "quantity": ZERO})
            row["quantity"] += r["shortage"]
    if not short:
        raise OrderError(f"{order.number} is not short of anything to buy.")
    first = order.dues.order_by("due_date").first()
    needed = first.due_date if first and first.due_date >= timezone.localdate() else None
    try:
        return purchase_requests.create(
            user,
            division=order.division,
            lines=[
                purchase_requests.LineInput(
                    item=r["item"], quantity=r["quantity"], notes=f"For {order.number}"
                )
                for r in short.values()
            ],
            needed_by=needed,
            reason=f"Material short for production order {order.number} "
            f"({order.item.code} × {order.quantity:,.3f}).",
        )
    except PurchasingError as error:
        raise OrderError(str(error)) from None


# --- Reading -------------------------------------------------------------------------------------


def _n(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value.normalize():f}" if value else "0"


def _sales(line: SalesOrderLine | None) -> dict | None:
    if line is None:
        return None
    return {
        "id": line.pk,
        "order": line.order.number,
        "line_no": line.line_no,
        "customer": line.order.customer.name,
        "description": line.description,
        "quantity": _n(line.quantity),
        "unit": line.unit,
    }


def row(order: ProductionOrder) -> dict:
    first = min((d.due_date for d in order.dues.all()), default=None)
    return {
        "id": order.pk,
        "number": order.number,
        "item": order.item.code,
        "item_name": order.item.name,
        "quantity": _n(order.quantity),
        "unit": order.item.unit,
        "division": order.division.code,
        "purpose": order.purpose,
        "sales_order": order.sales_line.order.number if order.sales_line_id else "",
        "customer": order.sales_line.order.customer.name if order.sales_line_id else "",
        "first_due": first,
        "status": order.status,
        "status_label": order.get_status_display(),
    }


def _order_bom(order: ProductionOrder) -> tuple[Bom | None, int]:
    if not order.bom_id:
        return _bom_for(order.item)
    outputs = list(order.bom.outputs.all())
    if len(outputs) < 2:
        return order.bom, 0
    return order.bom, next((o.cavities for o in outputs if o.item_id == order.item_id), 0)


def payload(order: ProductionOrder, user: User) -> dict:
    planner = can_plan(user)
    bom, cavities = _order_bom(order)
    shots = _factor(bom, cavities, order.quantity)[1] if bom is not None else None
    mould = order.mould or (bom.mould if bom else None)
    needs = requirements(order)
    made = (
        order.receipts.filter(undone=False, item=order.item).aggregate(total=Sum("quantity"))[
            "total"
        ]
        or ZERO
    )
    return row(order) | {
        "made": _n(made),  # good pieces from approved shift reports (P3-09)
        "sales_line": _sales(order.sales_line),
        "dues": [{"due_date": d.due_date, "quantity": _n(d.quantity)} for d in order.dues.all()],
        "notes": order.notes,
        "end_reason": order.end_reason,
        "bom": (
            {"id": bom.pk, "revision": bom.revision, "item": bom.item.code, "status": bom.status}
            if bom
            else None
        ),
        "mould": mould.code if mould else "",
        "family_shots": _n(shots) if shots is not None else "",
        "requirements": [
            {k: (_n(v) if isinstance(v, Decimal) else v) for k, v in r.items() if k != "item"}
            for r in needs
        ],
        "short": any(r["shortage"] > 0 and r["buy"] for r in needs),
        "created_by": order.created_by.full_name,
        "released_by": order.released_by.full_name if order.released_by_id else "",
        "released_at": order.released_at,
        "can_edit": planner and order.status == St.DRAFT,
        "can_release": planner and order.status == St.DRAFT and bom is not None,
        "can_complete": planner and order.status == St.RELEASED,
        "can_close": planner and order.status == St.COMPLETED,
        "can_cancel": planner and order.status in OPEN,
        "can_request": purchase_requests.can_raise(user) and order.status in OPEN,
        # P3-16: what the order has cost so far.
        "costs": costs.summary(order, user) if order.status != St.DRAFT else None,
    }


def search(user: User, q: str = "", status: str = "", item: str = "") -> QuerySet:
    found = visible(user)
    if q:
        found = found.filter(
            Q(number__icontains=q)
            | Q(item__code__icontains=q)
            | Q(item__name__icontains=q)
            | Q(sales_line__order__number__icontains=q)
        )
    if status == "open":
        found = found.filter(status__in=OPEN)
    elif status:
        found = found.filter(status=status)
    if item:
        found = found.filter(item__code=item.upper())
    return found.prefetch_related("dues")


def where_used(user: User, item: Item) -> dict:
    """The open orders that make the item, and the released orders that need it."""
    making = search(user, status="open", item=item.code)
    needing = (
        OrderBomLine.objects.filter(
            component=item,
            order__status=St.RELEASED,
            order__division__in=division_scope(user),
        )
        .select_related("order", "order__item")
        .order_by("order__number")
    )
    return {
        "item": item.code,
        "name": item.name,
        "making": [row(o) for o in making],
        "making_total": _n(sum((o.quantity for o in making), ZERO)),
        "needing": [
            {
                "id": x.order_id,
                "number": x.order.number,
                "item": x.order.item.code,
                "required": _n(x.required),
                "unit": x.unit,
            }
            for x in needing
        ],
    }


def sales_lines(user: User, q: str = "") -> list[dict]:
    """Open sales order lines (not tooling) of the user's divisions, with what is planned."""
    found = (
        SalesOrderLine.objects.filter(
            order__status__in=SALES_OPEN,
            order__division__in=division_scope(user),
            is_tooling=False,
        )
        .select_related("order", "order__customer", "order__division")
        .prefetch_related("schedule")
        .order_by("order__number", "line_no")
    )
    if q:
        found = found.filter(
            Q(order__number__icontains=q)
            | Q(order__customer__name__icontains=q)
            | Q(description__icontains=q)
        )
    out = []
    for line in found[:100]:
        planned = planned_for(line)
        out.append(
            _sales(line)
            | {
                "division": line.order.division.code,
                "planned": _n(planned),
                "left": _n(max(line.quantity - planned, ZERO)),
                "schedule": [
                    {"due_date": s.due_date, "quantity": _n(s.quantity)}
                    for s in line.schedule.all()
                ],
            }
        )
    return out
