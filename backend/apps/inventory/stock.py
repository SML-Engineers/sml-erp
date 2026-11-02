"""Stock movements and valuation (backlog P16-09, spec 5A.3, IAS 2).

- Confirming a GRN puts the good quantity into the division's quarantine store and the
  damaged quantity into its rejected store, lot by lot, at no value: nothing is on the books
  until QC accepts it.
- QC's decision moves the goods out of quarantine: the accepted quantity into the division's
  main store at the PO price in LKR (at the exchange rate of the receipt date, IAS 21), the
  rejected quantity into the rejected store at no value. The accepted value is posted Dr the
  item's inventory account, Cr Goods received not invoiced (system account), in the same
  transaction (rule 2).
- Reversing a GRN takes everything it put in back out, and reverses its journal entries.
- Movements are never changed or deleted (database guard). Balances and the weighted average
  cost are worked out from them: value on hand ÷ quantity on hand in the main stores.
- Non-stock items have no stock movements; they are expensed when invoiced (P16-10).
"""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import QuerySet, Sum
from django.utils import timezone

from apps.accounting import journal
from apps.accounting.models import Account, JournalEntry
from apps.accounting.services import AccountingError
from apps.core.models import User

from .models import GoodsReceipt, GoodsReceiptLine, IncomingInspection, Item, StockMovement, Store

K = StockMovement.Kind
CENT = Decimal("0.01")


class StockError(Exception):
    pass


def _store(division, kind: str) -> Store:
    stores = Store.objects.filter(division=division, kind=kind, is_active=True)
    store = stores.filter(code=f"{division.code}-MAIN").first() if kind == Store.Kind.MAIN else None
    store = store or stores.order_by("code").first()
    if store is None:
        name = {"main": "main", "quarantine": "quarantine", "rejected": "rejected"}[kind]
        raise StockError(
            f"Division {division.code} has no active {name} store (Settings → Stores)."
        )
    return store


def receipt_rate(grn: GoodsReceipt) -> Decimal:
    """The exchange rate the goods of a GRN are valued at: the receipt date's (IAS 21), or the
    PO's for GRNs confirmed before rates were kept per GRN."""
    return grn.exchange_rate or grn.purchase_order.exchange_rate


def unit_cost(line: GoodsReceiptLine) -> Decimal:
    """The PO price of one unit in LKR, at the receipt date's rate."""
    return line.po_line.unit_price * receipt_rate(line.receipt)


def _lots(line: GoodsReceiptLine, *, rejected_ids=frozenset(), whole_rejected=False):
    """(lot number, quantity, damaged, rejected by QC) for each package, or one lot for a line
    received without packages."""
    packages = list(line.packages.all())
    if packages:
        return [
            (
                p.lot_no,
                p.quantity or Decimal("0"),
                p.damaged,
                whole_rejected or p.pk in rejected_ids,
            )
            for p in packages
        ]
    return [(f"{line.receipt.number}-{line.line_no}", None, False, False)]


def _move(user, line, store, kind, lot, quantity, value=Decimal("0"), entry=None, day=None):
    if quantity == 0:
        return None
    return StockMovement.objects.create(
        item=line.item,
        store=store,
        division=line.receipt.division,
        lot_no=lot,
        kind=kind,
        movement_date=day or timezone.localdate(),
        quantity=quantity,
        value=value,
        receipt_line=line,
        journal_entry=entry,
        created_by=user,
    )


def receive(user: User, grn: GoodsReceipt) -> None:
    """Called when a GRN is confirmed."""
    quarantine = _store(grn.division, Store.Kind.QUARANTINE)
    rejected = _store(grn.division, Store.Kind.REJECTED)
    for line in grn.lines.select_related("item", "receipt__division"):
        if not line.item.is_stock or line.received_quantity == 0:
            continue
        lots = _lots(line)
        if lots[0][1] is None:  # no packages
            lot = lots[0][0]
            _move(user, line, quarantine, K.RECEIVED, lot, line.good_quantity, day=grn.receipt_date)
            _move(user, line, rejected, K.DAMAGED, lot, line.damaged_quantity, day=grn.receipt_date)
            continue
        for lot, quantity, damaged, _ in lots:
            store, kind = (rejected, K.DAMAGED) if damaged else (quarantine, K.RECEIVED)
            _move(user, line, store, kind, lot, quantity, day=grn.receipt_date)


def _grni() -> Account:
    account = Account.objects.filter(system_role="grni", is_active=True).first()
    if account is None:
        raise StockError(
            "There is no active Goods received not invoiced account (Chart of accounts)."
        )
    return account


