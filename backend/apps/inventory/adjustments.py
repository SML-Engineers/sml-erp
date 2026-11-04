"""Stock adjustments, write-offs and stock counts (backlog P2-18, spec 6, IAS 2).

- The stores person (or the Accountant) prepares an adjustment for a main store: stock found
  (+) or lost (−), or a write-off (damaged, expired, obsolete: − only), each line with its lot,
  and a reason. Nothing moves until the Director approves it through the approval engine
  (never its author). Approval posts it: stock leaving at the weighted average cost (the last
  of an item takes exactly the value left), stock found at the average cost or, for an item
  the stores have never held, the cost typed on the line; Dr/Cr the item's inventory account
  against Stock adjustments and write-offs.
- A stock count lists, for a main store, what the books say per item and lot on the count
  date; the counted quantities are typed in (items found that the books do not have can be
  added). Submitting it makes an adjustment of the differences, sent to the Director at once;
  no differences closes the count as agreed.
- Opening stock at go-live is loaded from its own count sheet (Stores → Opening stock, P16-15).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import QuerySet, Sum
from django.utils import timezone

from apps.accounting import journal
from apps.accounting.services import AccountingError
from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User
from apps.core.numbering import NumberSeriesError, allocate

from . import items as item_master
from .issues import (
    CENT,
    COST,
    ZERO,
    _day,
    cost_of,
    inventory_account,
    main_store,
    main_totals,
    system_account,
)
from .models import (
    Item,
    StockAdjustment,
    StockAdjustmentLine,
    StockCount,
    StockCountLine,
    StockMovement,
)
from .stock import StockError

DOC = "stock_adjustment"
St = StockAdjustment.Status
Kind = StockAdjustment.Kind
QTY = Decimal("0.001")
MAX_LINES = 500


def can_prepare(user: User) -> bool:
    access = effective_access(user)
    return access.has("stores", "enter") or access.has("accounting", "enter")


def visible(user: User) -> QuerySet[StockAdjustment]:
    access = effective_access(user)
    if not (access.has("stores", "view") or access.has("accounting", "view")):
        return StockAdjustment.objects.none()
    return StockAdjustment.objects.filter(store__division__in=division_scope(user))


def _signed(value, where: str) -> Decimal:
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise StockError(f"{where}: the quantity is not a number.") from None
    if not number.is_finite() or number == 0 or number != number.quantize(QTY):
        raise StockError(f"{where}: the quantity must not be 0, with at most 3 decimals.")
    return number


@dataclass
class LineInput:
    item: Item | None
    quantity: object
    lot_no: str = ""
    unit_cost: object = None
    notes: str = ""


def _fill(adjustment: StockAdjustment, lines: list[LineInput]) -> None:
    if not lines:
        raise StockError("Add at least one line.")
    if len(lines) > MAX_LINES:
        raise StockError(f"An adjustment can have at most {MAX_LINES} lines.")
    checked = []
    for n, line in enumerate(lines, start=1):
        where = f"Line {n}"
        if not isinstance(line.item, Item) or not line.item.is_stock:
            raise StockError(f"{where}: choose a stock item.")
        quantity = _signed(line.quantity, where)
        if adjustment.kind == Kind.WRITE_OFF and quantity > 0:
            raise StockError(f"{where}: a write-off only takes stock out (a minus quantity).")
        cost = None
        if line.unit_cost not in (None, ""):
            try:
                cost = Decimal(str(line.unit_cost).replace(",", ""))
            except InvalidOperation:
                raise StockError(f"{where}: the cost is not a number.") from None
            if not cost.is_finite() or cost <= 0:
                raise StockError(f"{where}: the cost must be more than 0.")
            cost = cost.quantize(COST, ROUND_HALF_UP)
        lot = (line.lot_no or "").strip()[:40]
        if not lot:
            raise StockError(f"{where}: give the lot number.")
        checked.append((line.item, quantity, lot, cost, (line.notes or "").strip()[:300]))
    adjustment.lines.all().delete()
    for n, (item, quantity, lot, cost, notes) in enumerate(checked, start=1):
        StockAdjustmentLine.objects.create(
            adjustment=adjustment,
            line_no=n,
            item=item,
            quantity=quantity,
            lot_no=lot,
            unit_cost=cost,
            notes=notes,
        )


def create(
    user: User, *, store, kind: str, reason: str, lines: list[LineInput], adjustment_date=None
) -> StockAdjustment:
    if not can_prepare(user):
        raise StockError("Only the stores person or the Accountant prepares stock adjustments.")
    store = main_store(user, store)
    if kind not in (Kind.ADJUSTMENT, Kind.WRITE_OFF):
        raise StockError("Choose an adjustment or a write-off.")
    reason = (reason or "").strip()
    if not reason:
        raise StockError("Give the reason for the adjustment.")
    day = _day(adjustment_date or timezone.localdate())
    with audit_context("stock_adjustment_created"), transaction.atomic():
        try:
            number = allocate(DOC, on_date=day)
        except NumberSeriesError as error:
            raise StockError(str(error)) from None
        adjustment = StockAdjustment.objects.create(
            number=number,
            kind=kind,
            store=store,
            adjustment_date=day,
            reason=reason[:2000],
            created_by=user,
        )
        _fill(adjustment, lines)
        return adjustment


def save(user: User, adjustment: StockAdjustment, *, reason: str, lines: list[LineInput]):
    with audit_context("stock_adjustment_changed"), transaction.atomic():
        adjustment = StockAdjustment.objects.select_for_update().get(pk=adjustment.pk)
        if adjustment.status != St.DRAFT or adjustment.created_by_id != user.pk:
            raise StockError("Only the person who prepared a draft adjustment changes it.")
        if adjustment.count_id:
            raise StockError("The differences of a count are changed by counting again.")
        reason = (reason or "").strip()
        if not reason:
            raise StockError("Give the reason for the adjustment.")
        adjustment.reason = reason[:2000]
        adjustment.save(update_fields=["reason"])
        _fill(adjustment, lines)
        return adjustment


def _check_stock(adjustment: StockAdjustment) -> None:
    """Stock taken out must be there, lot by lot."""
    wanted: dict[tuple, Decimal] = {}
    for line in adjustment.lines.select_related("item"):
        if line.quantity < 0:
            key = (line.item, line.lot_no)
            wanted[key] = wanted.get(key, ZERO) - line.quantity
    for (item, lot), quantity in wanted.items():
        here = (
            StockMovement.objects.filter(item=item, store=adjustment.store, lot_no=lot).aggregate(
                q=Sum("quantity")
            )["q"]
            or ZERO
        )
        if quantity > here:
            raise StockError(
                f"Only {here:,.3f} {item.unit} of {item.code} lot {lot} is in "
                f"{adjustment.store.code}."
            )


def submit(user: User, adjustment: StockAdjustment, comment: str = "") -> StockAdjustment:
    with audit_context("stock_adjustment_submitted", comment), transaction.atomic():
        adjustment = StockAdjustment.objects.select_for_update().get(pk=adjustment.pk)
        if adjustment.status != St.DRAFT or adjustment.created_by_id != user.pk:
            raise StockError("Only the person who prepared a draft adjustment sends it.")
        _check_stock(adjustment)
        try:
            approvals.submit(
                user,
                DOC,
                adjustment.pk,
                created_by=adjustment.created_by,
                division=adjustment.store.division,
                comment=comment,
                title=f"Stock adjustment {adjustment.number} ({adjustment.get_kind_display()})",
                link=f"/stock-adjustments/{adjustment.pk}",
            )
        except ApprovalError as error:
            raise StockError(str(error)) from None
        adjustment.status = St.AWAITING_APPROVAL
        adjustment.save(update_fields=["status"])
        return adjustment


def _waiting(adjustment: StockAdjustment) -> StockAdjustment:
    adjustment = StockAdjustment.objects.select_for_update().get(pk=adjustment.pk)
    if adjustment.status != St.AWAITING_APPROVAL:
        raise StockError("The adjustment is not waiting for approval.")
    return adjustment


def approve(user: User, adjustment: StockAdjustment, comment: str = "") -> StockAdjustment:
    with transaction.atomic():
        adjustment = _waiting(adjustment)
        try:
            state = approvals.approve(user, DOC, adjustment.pk, comment)
        except ApprovalError as error:
            raise StockError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("stock_adjustment_posted", comment):
                _post(user, adjustment)
        return adjustment


def _post(user: User, adjustment: StockAdjustment) -> None:
    _check_stock(adjustment)
    store = adjustment.store
    division = store.division
    lines = list(adjustment.lines.select_related("item__inventory_account").order_by("line_no"))
    taken: dict[int, tuple[Decimal, Decimal]] = {}
    for line in lines:
        item = line.item
        if line.quantity < 0:
            out = -line.quantity
            on_hand, value = main_totals(item)
            so_far = taken.get(item.pk, (ZERO, ZERO))
            if out == on_hand - so_far[0]:
                worth = value - so_far[1]
            else:
                worth = (out * cost_of(item)).quantize(CENT, ROUND_HALF_UP)
            taken[item.pk] = (so_far[0] + out, so_far[1] + worth)
            line.value = -worth
        else:
            cost = cost_of(item) or line.unit_cost
            if not cost:
                raise StockError(
                    f"Line {line.line_no}: {item.code} has no cost in the stores; type the cost "
                    "of the stock found."
                )
            line.value = (line.quantity * cost).quantize(CENT, ROUND_HALF_UP)
        line.save(update_fields=["value"])
    other = system_account("stock_adjustment", "Stock adjustments and write-offs")
    journal_lines = []
    for line in lines:
        if not line.value:
            continue
        stock = journal.Line(
            account=inventory_account(line.item),
            division=division,
            description=f"{adjustment.number} {line.item.code} lot {line.lot_no}",
        )
        cost_side = journal.Line(
            account=other, division=division, description=f"{adjustment.number} {line.item.code}"
        )
        if line.value > 0:
            stock.debit, cost_side.credit = line.value, line.value
        else:
            cost_side.debit, stock.credit = -line.value, -line.value
        journal_lines += [stock, cost_side]
    entry = None
    if journal_lines:
        try:
            entry = journal.post(
                user,
                entry_date=timezone.localdate(),
                narration=f"Stock {adjustment.get_kind_display().lower()} {adjustment.number}, "
                f"{store.code}: {adjustment.reason}"[:500],
                lines=journal_lines,
                source_type="stock_adjustment",
                source_id=adjustment.number,
            )
        except AccountingError as error:
            raise StockError(str(error)) from None
    else:
        raise StockError("The adjustment has no value to post.")
    for line in lines:
        StockMovement.objects.create(
            item=line.item,
            store=store,
            division=division,
            lot_no=line.lot_no,
            kind=StockMovement.Kind.ADJUSTED,
            movement_date=timezone.localdate(),
            quantity=line.quantity,
            value=line.value,
            adjustment_line=line,
            journal_entry=entry if line.value else None,
            created_by=user,
        )
        item_master.mark_used(line.item)
    adjustment.status = St.POSTED
    adjustment.journal_entry = entry
    adjustment.total_value = sum((x.value for x in lines), ZERO)
    adjustment.approved_at = timezone.now()
    adjustment.save(update_fields=["status", "journal_entry", "total_value", "approved_at"])


def send_back(user: User, adjustment: StockAdjustment, reason: str) -> StockAdjustment:
    with transaction.atomic():
        adjustment = _waiting(adjustment)
        try:
            approvals.send_back(user, DOC, adjustment.pk, reason)
        except ApprovalError as error:
            raise StockError(str(error)) from None
        with audit_context("stock_adjustment_returned", reason):
            adjustment.status = St.DRAFT
            adjustment.save(update_fields=["status"])
        if adjustment.count_id:
            StockCount.objects.filter(pk=adjustment.count_id).update(
                status=StockCount.Status.COUNTING
            )
        return adjustment


def reject(user: User, adjustment: StockAdjustment, reason: str) -> StockAdjustment:
    with transaction.atomic():
        adjustment = _waiting(adjustment)
        try:
            approvals.reject(user, DOC, adjustment.pk, reason)
        except ApprovalError as error:
            raise StockError(str(error)) from None
        with audit_context("stock_adjustment_rejected", reason):
            adjustment.status = St.REJECTED
            adjustment.save(update_fields=["status"])
        return adjustment


def can_approve(user: User, adjustment: StockAdjustment) -> bool:
    if adjustment.status != St.AWAITING_APPROVAL:
        return False
    state = approvals.state_of(DOC, adjustment.pk)
    return state is not None and approvals.why_not(user, state) is None


# --- Stock counts ----------------------------------------------------------------------------


def start_count(user: User, *, store, count_date=None, notes: str = "") -> StockCount:
    """A count sheet: every item and lot the books have in the store on the count date."""
    if not effective_access(user).has("stores", "enter"):
        raise StockError("Only the stores person starts a stock count.")
    store = main_store(user, store)
    day = _day(count_date or timezone.localdate())
    if StockCount.objects.filter(store=store, status=StockCount.Status.COUNTING).exists():
        raise StockError(f"A count of {store.code} is already open; finish or cancel it first.")
    with audit_context("stock_count_started"), transaction.atomic():
        try:
            number = allocate("stock_count", on_date=day)
        except NumberSeriesError as error:
            raise StockError(str(error)) from None
        count = StockCount.objects.create(
            number=number, store=store, count_date=day, notes=(notes or "")[:2000], created_by=user
        )
        rows = (
            StockMovement.objects.filter(store=store, movement_date__lte=day)
            .values("item", "lot_no")
            .annotate(quantity=Sum("quantity"))
            .exclude(quantity=0)
        )
        StockCountLine.objects.bulk_create(
            StockCountLine(
                count=count, item_id=r["item"], lot_no=r["lot_no"], system_quantity=r["quantity"]
            )
            for r in rows
        )
        return count


def _counting(user: User, count: StockCount) -> StockCount:
    if not effective_access(user).has("stores", "enter"):
        raise StockError("Only the stores person enters the count.")
    count = StockCount.objects.select_for_update().get(pk=count.pk)
    if count.status != StockCount.Status.COUNTING:
        raise StockError(f"Count {count.number} is closed.")
    main_store(user, count.store)
    return count


def enter_counts(user: User, count: StockCount, rows: list[tuple]) -> StockCount:
    """rows: (item, lot_no, counted quantity or None). A row for an item and lot the sheet
    does not have adds it (stock found that the books do not show)."""
    with audit_context("stock_count_entered"), transaction.atomic():
        count = _counting(user, count)
        for item, lot, counted in rows:
            lot = (lot or "").strip()[:40]
            if not isinstance(item, Item) or not item.is_stock or not lot:
                raise StockError("Each counted line needs a stock item and its lot.")
            value = None
            if counted not in (None, ""):
                try:
                    value = Decimal(str(counted).replace(",", ""))
                except InvalidOperation:
                    raise StockError(f"{item.code} lot {lot}: not a number.") from None
                if not value.is_finite() or value < 0 or value != value.quantize(QTY):
                    raise StockError(f"{item.code} lot {lot}: 0 or more, at most 3 decimals.")
            line, _ = StockCountLine.objects.get_or_create(
                count=count, item=item, lot_no=lot, defaults={"system_quantity": ZERO}
            )
            line.counted_quantity = value
            line.save(update_fields=["counted_quantity"])
        return count


def submit_count(user: User, count: StockCount, comment: str = "") -> StockCount:
    """Every line counted: the differences become an adjustment sent to the Director."""
    with audit_context("stock_count_submitted", comment), transaction.atomic():
        count = _counting(user, count)
        lines = list(count.lines.select_related("item"))
        missing = [x for x in lines if x.counted_quantity is None]
        if missing:
            raise StockError(
                f"{len(missing)} line(s) are not counted yet (enter 0 for what is not there)."
            )
        differences = [x for x in lines if x.counted_quantity != x.system_quantity]
        if not differences:
            count.status = StockCount.Status.AGREED
            count.save(update_fields=["status"])
            return count
        adjustment = getattr(count, "adjustment", None)
        if adjustment is None:
            try:
                number = allocate(DOC, on_date=count.count_date)
            except NumberSeriesError as error:
                raise StockError(str(error)) from None
            adjustment = StockAdjustment.objects.create(
                number=number,
                kind=Kind.COUNT,
                store=count.store,
                adjustment_date=count.count_date,
                reason=f"Stock count {count.number} of {count.count_date:%d/%m/%Y}",
                count=count,
                created_by=user,
            )
        _fill(
            adjustment,
            [
                LineInput(
                    item=x.item,
                    lot_no=x.lot_no,
                    quantity=x.counted_quantity - x.system_quantity,
                    notes=f"Books {x.system_quantity:,.3f}, counted {x.counted_quantity:,.3f}",
                )
                for x in differences
            ],
        )
        count.status = StockCount.Status.SUBMITTED
        count.save(update_fields=["status"])
        submit(user, adjustment, comment)
        return count


def cancel_count(user: User, count: StockCount) -> StockCount:
    with audit_context("stock_count_cancelled"), transaction.atomic():
        count = _counting(user, count)
        count.status = StockCount.Status.CANCELLED
        count.save(update_fields=["status"])
        return count
