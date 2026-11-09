"""Finished parts leaving stock on delivery (backlog P3-16 part 2; the owner's default of
3 Nov 2026: "no finished-goods stock until Phase 3").

- A delivery note line takes a finished part out of the order division's main store: by
  default the part of the line's job order or production order, or one chosen on the draft;
  none for tooling, services or parts not held in stock.
- When the note is issued, each such line leaves stock, lots oldest first, at the part's
  weighted average stock value (which since P3-16 holds its full production cost), and
  the value is charged to cost of sales: Dr Cost of finished goods sold, Cr the part's
  inventory account, in the order's division. Not enough in stock: the note is refused, as
  production must be approved (and so in stock) before it is delivered.
- Cancelling an issued note brings the parts back into the same lots at the same value and
  reverses the journal.
"""

from decimal import Decimal

from apps.accounting import journal
from apps.accounting.services import AccountingError

from . import issues
from .models import Item, StockMovement, Store
from .stock import StockError

ZERO = Decimal("0")
K = StockMovement.Kind


def part_for(order_line) -> Item | None:
    """The finished part of a sales order line: of its production orders, else its jobs."""
    from apps.production.models import JobOrder, ProductionOrder

    order = (
        ProductionOrder.objects.filter(sales_line=order_line)
        .exclude(status=ProductionOrder.Status.CANCELLED)
        .select_related("item")
        .first()
    )
    if order is not None:
        return order.item
    job = (
        JobOrder.objects.filter(sales_line=order_line, item__isnull=False)
        .exclude(status=JobOrder.Status.CANCELLED)
        .select_related("item")
        .first()
    )
    return job.item if job else None


def check_part(item: Item, where: str) -> Item:
    if item.category != Item.Category.FINISHED or not item.is_stock or not item.is_active:
        raise StockError(f"{where}: {item.code} is not an active finished part held in stock.")
    return item


def deliver(user, note) -> None:
    """Take the note's parts out of stock and charge their value to cost of sales."""
    order = note.order
    store = Store.objects.filter(
        division=order.division, kind=Store.Kind.MAIN, is_active=True
    ).first()
    lines = [x for x in note.lines.select_related("item", "order_line") if x.item_id]
    if not lines:
        return
    if store is None:
        raise StockError(f"Division {order.division.code} has no main store for finished parts.")
    Store.objects.select_for_update().filter(pk=store.pk).first()
    plan, taken = [], {}
    for x in lines:
        where = f"Line {x.order_line.line_no}"
        item = check_part(x.item, where)
        left, value_of_line = x.quantity, ZERO
        for lot, on_hand in issues.lots(item, store):
            used = sum((q for i, lot_, q, _ in plan if i.pk == item.pk and lot_ == lot), ZERO)
            free = on_hand - used
            if left <= 0 or free <= 0:
                continue
            part = min(free, left)
            so_far = taken.get(item.pk, (ZERO, ZERO))
            value = issues.take_value(item, part, so_far)
            plan.append((item, lot, part, value))
            taken[item.pk] = (so_far[0] + part, so_far[1] + value)
            value_of_line += value
            left -= part
        if left > 0:
            raise StockError(
                f"{where}: only {x.quantity - left:,.3f} {item.unit} of {item.code} is in "
                f"{store.code}. Approve its production first."
            )
        x.cost = value_of_line
        x.save(update_fields=["cost"])
    total = sum((v for *_, v in plan), ZERO)
    entry = None
    if total:
        by_item: dict[int, list] = {}
        for item, _, _, value in plan:
            by_item.setdefault(item.pk, [item, ZERO])[1] += value
        rows = [
            journal.Line(
                account=issues.system_account("finished_goods_sold", "Cost of finished goods sold"),
                debit=total,
                division=order.division,
                description=f"{note.number} {order.customer.name}",
            )
        ]
        for item, value in by_item.values():
            rows.append(
                journal.Line(
                    account=issues.inventory_account(item),
                    credit=value,
                    division=order.division,
                    description=f"{note.number} {item.code} {item.name}",
                )
            )
        try:
            entry = journal.post(
                user,
                entry_date=note.delivery_date,
                narration=f"Finished parts delivered: {note.number}, {order.number}",
                lines=rows,
                source_type="delivery_note",
                source_id=note.number,
            )
        except AccountingError as error:
            raise StockError(str(error)) from None
    for item, lot, part, value in plan:
        StockMovement.objects.create(
            item=item,
            store=store,
            division=store.division,
            lot_no=lot,
            kind=K.DELIVERED,
            movement_date=note.delivery_date,
            quantity=-part,
            value=-value,
            journal_entry=entry,
            created_by=user,
        )
    note.cost_entry = entry


def undeliver(user, note, reason: str) -> None:
    """A cancelled note: its parts come back into the same lots at the same value."""
    if note.cost_entry_id is None and not note.lines.filter(item__isnull=False).exists():
        return
    taken = (
        StockMovement.objects.filter(kind=K.DELIVERED, journal_entry=note.cost_entry)
        if note.cost_entry_id
        else StockMovement.objects.none()
    )
    reversal = None
    if note.cost_entry_id:
        try:
            reversal = journal.reverse(
                user, note.cost_entry, reason=f"Delivery note cancelled: {reason}"
            )
        except AccountingError as error:
            raise StockError(str(error)) from None
    for m in taken:
        StockMovement.objects.create(
            item=m.item,
            store=m.store,
            division=m.division,
            lot_no=m.lot_no,
            kind=K.UNDELIVERED,
            movement_date=note.delivery_date,
            quantity=-m.quantity,
            value=-m.value,
            journal_entry=reversal,
            created_by=user,
        )