def decide(user: User, inspection: IncomingInspection) -> None:
    """Called when QC's decision is final: move the goods out of quarantine and post the
    accepted value."""
    line = GoodsReceiptLine.objects.select_related(
        "item__inventory_account",
        "receipt__division",
        "receipt__supplier",
        "po_line",
        "receipt__purchase_order",
    ).get(pk=inspection.line_id)
    item = line.item
    if not item.is_stock:
        return
    grn = line.receipt
    quarantine = _store(grn.division, Store.Kind.QUARANTINE)
    main = _store(grn.division, Store.Kind.MAIN)
    rejected = _store(grn.division, Store.Kind.REJECTED)
    cost = unit_cost(line)
    whole = inspection.decision == IncomingInspection.Decision.REJECTED
    rejected_ids = frozenset(inspection.rejected_packages.values_list("package_id", flat=True))
    lots = _lots(line, rejected_ids=rejected_ids, whole_rejected=whole)
    moves = []  # (store, kind, lot, quantity, value)
    if lots[0][1] is None:
        lot = lots[0][0]
        moves.append((quarantine, K.ACCEPTED, lot, -line.good_quantity, Decimal("0")))
        accepted = inspection.accepted_quantity
        moves.append(
            (main, K.ACCEPTED, lot, accepted, (accepted * cost).quantize(CENT, ROUND_HALF_UP))
        )
        moves.append((rejected, K.REJECTED, lot, inspection.rejected_quantity, Decimal("0")))
    else:
        for lot, quantity, damaged, is_rejected in lots:
            if damaged:
                continue
            kind = K.REJECTED if is_rejected else K.ACCEPTED
            moves.append((quarantine, kind, lot, -quantity, Decimal("0")))
            if is_rejected:
                moves.append((rejected, K.REJECTED, lot, quantity, Decimal("0")))
            else:
                value = (quantity * cost).quantize(CENT, ROUND_HALF_UP)
                moves.append((main, K.ACCEPTED, lot, quantity, value))
    total = sum((value for *_, value in moves), Decimal("0"))
    entry = None
    if total > 0:
        if item.inventory_account is None:
            raise StockError(f"Item {item.code} has no inventory account (the Accountant sets it).")
        try:
            entry = journal.post(
                user,
                entry_date=timezone.localdate(),
                narration=(
                    f"QC accepted {item.code} on {grn.number} from {grn.supplier.name} "
                    f"(PO {grn.purchase_order.label})"
                ),
                lines=[
                    journal.Line(
                        account=item.inventory_account,
                        debit=total,
                        division=grn.division,
                        description=f"{item.code} {item.name}",
                    ),
                    journal.Line(
                        account=_grni(),
                        credit=total,
                        division=grn.division,
                        supplier=grn.supplier,
                        description=f"{grn.number} {item.code}",
                    ),
                ],
                source_type="goods_receipt",
                source_id=grn.number,
            )
        except AccountingError as error:
            raise StockError(str(error)) from None
    for store, kind, lot, quantity, value in moves:
        _move(user, line, store, kind, lot, quantity, value, entry=entry if value else None)


def reverse(user: User, grn: GoodsReceipt, reason: str) -> None:
    """Called when the Director approves a GRN's reversal: take out what it put in, store by
    store and lot by lot, and reverse its journal entries."""
    movements = StockMovement.objects.filter(receipt_line__receipt=grn)
    reversals = {}
    for entry_id in set(
        movements.exclude(journal_entry=None).values_list("journal_entry", flat=True)
    ):
        entry = JournalEntry.objects.get(pk=entry_id)
        try:
            reversals[entry_id] = journal.reverse(
                user, entry, reason=f"GRN {grn.number} reversed: {reason}"
            )
        except AccountingError as error:
            raise StockError(str(error)) from None
    rows = (
        movements.values("receipt_line", "store", "lot_no", "journal_entry")
        .annotate(quantity=Sum("quantity"), value=Sum("value"))
        .order_by("receipt_line", "store", "lot_no")
    )
    lines = {line.pk: line for line in grn.lines.select_related("item", "receipt__division")}
    stores = {s.pk: s for s in Store.objects.filter(pk__in={row["store"] for row in rows})}
    for row in rows:
        if row["quantity"] == 0:
            continue
        _move(
            user,
            lines[row["receipt_line"]],
            stores[row["store"]],
            K.REVERSED,
            row["lot_no"],
            -row["quantity"],
            -row["value"],
            entry=reversals.get(row["journal_entry"]),
        )


# --- Balances --------------------------------------------------------------------------------


def balances(movements: QuerySet[StockMovement], *, by_lot: bool = False) -> list[dict]:
    """Quantity and value on hand per item and store (and lot), from the movements."""
    keys = ["item", "store"] + (["lot_no"] if by_lot else [])
    rows = (
        movements.values(*keys)
        .annotate(quantity=Sum("quantity"), value=Sum("value"))
        .exclude(quantity=0, value=0)
        .order_by(*keys)
    )
    return list(rows)


def average_costs(movements: QuerySet[StockMovement]) -> dict[int, Decimal]:
    """Weighted average cost per item: value ÷ quantity in the main stores."""
    totals = defaultdict(lambda: [Decimal("0"), Decimal("0")])
    rows = (
        movements.filter(store__kind=Store.Kind.MAIN)
        .values("item")
        .annotate(quantity=Sum("quantity"), value=Sum("value"))
    )
    for row in rows:
        totals[row["item"]][0] += row["quantity"]
        totals[row["item"]][1] += row["value"]
    return {
        item: (value / quantity).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        for item, (quantity, value) in totals.items()
        if quantity > 0
    }


def on_hand(item: Item, store: Store | None = None) -> Decimal:
    rows = StockMovement.objects.filter(item=item)
    if store is not None:
        rows = rows.filter(store=store)
    return rows.aggregate(total=Sum("quantity"))["total"] or Decimal("0")
