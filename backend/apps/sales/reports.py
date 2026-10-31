"""Sales reports (backlog P15-11, spec 5): the quotation register, win / loss with reasons,
quotations needing attention (awaiting approval, expiring this week), open sales orders and
their delivery dates, and advances received and not yet set off.

Each report gives rows for the screen and for Excel and PDF (apps.core.exports), so they
always agree. A user sees only their divisions, and a Sales Executive only their own
quotations and orders (the same rules as the lists, services.visible and orders.visible).
"""

from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.exports import Column
from apps.core.models import ApprovalState, User

from . import orders, services
from .models import CustomerAdvance, DeliverySchedule, OutcomeReason, Quotation, SalesOrder

ZERO = Decimal("0.00")
EXPIRY_DAYS = 7  # "expiring this week"
OPEN_ORDERS = (SalesOrder.Status.OPEN, SalesOrder.Status.PARTLY_DELIVERED)
LIVE = (Quotation.Status.APPROVED, Quotation.Status.SENT)
QUOTE = "quotation"  # workflow.DOC


def _money(value) -> str:
    return f"{(value or ZERO):.2f}"


def _in_period(rows: QuerySet, field: str, start: date | None, end: date | None) -> QuerySet:
    if start:
        rows = rows.filter(**{f"{field}__gte": start})
    if end:
        rows = rows.filter(**{f"{field}__lte": end})
    return rows


def _division(rows: QuerySet, division: str) -> QuerySet:
    return rows.filter(division__code=division.upper()) if division else rows


# --- Quotation register ----------------------------------------------------------------------

REGISTER_COLUMNS = [
    Column("label", "Quotation", width=1.4),
    Column("quote_date", "Date", "date"),
    Column("valid_until", "Valid until", "date"),
    Column("division", "Division", width=0.6),
    Column("customer", "Customer", width=2),
    Column("salesperson", "Salesperson", width=1.2),
    Column("status", "Status", width=1.1),
    Column("reason", "Won / lost because", width=1.4),
    Column("total", "Total", width=1.2),
    Column("total_lkr", "Total (LKR)", "money"),
]


def register(
    user: User,
    *,
    start: date | None = None,
    end: date | None = None,
    status: str = "",
    customer: str = "",
    division: str = "",
    salesperson: str = "",
) -> list[dict]:
    """Quotations by date, filtered by status, customer, division and salesperson (the
    person who made it). Revised quotations show as "Replaced by a revision"."""
    rows = _division(_in_period(services.visible(user), "quote_date", start, end), division)
    if status:
        rows = rows.filter(status__in=status.split(","))
    if customer.isdigit():
        rows = rows.filter(customer_id=int(customer))
    if salesperson.isdigit():
        rows = rows.filter(created_by_id=int(salesperson))
    rows = rows.select_related("division", "customer", "currency", "created_by").order_by(
        "-quote_date", "-number", "-revision"
    )
    return [
        {
            "id": q.pk,
            "label": q.label,
            "quote_date": q.quote_date,
            "valid_until": q.valid_until,
            "division": q.division.code,
            "customer_id": q.customer_id,
            "customer": q.customer.name,
            "salesperson_id": q.created_by_id,
            "salesperson": q.created_by.full_name,
            "status": q.get_status_display(),
            "status_code": q.status,
            "reason": q.get_outcome_reason_display() if q.outcome_reason else "",
            "currency": q.currency.code,
            "total": f"{q.currency.code} {q.total_amount:,.2f}",
            "total_amount": _money(q.total_amount),
            "total_lkr": _money(q.total_lkr),
        }
        for q in rows[:5000]
    ]


def register_summary(rows: list[dict]) -> list[dict]:
    """How many quotations, and their value in LKR, per status."""
    summary: OrderedDict[str, dict] = OrderedDict(
        (code, {"status_code": code, "status": name, "count": 0, "total_lkr": ZERO})
        for code, name in Quotation.Status.choices
    )
    for row in rows:
        entry = summary[row["status_code"]]
        entry["count"] += 1
        entry["total_lkr"] += Decimal(row["total_lkr"])
    return [
        {**entry, "total_lkr": _money(entry["total_lkr"])}
        for entry in summary.values()
        if entry["count"]
    ]


