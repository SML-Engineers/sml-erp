"""Closing an order and its variances (spec 7.7 "At completion"; backlog P3-18).

An order for a sales order line closes by itself when the line's last quantity is delivered
and the order is completed (whichever comes last); an order for stock or internal work is
closed by the Planner after completion, as before. Closing keeps a final report
(`OrderClose`, never changed):

- **Revenue** in LKR: the good pieces (up to the order quantity) at the average LKR price of
  the line's issued tax invoices (each at its invoice-date rate), or at the sales order's
  price and rate before any invoice. Orders for stock or internal work have none.
- **Estimate against actual by element**, the estimate flexed to the good pieces made from
  the accepted quotation's costing: material, machine time (the quote's machining and
  overhead against labour, machine overhead and mould wear), setup (once per order),
  rejects (the quote's allowance against the cost spent on the rejected pieces) and
  subcontract and direct expenses (with packing). Material is split into **price** (paid more
  or less per kg than quoted) and **usage** (more or less kg per piece) where the kilograms
  are known. An order without a quotation costing shows its actuals and the total against
  its BOM standard cost only.
- **Actuals for quoting**: kg and machine hours per good piece, setup hours and (moulding)
  the actual cycle time; averaged over closed orders per part for the next quotation."""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.audit import audit_context
from apps.core.models import User
from apps.inventory.models import Item
from apps.sales.models import QuotationCosting, TaxInvoice, TaxInvoiceLine

from . import costs, profit
from .models import JobOrder, MouldingRun, OrderClose, OrderCost, ProductionOrder, ShiftReport

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")
E = OrderCost.Element
MACHINE = (E.LABOUR, E.OVERHEAD, E.MOULD)
OUTSIDE = (E.SUBCONTRACT, E.DIRECT)
COMPLETED = "completed"
CLOSED = "closed"


def _m(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(CENT, ROUND_HALF_UP))


def _q(value: Decimal | None, places="0.0001") -> str | None:
    return None if value is None else str(value.quantize(Decimal(places), ROUND_HALF_UP))


def _key(order) -> dict:
    return {"job": order} if isinstance(order, JobOrder) else {"production_order": order}


def _kg(quantity: Decimal, unit: str) -> Decimal | None:
    if unit == Item.Unit.KG:
        return quantity
    if unit == Item.Unit.G:
        return quantity / 1000
    return None


# --- Actuals ---------------------------------------------------------------------------------


def _material_kg(order) -> Decimal | None:
    """Kilograms of material used: a job's issues less returns by weight; a moulding order's
    resin and masterbatch backflushed for every piece moulded."""
    total, known = ZERO, False
    if isinstance(order, JobOrder):
        for quantity, unit in OrderCost.objects.filter(job=order, element=E.MATERIAL).values_list(
            "quantity", "unit"
        ):
            kg = _kg(quantity, unit)
            if kg is not None:
                total, known = total + kg, True
        return total if known else None
    from .shift_approval import MOULDED, _needs

    reports = ShiftReport.objects.filter(
        status=ShiftReport.Status.APPROVED, runs__order=order
    ).distinct()
    for report in reports:
        needs = _needs(report)
        for run in report.runs.filter(order=order):
            for item, _, quantity, kind in needs.get(run.pk, []):
                kg = _kg(quantity, item.unit) if kind in MOULDED else None
                if kg is not None:
                    total, known = total + kg, True
    return total if known else None


def _cycle(order) -> tuple[Decimal | None, Decimal | None]:
    """(actual, standard) cycle time in seconds of a moulding order, weighted by shots."""
    if isinstance(order, JobOrder):
        return None, None
    shots, weighted, standard = 0, ZERO, None
    for run in MouldingRun.objects.filter(
        order=order, report__status=ShiftReport.Status.APPROVED
    ).select_related("mould"):
        standard = run.mould.cycle_time_s
        if run.actual_cycle_s:
            shots += run.shots
            weighted += run.actual_cycle_s * run.shots
    return (weighted / shots if shots else None), standard


def actuals(order) -> dict:
    by = defaultdict(lambda: ZERO)
    hours = setup_hours = ZERO
    for element, amount, quantity, unit in OrderCost.objects.filter(**_key(order)).values_list(
        "element", "amount", "quantity", "unit"
    ):
        by[element] += amount
        if unit == "h" and element == E.OVERHEAD:
            hours += quantity
        if unit == "h" and element == E.SETUP:
            setup_hours += quantity
    good, rejected = costs._rejected(order)
    cycle, standard_cycle = _cycle(order)
    return {
        "by": by,
        "total": sum(by.values(), ZERO),
        "good": good,
        "rejected": rejected,
        "kg": _material_kg(order),
        "hours": hours,
        "setup_hours": setup_hours,
        "cycle_s": cycle,
        "standard_cycle_s": standard_cycle,
    }


