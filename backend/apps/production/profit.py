"""Live order profitability (spec 7.7; backlog P3-17).

For every job order and moulding production order, three figures:

- **Estimate**: the cost per piece from the accepted quotation's costing (at the quoted
  quantity, tooling left out), or else the BOM's standard cost, times the order quantity.
- **Actual to date**: the order's cost entries (P3-16) and the revenue earned on the good
  pieces (good quantity × the sales line's net price in LKR at the order's rate).
- **Forecast at completion**: actual cost + remaining quantity × the standard cost per piece
  (the estimate's, or the actual cost per good piece so far when there is no estimate).
  Forecast margin = forecast revenue − forecast cost; margin % is on cost, as on quotations.

Status: **red** for a forecast loss or a cost overrun over the limit; **amber** for a margin
below the minimum or rejects over the limit; otherwise **green**. The limits come from the
production settings in force (P3-02); a blank minimum margin means the quotation limits'
minimum for the order's division.

The Production Manager and the Director get one alert per order and kind (overrun, margin,
rejects) when it first happens: checked after the order's costs are brought up to date and
in the daily snapshot of every open order. A moulding view adds per machine and mould: actual
against standard cycle time, material per good piece, rejects and the margin per 1,000."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.access import division_scope
from apps.core.models import User
from apps.core.notifications import notify
from apps.masters.limits import DEFAULT_MIN_MARGIN
from apps.masters.limits import in_force as limits_in_force
from apps.purchasing.models import SupplierInvoiceLine
from apps.sales import costing as quotation_costing
from apps.vouchers.models import VoucherLine

from . import boms, costs, reasons
from .models import (
    DowntimeEntry,
    JobCardEntry,
    JobOrder,
    MouldingRun,
    OrderCost,
    OrderProfitSnapshot,
    ProductionOrder,
    ProductionReceipt,
    ProfitAlert,
    RejectEntry,
    ShiftReport,
)

log = logging.getLogger(__name__)

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")
OPEN = ("released",)
DONE = ("completed", "closed")
GREEN, AMBER, RED = "green", "amber", "red"


class ProfitError(Exception):
    pass


def can_see(user: User) -> bool:
    return costs.can_see(user)


def _money(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(CENT, ROUND_HALF_UP)


def _pct(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(CENT, ROUND_HALF_UP)


def _s(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _key(order) -> dict:
    return {"job": order} if isinstance(order, JobOrder) else {"production_order": order}


def kind_of(order) -> str:
    return "job" if isinstance(order, JobOrder) else "production"


def link_of(order) -> str:
    if isinstance(order, JobOrder):
        return f"/job-orders?job={order.pk}"
    return f"/production-orders?order={order.pk}"


# --- The figures -----------------------------------------------------------------------------


def _price(order) -> Decimal | None:
    """LKR per piece of the order's sales line, after discounts; None for stock or internal
    work."""
    line = order.sales_line
    if line is None or not line.quantity:
        return None
    return line.net / line.quantity * line.order.exchange_rate


def _estimate(order) -> tuple[Decimal | None, str]:
    """(cost per piece, where it came from): the accepted quotation's costing, else the BOM's
    standard cost."""
    line = order.sales_line
    quoted = line.quotation_line if line is not None else None
    if quoted is not None:
        found = getattr(quoted, "costing", None)
        if found is not None:
            row = quotation_costing.figures(
                found, quoted.quantity, quoted.unit_price, quoted.quotation.exchange_rate
            )
            if row["cost"] > 0:
                return row["cost"], "quotation"
    if order.bom_id:
        try:
            per_unit = boms.cost(order.bom)["per_unit"]
        except boms.BomError:
            per_unit = ZERO
        if per_unit > 0:
            return per_unit, "bom"
    return None, ""


def _min_margin(order, setting) -> Decimal:
    if setting is not None and setting.min_margin_pct is not None:
        return setting.min_margin_pct
    line = order.sales_line
    quotation = line.order.quotation if line is not None else None
    on = quotation.quote_date if quotation is not None else timezone.localdate()
    limit = limits_in_force(order.division, on)
    return limit.min_margin_pct if limit else DEFAULT_MIN_MARGIN


def _setting():
    try:
        return reasons.setting_on()
    except reasons.ReasonError:
        return None


def figures(order, setting=None) -> dict:
    """The order's estimate, actual to date and forecast at completion, with its status and
    the limits it breaks. Amounts are Decimals in LKR."""
    setting = setting if setting is not None else _setting()
    actual = OrderCost.objects.filter(**_key(order)).aggregate(t=Sum("amount"))["t"] or ZERO
    good, rejected = costs._rejected(order)
    quantity = order.quantity
    done = order.status in DONE
    remaining = ZERO if done else max(quantity - good, ZERO)
    unit, basis = _estimate(order)
    standard = unit if unit is not None else (actual / good if good else None)
    forecast = actual + remaining * standard if standard is not None else None
    price = _price(order)
    value = earned = revenue = None
    if price is not None:
        value = price * quantity
        earned = price * min(good, quantity)
        revenue = price * (min(good, quantity) + remaining)
    margin = margin_pct = None
    if revenue is not None and forecast is not None:
        margin = revenue - forecast
        if forecast > 0:
            margin_pct = margin / forecast * HUNDRED
    overrun = None
    if unit is not None and good > 0:
        overrun = (actual / (unit * good) - 1) * HUNDRED
    made = good + rejected
    reject_pct = rejected / made * HUNDRED if made else None
    minimum = _min_margin(order, setting)
    flags = []
    if overrun is not None and setting is not None and overrun > setting.overrun_alert_pct:
        flags.append(ProfitAlert.Kind.OVERRUN)
    if margin_pct is not None and margin_pct < minimum:
        flags.append(ProfitAlert.Kind.MARGIN)
    if reject_pct is not None and setting is not None and reject_pct > setting.reject_alert_pct:
        flags.append(ProfitAlert.Kind.REJECTS)
    if ProfitAlert.Kind.OVERRUN in flags or (margin is not None and margin < 0):
        status = RED
    elif flags:
        status = AMBER
    else:
        status = GREEN
    complete = min(good / quantity * HUNDRED, HUNDRED) if quantity else ZERO
    return {
        "quantity": quantity,
        "good": good,
        "rejected": rejected,
        "complete_pct": _pct(complete),
        "price": _money(price),
        "value": _money(value),
        "earned": _money(earned),
        "estimate_basis": basis,
        "estimate_unit": _money(unit),
        "estimate_cost": _money(unit * quantity) if unit is not None else None,
        "estimate_margin": _money(value - unit * quantity)
        if unit is not None and value is not None
        else None,
        "cost": _money(actual),
        "per_good": _money(actual / good) if good else None,
        "forecast_cost": _money(forecast),
        "forecast_revenue": _money(revenue),
        "forecast_margin": _money(margin),
        "margin_pct": _pct(margin_pct),
        "min_margin_pct": minimum,
        "overrun_pct": _pct(overrun),
        "overrun_limit": setting.overrun_alert_pct if setting else None,
        "reject_pct": _pct(reject_pct),
        "reject_limit": setting.reject_alert_pct if setting else None,
        "flags": [str(f) for f in flags],
        "status": status,
    }


def _payload(f: dict) -> dict:
    out = {}
    for key, value in f.items():
        if isinstance(value, Decimal):
            whole = key in ("quantity", "good", "rejected")
            out[key] = f"{value.normalize():f}" if whole else str(value)
        else:
            out[key] = value
    return out


# --- Who the order is for -------------------------------------------------------------------


def _due(order) -> date | None:
    if isinstance(order, JobOrder):
        return order.due_date
    first = order.dues.order_by("due_date").first()
    return first.due_date if first else None


def _sections(order) -> list[str]:
    if isinstance(order, JobOrder):
        return sorted({o.section.code for o in order.operations.all() if o.section_id})
    return sorted(
        set(
            MouldingRun.objects.filter(order=order).values_list("machine__section__code", flat=True)
        )
        | set(order.plan_entries.values_list("machine__section__code", flat=True))
    )


def _row(order, setting) -> dict:
    line = order.sales_line
    customer = line.order.customer if line is not None else None
    part = order.item.code if order.item_id else ""
    return {
        "kind": kind_of(order),
        "id": order.pk,
        "number": order.number,
        "link": link_of(order),
        "status_label": order.get_status_display(),
        "division": order.division.code,
        "customer": customer.name if customer else "",
        "customer_id": customer.pk if customer else None,
        "sales_order": line.order.number if line is not None else "",
        "part": part,
        "description": getattr(order, "description", "") or (order.item.name if part else ""),
        "due_date": _due(order),
        "sections": _sections(order),
        **_payload(figures(order, setting)),
    }


def _orders(user: User, state: str):
    statuses = {"completed": ("completed",), "closed": ("closed",)}.get(state, OPEN)
    scope = division_scope(user)
    jobs = JobOrder.objects.filter(status__in=statuses, division__in=scope).select_related(
        "division", "item", "bom", "sales_line__order__customer", "sales_line__quotation_line"
    )
    orders = ProductionOrder.objects.filter(status__in=statuses, division__in=scope).select_related(
        "division", "item", "bom", "sales_line__order__customer", "sales_line__quotation_line"
    )
    return list(jobs) + list(orders)


def dashboard(user: User, filters: dict) -> dict:
    """Every open (or completed) order the user may see, filtered by division, customer,
    section and due date, worst first."""
    if not can_see(user):
        raise ProfitError("You do not have access to order profitability.")
    state = filters.get("state") or "open"
    setting = _setting()
    rows = []
    for order in _orders(user, state):
        if filters.get("division") and order.division.code != filters["division"]:
            continue
        row = _row(order, setting)
        if filters.get("customer") and str(row["customer_id"]) != str(filters["customer"]):
            continue
        if filters.get("section") and filters["section"] not in row["sections"]:
            continue
        due_by = filters.get("due_by")
        if due_by and (row["due_date"] is None or row["due_date"].isoformat() > due_by):
            continue
        rows.append(row)
    rank = {RED: 0, AMBER: 1, GREEN: 2}
    rows.sort(key=lambda r: (rank[r["status"]], r["due_date"] or date.max, r["number"]))
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in (RED, AMBER, GREEN)}
    return {"state": state, "counts": counts, "orders": rows}


def detail(order, user: User) -> dict | None:
    """The order's profitability for its own page, with its daily snapshots."""
    if not can_see(user):
        return None
    shots = [
        {
            "day": s.day,
            "cost": str(s.cost),
            "forecast_margin": _s(s.forecast_margin),
            "margin_pct": _s(s.margin_pct),
            "complete_pct": str(s.complete_pct),
            "status": s.status,
        }
        for s in OrderProfitSnapshot.objects.filter(**_key(order)).order_by("day")
    ]
    alerts = [
        {"kind": a.kind, "label": a.get_kind_display(), "detail": a.detail, "at": a.created_at}
        for a in ProfitAlert.objects.filter(**_key(order))
    ]
    return {**_payload(figures(order)), "snapshots": shots[-120:], "alerts": alerts}