def salespeople(user: User) -> list[dict]:
    """The people who made the quotations the user can see, for the register's filter."""
    seen = (
        services.visible(user)
        .values_list("created_by_id", "created_by__full_name")
        .distinct()
        .order_by("created_by__full_name")
    )
    return [{"id": pk, "name": name} for pk, name in seen]


# --- Win / loss with reasons ------------------------------------------------------------------

WIN_LOSS_COLUMNS = [
    Column("label", "Quotation", width=1.4),
    Column("decided", "Decided", "date"),
    Column("division", "Division", width=0.6),
    Column("customer", "Customer", width=2),
    Column("salesperson", "Salesperson", width=1.2),
    Column("outcome", "Outcome", width=0.7),
    Column("reason", "Reason", width=1.6),
    Column("note", "Note", width=2),
    Column("total_lkr", "Total (LKR)", "money"),
]


def win_loss(
    user: User, *, start: date | None = None, end: date | None = None, division: str = ""
) -> list[dict]:
    """Quotations won or lost in the period (by the day the outcome was recorded)."""
    rows = _division(
        services.visible(user).filter(
            status__in=(Quotation.Status.ACCEPTED, Quotation.Status.LOST)
        ),
        division,
    ).select_related("division", "customer", "created_by")
    result = []
    for q in rows.order_by("-outcome_at", "-id"):
        decided = timezone.localtime(q.outcome_at).date() if q.outcome_at else q.quote_date
        if (start and decided < start) or (end and decided > end):
            continue
        result.append(
            {
                "id": q.pk,
                "label": q.label,
                "decided": decided,
                "division": q.division.code,
                "customer": q.customer.name,
                "salesperson": q.created_by.full_name,
                "outcome": "Won" if q.status == Quotation.Status.ACCEPTED else "Lost",
                "won": q.status == Quotation.Status.ACCEPTED,
                "reason_code": q.outcome_reason,
                "reason": q.get_outcome_reason_display() if q.outcome_reason else "",
                "note": q.outcome_note,
                "total_lkr": _money(q.total_lkr),
            }
        )
    return result


def _rate(won: int, decided: int) -> str | None:
    return None if decided == 0 else f"{Decimal(won * 100) / decided:.1f}"


def win_loss_summary(rows: list[dict]) -> dict:
    """Won and lost per reason and per salesperson, with the win rate by count and value."""

    def blank():
        return {"won": 0, "won_lkr": ZERO, "lost": 0, "lost_lkr": ZERO}

    def add(entry, row):
        side = "won" if row["won"] else "lost"
        entry[side] += 1
        entry[f"{side}_lkr"] += Decimal(row["total_lkr"])

    def out(entry):
        return {
            **entry,
            "won_lkr": _money(entry["won_lkr"]),
            "lost_lkr": _money(entry["lost_lkr"]),
            "win_rate": _rate(entry["won"], entry["won"] + entry["lost"]),
        }

    total = blank()
    reasons = {code: blank() for code, _ in OutcomeReason.choices}
    people: dict[str, dict] = {}
    for row in rows:
        add(total, row)
        if row["reason_code"] in reasons:
            add(reasons[row["reason_code"]], row)
        add(people.setdefault(row["salesperson"], blank()), row)
    value = total["won_lkr"] + total["lost_lkr"]
    return {
        "total": {
            **out(total),
            "value_win_rate": None if not value else f"{total['won_lkr'] * 100 / value:.1f}",
        },
        "by_reason": [
            {"reason_code": code, "reason": name, **out(reasons[code])}
            for code, name in OutcomeReason.choices
            if reasons[code]["won"] or reasons[code]["lost"]
        ],
        "by_salesperson": [{"salesperson": name, **out(people[name])} for name in sorted(people)],
    }


# --- Quotations needing attention ------------------------------------------------------------

ATTENTION_COLUMNS = [
    Column("label", "Quotation", width=1.4),
    Column("why", "Needs", width=1.6),
    Column("date", "Since / until", "date"),
    Column("days", "Days", "number", width=0.5),
    Column("division", "Division", width=0.6),
    Column("customer", "Customer", width=2),
    Column("salesperson", "Salesperson", width=1.2),
    Column("total_lkr", "Total (LKR)", "money"),
]