# --- The quoted standard -------------------------------------------------------------------


def standard(order) -> dict | None:
    """Per piece from the accepted quotation's costing (at the quoted quantity), with setup
    and per-order extras once per order."""
    line = order.sales_line
    quoted = line.quotation_line if line is not None else None
    costing = getattr(quoted, "costing", None) if quoted is not None else None
    if costing is None:
        return None
    f = profit.quotation_costing.figures(
        costing, quoted.quantity, quoted.unit_price, quoted.quotation.exchange_rate
    )
    extras = list(costing.extras.all())
    per_piece = sum((e.amount for e in extras if not e.per_order), ZERO)
    per_order = sum((e.amount for e in extras if e.per_order), ZERO)
    if costing.method == QuotationCosting.Method.MOULDING:
        cavities = Decimal(costing.cavities or 1)
        shot = ((costing.part_weight_g or 0) + (costing.runner_weight_g or 0) / cavities) / 1000
        kg = shot * (1 + costing.masterbatch_pct / HUNDRED)
    else:
        kg = costing.weight_kg or ZERO
    material = f["material"]
    return {
        "material": material,
        "machine": f["machining"] + f["overhead"],
        "rejects": f["rejects"],
        "outside": f["packing"] + per_piece,
        "setup": (costing.setup_hours * costing.setup_rate).quantize(CENT, ROUND_HALF_UP),
        "per_order": per_order,
        "kg": kg,
        "per_kg": material / kg if kg else None,
        "cycle_s": costing.cycle_time_s,
        "setup_hours": costing.setup_hours,
    }


# --- Revenue ---------------------------------------------------------------------------------


def revenue(order, good: Decimal) -> tuple[Decimal | None, str]:
    line = order.sales_line
    if line is None:
        return None, ""
    lkr = qty = ZERO
    for x in TaxInvoiceLine.objects.filter(
        delivery_line__order_line=line, invoice__status=TaxInvoice.Status.ISSUED
    ).select_related("invoice"):
        lkr += (x.amount - x.discount) * x.invoice.exchange_rate
        qty += x.quantity
    if qty:
        price, basis = lkr / qty, "invoices"
    else:
        price, basis = profit._price(order), "order"
    if price is None:
        return None, ""
    return price * min(good, order.quantity), basis


# --- The report ------------------------------------------------------------------------------