# --- Drill-down: each cost entry's source document -------------------------------------------


def _ids(sources, prefix: str) -> dict[str, int]:
    found = {}
    for s in sources:
        parts = s.split(":")
        if parts[0] == prefix and len(parts) > 1 and parts[1].isdigit():
            found[s] = int(parts[1])
    return found


def source_links(sources) -> dict[str, dict]:
    """For each cost source, the document it came from: {"label", "link"}."""
    sources = set(sources)
    out: dict[str, dict] = {}
    report_of = {}
    for prefix, model in (
        ("run", MouldingRun),
        ("downtime", DowntimeEntry),
        ("receipt", ProductionReceipt),
        ("job_entry", JobCardEntry),
    ):
        wanted = _ids(sources, prefix)
        found = dict(model.objects.filter(pk__in=wanted.values()).values_list("pk", "report_id"))
        for source, pk in wanted.items():
            if pk in found:
                report_of[source] = found[pk]
    reports = {
        r.pk: r
        for r in ShiftReport.objects.filter(pk__in=set(report_of.values())).select_related(
            "section", "shift"
        )
    }
    for source, report_id in report_of.items():
        r = reports[report_id]
        out[source] = {
            "label": f"Work shift report {r.section.code} {r.day} {r.shift.code}",
            "link": f"/shift-report?report={r.pk}",
        }
    wanted = _ids(sources, "voucher_line")
    for line in VoucherLine.objects.filter(pk__in=wanted.values()).select_related("voucher"):
        for source, pk in wanted.items():
            if pk == line.pk:
                out[source] = {
                    "label": f"Voucher {line.voucher.number}",
                    "link": f"/vouchers/{line.voucher_id}",
                }
    wanted = _ids(sources, "invoice_line")
    for line in SupplierInvoiceLine.objects.filter(pk__in=wanted.values()).select_related(
        "invoice"
    ):
        for source, pk in wanted.items():
            if pk == line.pk:
                out[source] = {
                    "label": f"Supplier invoice {line.invoice.number}",
                    "link": f"/supplier-invoices/{line.invoice_id}",
                }
    return out