def attention(user: User, *, division: str = "") -> list[dict]:
    """Quotations awaiting the Director's approval (oldest first), then approved or sent
    quotations that expire within a week (soonest first)."""
    today = timezone.localdate()
    rows = _division(services.visible(user), division).select_related(
        "division", "customer", "created_by"
    )
    result = []
    waiting = rows.filter(status=Quotation.Status.AWAITING_APPROVAL)
    states = {
        s.document_id: s
        for s in ApprovalState.objects.filter(
            document_type=QUOTE,
            document_id__in=[q.pk for q in waiting],
        )
    }
    for q in waiting:
        state = states.get(q.pk)
        last = approvals.history(QUOTE, q.pk).order_by("-acted_at", "-id").first()
        since = timezone.localtime(last.acted_at).date() if last else q.quote_date
        result.append(
            {
                "id": q.pk,
                "kind": "approval",
                "label": q.label,
                "why": "Director's approval",
                "approvers": ", ".join(p.full_name for p in approvals.approvers(state))
                if state
                else "",
                "date": since,
                "days": (today - since).days,
                "division": q.division.code,
                "customer": q.customer.name,
                "salesperson": q.created_by.full_name,
                "total_lkr": _money(q.total_lkr),
            }
        )
    result.sort(key=lambda r: (r["date"], r["label"]))
    expiring = rows.filter(
        status__in=LIVE, valid_until__gte=today, valid_until__lte=today + timedelta(EXPIRY_DAYS)
    ).order_by("valid_until", "number")
    for q in expiring:
        result.append(
            {
                "id": q.pk,
                "kind": "expiring",
                "label": q.label,
                "why": f"Expires ({q.get_status_display().lower()}, no answer yet)",
                "approvers": "",
                "date": q.valid_until,
                "days": (q.valid_until - today).days,
                "division": q.division.code,
                "customer": q.customer.name,
                "salesperson": q.created_by.full_name,
                "total_lkr": _money(q.total_lkr),
            }
        )
    return result


# --- Open sales orders and their delivery dates ----------------------------------------------

ORDER_COLUMNS = [
    Column("due_date", "Due", "date"),
    Column("number", "Order", width=1.1),
    Column("customer", "Customer", width=1.8),
    Column("customer_po", "Customer PO", width=1.1),
    Column("division", "Division", width=0.6),
    Column("item", "Item", width=2.2),
    Column("quantity", "Quantity", width=0.9),
    Column("status", "Due status", width=0.8),
    Column("value_lkr", "Value (LKR)", "money"),
]


def open_orders(
    user: User, *, division: str = "", customer: str = "", until: date | None = None
) -> list[dict]:
    """Every delivery still to make on open orders, by due date; overdue ones are marked.
    The value is the delivery's share of its line (net of discount, before tax), in LKR."""
    today = timezone.localdate()
    order_rows = _division(orders.visible(user).filter(status__in=OPEN_ORDERS), division)
    if customer.isdigit():
        order_rows = order_rows.filter(customer_id=int(customer))
    deliveries = (
        DeliverySchedule.objects.filter(line__order__in=order_rows)
        .select_related("line__order__customer", "line__order__division")
        .order_by("due_date", "line__order__number", "line__line_no", "seq")
    )
    if until:
        deliveries = deliveries.filter(due_date__lte=until)
    result = []
    for d in deliveries:
        line, order = d.line, d.line.order
        net = line.amount - line.discount
        share = net * d.quantity / line.quantity if line.quantity else ZERO
        rate = (order.total_lkr / order.total_amount) if order.total_amount else Decimal("1")
        result.append(
            {
                "id": order.pk,
                "due_date": d.due_date,
                "number": order.number,
                "customer": order.customer.name,
                "customer_po": order.customer_po,
                "division": order.division.code,
                "item": line.description,
                "quantity": f"{d.quantity.normalize():,f} {line.unit}",
                "overdue": d.due_date < today,
                "status": "Overdue"
                if d.due_date < today
                else ("This week" if d.due_date <= today + timedelta(7) else ""),
                "value_lkr": _money((share * rate).quantize(Decimal("0.01"))),
            }
        )
    return result


# --- Advances received and not yet set off ---------------------------------------------------

ADVANCE_COLUMNS = [
    Column("number", "Receipt", width=1.1),
    Column("receipt_date", "Date", "date"),
    Column("customer", "Customer", width=2),
    Column("against", "Against", width=1.4),
    Column("division", "Division", width=0.6),
    Column("amount", "Received", width=1.2),
    Column("amount_lkr", "Received (LKR)", "money"),
    Column("set_off_lkr", "Set off (LKR)", "money"),
    Column("balance_lkr", "Balance (LKR)", "money"),
]