def report(order) -> dict:
    """The order's final figures as they stand now (kept when it closes)."""
    a = actuals(order)
    by, good, rejected = a["by"], a["good"], a["rejected"]
    made = good + rejected
    share = good / made if made else Decimal(1)
    machine = sum((by[e] for e in MACHINE), ZERO)
    actual_rows = {
        "material": by[E.MATERIAL] * share,
        "machine": machine * share,
        "setup": by[E.SETUP],
        "rejects": (by[E.MATERIAL] + machine) * (1 - share),
        "outside": sum((by[e] for e in OUTSIDE), ZERO),
    }
    std = standard(order)
    estimate_rows = None
    price_var = usage_var = None
    if std is not None:
        estimate_rows = {
            "material": std["material"] * good,
            "machine": std["machine"] * good,
            "setup": std["setup"],
            "rejects": std["rejects"] * good,
            "outside": std["outside"] * good + std["per_order"],
        }
        if a["kg"] is not None and std["per_kg"] is not None:
            kg_good = a["kg"] * share
            price_var = actual_rows["material"] - kg_good * std["per_kg"]
            usage_var = (kg_good - std["kg"] * good) * std["per_kg"]
    labels = {
        "material": "Material",
        "machine": "Machine time",
        "setup": "Setup and mould changes",
        "rejects": "Rejects",
        "outside": "Subcontract, direct expenses and packing",
    }
    rows = []
    for key, label in labels.items():
        est = estimate_rows[key] if estimate_rows else None
        act = actual_rows[key]
        rows.append(
            {
                "key": key,
                "label": label,
                "estimate": _m(est),
                "actual": _m(act),
                "variance": _m(act - est) if est is not None else None,
            }
        )
    cost = a["total"]
    unit, basis = profit._estimate(order)
    estimate_total = sum(estimate_rows.values(), ZERO) if estimate_rows else None
    if estimate_total is None and unit is not None:
        estimate_total = unit * good
    income, income_basis = revenue(order, good)
    margin = income - cost if income is not None else None
    return {
        "basis": "quotation" if std is not None else basis,
        "quantity": f"{order.quantity.normalize():f}",
        "good": f"{good.normalize():f}" if good else "0",
        "rejected": f"{rejected.normalize():f}" if rejected else "0",
        "revenue": _m(income),
        "revenue_basis": income_basis,
        "cost": _m(cost),
        "margin": _m(margin),
        "margin_pct": _m(margin / cost * HUNDRED) if margin is not None and cost else None,
        "estimate_cost": _m(estimate_total),
        "variance": _m(cost - estimate_total) if estimate_total is not None else None,
        "rows": rows,
        "material_price": _m(price_var),
        "material_usage": _m(usage_var),
        "actuals": {
            "kg_per_piece": _q(a["kg"] * share / good) if a["kg"] is not None and good else None,
            "hours_per_1000": _q(a["hours"] * share / good * 1000, "0.01") if good else None,
            "setup_hours": _q(a["setup_hours"], "0.01"),
            "cycle_s": _q(a["cycle_s"], "0.01"),
        },
        "quoted": {
            "kg_per_piece": _q(std["kg"]) if std else None,
            "setup_hours": _q(std["setup_hours"], "0.01") if std else None,
            "cycle_s": _q(std["cycle_s"], "0.01") if std and std["cycle_s"] else None,
        },
        "standard_cycle_s": _q(a["standard_cycle_s"], "0.01"),
    }


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def record(user: User, order, *, automatic: bool = False) -> OrderClose:
    """Keep the closing order's final report (once)."""
    found = OrderClose.objects.filter(**_key(order)).first()
    if found is not None:
        return found
    body = report(order)
    return OrderClose.objects.create(
        **_key(order),
        division=order.division,
        item=order.item if order.item_id else None,
        revenue=_dec(body["revenue"]),
        cost=Decimal(body["cost"]),
        margin=_dec(body["margin"]),
        variance=_dec(body["variance"]),
        automatic=automatic,
        report=body,
        closed_by=user,
    )


def payload(order) -> dict | None:
    found = OrderClose.objects.filter(**_key(order)).select_related("closed_by").first()
    if found is None:
        return None
    return {
        **found.report,
        "automatic": found.automatic,
        "closed_by": found.closed_by.full_name,
        "closed_at": found.closed_at,
    }


# --- Closing on the last delivery ----------------------------------------------------------


def _delivered_in_full(line) -> bool:
    from apps.sales import deliveries

    return deliveries.delivered(line.order).get(line.pk, ZERO) >= line.quantity


def close_if_delivered(user: User, order) -> bool:
    """Close a completed order whose sales line has had its last quantity delivered."""
    model = type(order)
    with transaction.atomic():
        order = model.objects.select_for_update().get(pk=order.pk)
        if order.status != COMPLETED or order.sales_line_id is None:
            return False
        if not _delivered_in_full(order.sales_line):
            return False
        event = "job_order_closed" if model is JobOrder else "production_order_closed"
        with audit_context(event, f"{order.number}: last quantity delivered"):
            order.status = CLOSED
            order.closed_at = timezone.now()
            order.save()
            record(user, order, automatic=True)
        return True


def after_delivery(user: User, note) -> None:
    """A delivery note issued: close its lines' completed orders now delivered in full."""
    for line in note.order.lines.all():
        for order in list(JobOrder.objects.filter(sales_line=line, status=COMPLETED)) + list(
            ProductionOrder.objects.filter(sales_line=line, status=COMPLETED)
        ):
            close_if_delivered(user, order)


# --- Feeding the next quotation ------------------------------------------------------------


def part_actuals(item: Item, limit: int = 10) -> dict:
    """The last closed orders of a part, and their averages: kg and machine hours per good
    piece, setup hours per order and the moulding cycle time."""
    closed = list(OrderClose.objects.filter(item=item).order_by("-closed_at")[:limit])
    rows = []
    sums: dict[str, list[Decimal]] = defaultdict(list)
    for c in closed:
        order = c.job or c.production_order
        got = c.report.get("actuals", {})
        for key in ("kg_per_piece", "hours_per_1000", "setup_hours", "cycle_s"):
            if got.get(key) is not None:
                sums[key].append(Decimal(got[key]))
        rows.append(
            {
                "number": order.number,
                "closed_at": c.closed_at,
                "good": c.report.get("good"),
                "margin_pct": c.report.get("margin_pct"),
                **got,
            }
        )

    def avg(key, places):
        values = sums.get(key)
        return _q(sum(values, ZERO) / len(values), places) if values else None

    return {
        "item": item.code,
        "name": item.name,
        "orders": rows,
        "average": {
            "kg_per_piece": avg("kg_per_piece", "0.0001"),
            "hours_per_1000": avg("hours_per_1000", "0.01"),
            "setup_hours": avg("setup_hours", "0.01"),
            "cycle_s": avg("cycle_s", "0.01"),
        },
    }