# --- Alerts and snapshots -------------------------------------------------------------------


def _recipients(order) -> list[User]:
    found = []
    for user in (
        User.objects.filter(
            is_active=True,
            role_assignments__role__code__in=("director", "production_manager"),
            role_assignments__role__is_active=True,
        )
        .distinct()
        .prefetch_related("divisions")
    ):
        if division_scope(user).filter(pk=order.division_id).exists():
            found.append(user)
    return found


def _detail(kind: str, f: dict) -> str:
    if kind == ProfitAlert.Kind.OVERRUN:
        return (
            f"Cost so far {f['cost']:,} for {f['good'].normalize():,f} good pieces is "
            f"{f['overrun_pct']}% over the estimate (limit {f['overrun_limit']}%)."
        )
    if kind == ProfitAlert.Kind.MARGIN:
        return (
            f"Forecast margin {f['forecast_margin']:,} ({f['margin_pct']}%) is below the "
            f"minimum of {f['min_margin_pct']}%."
        )
    return f"Rejects are {f['reject_pct']}% of the pieces made (limit {f['reject_limit']}%)."


def check_alerts(order, setting=None, f: dict | None = None) -> list[ProfitAlert]:
    """Raise each alert the order now breaks for the first time, and tell the Production
    Manager and the Director."""
    if order.status not in OPEN:
        return []
    f = f if f is not None else figures(order, setting)
    raised = []
    for kind in f["flags"]:
        if ProfitAlert.objects.filter(**_key(order), kind=kind).exists():
            continue
        try:
            with transaction.atomic():
                alert = ProfitAlert.objects.create(
                    **_key(order), kind=kind, detail=_detail(kind, f)[:300]
                )
        except IntegrityError:  # raised meanwhile by another run
            continue
        raised.append(alert)
    if raised:
        people = _recipients(order)
        for alert in raised:
            transaction.on_commit(
                lambda alert=alert: notify(
                    people,
                    "order_profit_alert",
                    title=f"{order.number}: {alert.get_kind_display().lower()}",
                    body=alert.detail,
                    link=link_of(order),
                )
            )
    return raised


