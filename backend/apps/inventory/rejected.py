"""Goods waiting in the rejected stores (owner, 22 Nov 2026, from his testing): rejected and
damaged goods are to go back to the supplier within 14 days. This lists every lot still in a
division's rejected store, oldest first, with how long it has waited, and tells the stores
person and purchasing of the division once when a lot has waited longer than that.

A lot's waiting starts on the day it first went into the rejected store; it ends when the
lot leaves (returned to the supplier, or written off). Part of a lot returned leaves the
rest still waiting from the same day.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.core.models import Division, Notification

from .models import StockMovement, Store

DAYS = 14  # the owner's target: rejected goods go back within 14 days
EVENT = "rejected_stock_waiting"


def lots(movements: QuerySet[StockMovement] | None = None, *, today: date | None = None):
    """Every lot on hand in a rejected store: item, store, lot, quantity, the day it came in,
    the days it has waited, and the GRN it came from. Oldest first."""
    today = today or timezone.localdate()
    if movements is None:
        movements = StockMovement.objects.all()
    found = movements.filter(store__kind=Store.Kind.REJECTED).select_related(
        "item",
        "store",
        "store__division",
        "receipt_line__receipt__supplier",
        "receipt_line__receipt__purchase_order",
    )
    groups: dict[tuple, list[StockMovement]] = defaultdict(list)
    for movement in found.order_by("movement_date", "id"):
        groups[(movement.item_id, movement.store_id, movement.lot_no)].append(movement)
    rows = []
    for moves in groups.values():
        quantity = sum((m.quantity for m in moves), Decimal("0"))
        if quantity <= 0:
            continue
        first = next(m for m in moves if m.quantity > 0)
        source = next((m.receipt_line for m in moves if m.receipt_line_id), None)
        grn = source.receipt if source else None
        waited = (today - first.movement_date).days
        rows.append(
            {
                "item": first.item,
                "store": first.store,
                "lot_no": first.lot_no,
                "quantity": quantity,
                "since": first.movement_date,
                "days": waited,
                "over": waited > DAYS,
                "grn": grn,
            }
        )
    rows.sort(key=lambda r: (r["since"], r["store"].code, r["item"].code, r["lot_no"]))
    return rows


def _title(row) -> str:
    return (
        f"{row['item'].code} lot {row['lot_no']} has waited over {DAYS} days in {row['store'].code}"
    )


def remind(*, today: date | None = None) -> int:
    """Tell the stores person and purchasing of the division, once per lot, when a lot has
    waited in the rejected store longer than 14 days. Returns how many lots were told."""
    from apps.core.notifications import notify
    from apps.purchasing.requests import _people

    told = 0
    for row in lots(today=today):
        if not row["over"]:
            continue
        title = _title(row)
        if Notification.objects.filter(event=EVENT, title=title[:200]).exists():
            continue
        grn = row["grn"]
        where = f" from {grn.number} ({grn.supplier.name})" if grn else ""
        division: Division = row["store"].division
        with transaction.atomic():
            notify(
                _people(division),
                EVENT,
                title=title,
                body=f"{row['quantity'].normalize():f} {row['item'].unit} of "
                f"{row['item'].name}{where}, in the rejected store since "
                f"{row['since']:%d/%m/%Y} ({row['days']} days). Return it to the supplier.",
                link="/purchasing/reports?tab=rejected",
            )
        told += 1
    return told