# --- Profitability reports (P3-20 part 2) -----------------------------------------------------

GROUPS = ("order", "customer", "part", "mould", "division")


def _closed(user: User, start, end):
    from apps.core.access import division_scope

    return (
        OrderClose.objects.filter(
            division__in=division_scope(user),
            closed_at__date__gte=start,
            closed_at__date__lte=end,
        )
        .select_related(
            "division",
            "item",
            "job__sales_line__order__customer",
            "production_order__sales_line__order__customer",
            "production_order__mould",
        )
        .order_by("closed_at", "id")
    )


def _group_key(c: OrderClose, by: str) -> tuple[str, str] | None:
    order = c.job or c.production_order
    if by == "order":
        return order.number, order.item.code if order.item_id else ""
    if by == "customer":
        line = order.sales_line
        return (line.order.customer.name, "") if line is not None else None
    if by == "part":
        return (c.item.code, c.item.name) if c.item_id else None
    if by == "mould":
        mould = getattr(order, "mould", None)
        return (mould.code, mould.name) if mould is not None else None
    return c.division.code, ""


def margins(user: User, start, end, by: str = "customer") -> dict:
    """Closed orders in the dates with revenue, grouped: revenue, cost, margin and margin %
    on cost, most profitable first. Orders for stock or internal work have no revenue and
    are counted apart."""
    if by not in GROUPS:
        raise profit.ProfitError("Group by order, customer, part, mould or division.")
    groups: dict[str, dict] = {}
    without = 0
    for c in _closed(user, start, end):
        if c.revenue is None:
            without += 1
            continue
        key = _group_key(c, by)
        if key is None:
            continue
        g = groups.setdefault(
            key[0], {"key": key[0], "name": key[1], "orders": 0, "revenue": ZERO, "cost": ZERO}
        )
        g["orders"] += 1
        g["revenue"] += c.revenue
        g["cost"] += c.cost
    rows = []
    for g in groups.values():
        margin = g["revenue"] - g["cost"]
        rows.append(
            {
                **g,
                "revenue": _m(g["revenue"]),
                "cost": _m(g["cost"]),
                "margin": _m(margin),
                "margin_pct": _m(margin / g["cost"] * HUNDRED) if g["cost"] else None,
            }
        )
    rows.sort(key=lambda r: (-Decimal(r["margin"]), r["key"]))
    revenue = sum((Decimal(r["revenue"]) for r in rows), ZERO)
    cost = sum((Decimal(r["cost"]) for r in rows), ZERO)
    return {
        "by": by,
        "rows": rows,
        "total": {
            "revenue": _m(revenue),
            "cost": _m(cost),
            "margin": _m(revenue - cost),
            "margin_pct": _m((revenue - cost) / cost * HUNDRED) if cost else None,
        },
        "without_revenue": without,
    }


def accuracy(user: User, start, end) -> dict:
    """How far closed orders' actual costs were from their quotations, by element: the
    estimate and actual added up over the orders estimated from a quotation, the variance
    and its % of the estimate (positive: costlier than quoted)."""
    rows: dict[str, dict] = {}
    count = 0
    price = usage = ZERO
    for c in _closed(user, start, end):
        r = c.report
        if r.get("basis") != "quotation":
            continue
        count += 1
        for x in r.get("rows", []):
            if x.get("estimate") is None:
                continue
            g = rows.setdefault(
                x["key"], {"key": x["key"], "label": x["label"], "estimate": ZERO, "actual": ZERO}
            )
            g["estimate"] += Decimal(x["estimate"])
            g["actual"] += Decimal(x["actual"])
        price += Decimal(r.get("material_price") or 0)
        usage += Decimal(r.get("material_usage") or 0)
    out = []
    for g in rows.values():
        variance = g["actual"] - g["estimate"]
        out.append(
            {
                "key": g["key"],
                "label": g["label"],
                "estimate": _m(g["estimate"]),
                "actual": _m(g["actual"]),
                "variance": _m(variance),
                "variance_pct": _m(variance / g["estimate"] * HUNDRED) if g["estimate"] else None,
            }
        )
    return {
        "orders": count,
        "rows": out,
        "material_price": _m(price),
        "material_usage": _m(usage),
    }