def _visible_advances(user: User) -> QuerySet[CustomerAdvance]:
    """The Cashier, Accountant and Director (Payments and receipts) and the Sales Manager see
    all advances of their divisions; a Sales Executive those against their own documents."""
    access = effective_access(user)
    rows = CustomerAdvance.objects.filter(division__in=division_scope(user))
    if access.has("payments", "view") or (access.has("sales", "view") and services.sees_all(user)):
        return rows
    if not access.has("sales", "view"):
        return CustomerAdvance.objects.none()
    return rows.filter(
        Q(quotation__created_by=user)
        | Q(proforma__created_by=user)
        | Q(sales_order__created_by=user)
    )


def advances_open(user: User, *, division: str = "", customer: str = "") -> list[dict]:
    """Approved advances with something still to set off against invoices (Phase 2)."""
    rows = _division(
        _visible_advances(user).filter(status=CustomerAdvance.Status.APPROVED), division
    )
    if customer.isdigit():
        rows = rows.filter(customer_id=int(customer))
    rows = rows.select_related(
        "customer", "division", "currency", "quotation", "proforma", "sales_order"
    ).order_by("receipt_date", "number")
    result = []
    for a in rows:
        balance = a.amount_lkr - a.set_off_lkr
        if balance <= 0:
            continue
        against = (
            a.sales_order.number
            if a.sales_order_id
            else a.proforma.number
            if a.proforma_id
            else a.quotation.label
            if a.quotation_id
            else ""
        )
        result.append(
            {
                "id": a.pk,
                "number": a.number,
                "receipt_date": a.receipt_date,
                "customer": a.customer.name,
                "against": against,
                "division": a.division.code,
                "amount": f"{a.currency.code} {a.amount:,.2f}",
                "amount_lkr": _money(a.amount_lkr),
                "set_off_lkr": _money(a.set_off_lkr),
                "balance_lkr": _money(balance),
            }
        )
    return result


# --- The sales tiles on the dashboard --------------------------------------------------------


def dashboard(user: User, division: str = "") -> dict:
    """Figures for the home page. Each one is worked out by the report or list it opens, so a
    tile and its list always agree."""
    division = (division or "").upper()
    today = timezone.localdate()
    month = today.replace(day=1)
    quotes = _division(services.visible(user), division)
    waiting_ids = [s.document_id for s in approvals.waiting_for(user, QUOTE)]
    waiting = quotes.filter(pk__in=waiting_ids)
    needing = attention(user, division=division)
    live = quotes.filter(status__in=LIVE)
    decided = win_loss_summary(win_loss(user, start=month, end=today, division=division))
    deliveries = open_orders(user, division=division, until=today + timedelta(7))
    orders_open = _division(orders.visible(user).filter(status__in=OPEN_ORDERS), division)
    order_waiting_ids = [s.document_id for s in approvals.waiting_for(user, orders.DOC)]
    advances = advances_open(user, division=division)

    def total(rows, field="total_lkr"):
        return _money(sum((getattr(r, field) for r in rows), ZERO))

    return {
        "division": division,
        "divisions": [
            {"code": d.code, "name": d.name}
            for d in division_scope(user).filter(division_type="production").order_by("code")
        ],
        "can_approve": effective_access(user).has("sales", "approve")
        or bool(waiting_ids or order_waiting_ids),
        "can_enter": services.can_enter(user),
        "waiting_for_me": {
            "count": waiting.count() + len(order_waiting_ids),
            "quotations": waiting.count(),
            "orders": len(order_waiting_ids),
            "total": total(waiting),
        },
        "awaiting_approval": sum(1 for r in needing if r["kind"] == "approval"),
        "expiring": sum(1 for r in needing if r["kind"] == "expiring"),
        "live": {"count": live.count(), "total": total(live)},
        "this_month": {"from": month.isoformat(), "to": today.isoformat(), **decided["total"]},
        "open_orders": {"count": orders_open.count(), "total": total(orders_open)},
        "deliveries": {
            "overdue": sum(1 for r in deliveries if r["overdue"]),
            "this_week": sum(1 for r in deliveries if not r["overdue"]),
        },
        "advances": {
            "count": len(advances),
            "balance": _money(sum((Decimal(r["balance_lkr"]) for r in advances), ZERO)),
        },
    }