def safe_check(order) -> None:
    """After a cost sync: an alert failing never blocks anything; the daily run catches up."""
    try:
        check_alerts(order)
    except Exception:  # noqa: BLE001
        log.exception("Profit alerts for %s failed", order)


def snapshot_open(day: date | None = None) -> int:
    """The daily snapshot of every open order (and its alerts). Run each evening; a second
    run on the same day adds nothing."""
    day = day or timezone.localdate()
    setting = _setting()
    made = 0
    for order in list(JobOrder.objects.filter(status__in=OPEN)) + list(
        ProductionOrder.objects.filter(status__in=OPEN)
    ):
        f = figures(order, setting)
        check_alerts(order, setting, f)
        if OrderProfitSnapshot.objects.filter(**_key(order), day=day).exists():
            continue
        OrderProfitSnapshot.objects.create(
            **_key(order),
            day=day,
            cost=f["cost"],
            earned=f["earned"],
            value=f["value"],
            complete_pct=f["complete_pct"],
            forecast_cost=f["forecast_cost"],
            forecast_margin=f["forecast_margin"],
            margin_pct=f["margin_pct"],
            status=f["status"],
        )
        made += 1
    return made


# --- Moulding view per machine and mould ----------------------------------------------------


def moulding_view(user: User, start: date, end: date) -> list[dict]:
    """Per machine and mould, over approved shift reports from `start` to `end`: good and
    rejected pieces, actual against standard cycle time, material per good piece, cost per
    good piece and the margin per 1,000 good pieces (orders for stock have no margin)."""
    if not can_see(user):
        raise ProfitError("You do not have access to order profitability.")
    runs = list(
        MouldingRun.objects.filter(
            report__status=ShiftReport.Status.APPROVED,
            report__day__gte=start,
            report__day__lte=end,
            order__division__in=division_scope(user),
        ).select_related("machine", "mould", "order__sales_line__order")
    )
    rejects = defaultdict(int)
    for run_id, q in RejectEntry.objects.filter(run__in=runs).values_list("run_id", "quantity"):
        rejects[run_id] += q
    run_costs = defaultdict(lambda: ZERO)
    for source, amount in OrderCost.objects.filter(
        source__in=[f"run:{r.pk}:{x}" for r in runs for x in ("labour", "overhead", "mould")]
    ).values_list("source", "amount"):
        run_costs[int(source.split(":")[1])] += amount
    material_per_piece = {}
    for order in {r.order for r in runs}:
        material = (
            OrderCost.objects.filter(production_order=order, element="material").aggregate(
                t=Sum("amount")
            )["t"]
            or ZERO
        )
        good, _ = costs._rejected(order)
        material_per_piece[order.pk] = material / good if good else ZERO
    groups: dict[tuple, dict] = {}
    for r in runs:
        g = groups.setdefault(
            (r.machine.code, r.mould.code),
            {
                "machine": r.machine.code,
                "mould": r.mould.code,
                "standard_cycle_s": r.mould.cycle_time_s,
                "good": ZERO,
                "rejected": 0,
                "shots": 0,
                "timed_shots": 0,
                "cycle_x_shots": ZERO,
                "material": ZERO,
                "cost": ZERO,
                "priced_good": ZERO,
                "priced_cost": ZERO,
                "revenue": ZERO,
                "orders": set(),
            },
        )
        good = r.good_quantity
        material = material_per_piece.get(r.order_id, ZERO) * good
        cost = material + run_costs[r.pk]
        g["good"] += good
        g["rejected"] += rejects[r.pk]
        g["shots"] += r.shots
        if r.actual_cycle_s:
            g["timed_shots"] += r.shots
            g["cycle_x_shots"] += r.actual_cycle_s * r.shots
        g["material"] += material
        g["cost"] += cost
        g["orders"].add(r.order.number)
        price = _price(r.order)
        if price is not None:
            g["priced_good"] += good
            g["priced_cost"] += cost
            g["revenue"] += price * good
    rows = []
    for g in sorted(groups.values(), key=lambda x: (x["machine"], x["mould"])):
        made = g["good"] + g["rejected"]
        actual = g["cycle_x_shots"] / g["timed_shots"] if g["timed_shots"] else None
        margin = None
        if g["priced_good"]:
            margin = (g["revenue"] - g["priced_cost"]) / g["priced_good"] * 1000
        rows.append(
            {
                "machine": g["machine"],
                "mould": g["mould"],
                "orders": sorted(g["orders"]),
                "good": f"{g['good'].normalize():f}",
                "rejected": g["rejected"],
                "reject_pct": _s(_pct(g["rejected"] / made * HUNDRED)) if made else None,
                "standard_cycle_s": str(g["standard_cycle_s"]),
                "actual_cycle_s": _s(_pct(actual)),
                "material_per_piece": _s(
                    (g["material"] / g["good"]).quantize(Decimal("0.0001"), ROUND_HALF_UP)
                )
                if g["good"]
                else None,
                "cost_per_1000": _s(_money(g["cost"] / g["good"] * 1000)) if g["good"] else None,
                "margin_per_1000": _s(_money(margin)),
            }
        )
    return rows
