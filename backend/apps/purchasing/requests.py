"""Reorder levels and purchase requests (backlog P2-13, spec 6 inventory alerts).

- The stores person or purchasing sets a reorder level and quantity per item and main store,
  with the usual supplier.
- A check (every hour, and when a level is saved) compares each level with what is in the
  store plus what is already coming: open purchase orders of the division and purchase
  requests not yet made into an order. At or below the level, the stores person and
  purchasing are told once; when the stock is above the level again, the next fall tells them
  again.
- From the alert, one click makes a draft purchase request for the reorder quantity from the
  usual supplier. A request is sent for approval through the approval engine (the Director
  by default), never approved by its author. Purchasing then makes an approved request into
  a draft purchase order, at the last price paid to that supplier (or prices they type), and
  the order follows its own approval.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F, QuerySet, Sum
from django.utils import timezone

from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, Division, User
from apps.core.notifications import notify
from apps.core.numbering import NumberSeriesError, allocate
from apps.inventory.models import Item, StockMovement, Store
from apps.masters.models import Supplier

from . import orders
from .models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    ReorderLevel,
)
from .orders import PurchasingError

DOC = "purchase_request"
St = PurchaseRequest.Status
QTY = Decimal("0.001")
ZERO = Decimal("0")
MAX_LINES = 100
# Purchase orders whose quantities are still coming.
COMING = (
    PurchaseOrder.Status.DRAFT,
    PurchaseOrder.Status.AWAITING_APPROVAL,
    PurchaseOrder.Status.APPROVED,
    PurchaseOrder.Status.PARTLY_RECEIVED,
)
REQUESTED = (St.DRAFT, St.AWAITING_APPROVAL, St.APPROVED)


# --- Who may do what ---------------------------------------------------------------------


def can_raise(user: User) -> bool:
    """The stores person or purchasing."""
    access = effective_access(user)
    return access.has("stores", "enter") or access.has("purchasing", "enter")


def can_view(user: User) -> bool:
    access = effective_access(user)
    return access.has("stores", "view") or access.has("purchasing", "view")


def visible(user: User) -> QuerySet[PurchaseRequest]:
    if not can_view(user):
        return PurchaseRequest.objects.none()
    return PurchaseRequest.objects.filter(division__in=division_scope(user))


def can_edit(user: User, request: PurchaseRequest) -> bool:
    return request.status == St.DRAFT and request.created_by_id == user.pk and can_raise(user)


def can_approve(user: User, request: PurchaseRequest) -> bool:
    if request.status != St.AWAITING_APPROVAL:
        return False
    state = approvals.state_of(DOC, request.pk)
    return state is not None and approvals.why_not(user, state) is None


def can_order(user: User, request: PurchaseRequest) -> bool:
    return request.status == St.APPROVED and orders.can_enter(user)


def can_cancel(user: User, request: PurchaseRequest) -> bool:
    if request.status == St.DRAFT:
        return can_edit(user, request)
    return request.status == St.APPROVED and can_raise(user)


def _quantity(value, where: str, *, zero=False) -> Decimal:
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise PurchasingError(f"{where} is not a number.") from None
    if not number.is_finite() or number < 0 or (number == 0 and not zero):
        raise PurchasingError(f"{where} must be more than 0.")
    if number != number.quantize(QTY) or number >= Decimal("1e15"):
        raise PurchasingError(f"{where} can have at most 3 decimal places.")
    return number


# --- Reorder levels ------------------------------------------------------------------------


def _main_store(user: User, store) -> Store:
    if not isinstance(store, Store) or not store.is_active or store.kind != Store.Kind.MAIN:
        raise PurchasingError("Choose an active main store.")
    if not division_scope(user).filter(pk=store.division_id).exists():
        raise PurchasingError(f"You do not work in division {store.division.code}.")
    return store


def _stock_item(item, division_id: int) -> Item:
    if not isinstance(item, Item) or not item.is_active:
        raise PurchasingError("Choose an active item.")
    if not item.is_stock:
        raise PurchasingError(f"{item.code} is not kept in stock.")
    if item.division_id and item.division_id != division_id:
        raise PurchasingError(f"Item {item.code} is for division {item.division.code}.")
    return item


def set_level(
    user: User, *, item, store, level, quantity, usual_supplier: Supplier | None = None
) -> ReorderLevel:
    """Add or change the reorder level and quantity of an item in a main store."""
    if not can_raise(user):
        raise PurchasingError("Only the stores person or purchasing sets reorder levels.")
    store = _main_store(user, store)
    item = _stock_item(item, store.division_id)
    level = _quantity(level, "The reorder level", zero=True)
    quantity = _quantity(quantity, "The reorder quantity")
    if usual_supplier is not None and not usual_supplier.is_active:
        raise PurchasingError(f"{usual_supplier.name} is deactivated.")
    with audit_context("reorder_level_set"), transaction.atomic():
        row, _ = ReorderLevel.objects.select_for_update().get_or_create(
            item=item,
            store=store,
            defaults={"level": level, "quantity": quantity, "updated_by": user},
        )
        row.level, row.quantity, row.usual_supplier = level, quantity, usual_supplier
        row.updated_by, row.updated_at = user, timezone.now()
        row.save()
        check([row])
        return row


def remove_level(user: User, row: ReorderLevel) -> None:
    if not can_raise(user):
        raise PurchasingError("Only the stores person or purchasing sets reorder levels.")
    _main_store(user, row.store)
    with audit_context("reorder_level_removed"):
        row.delete()


@dataclass
class Position:
    row: ReorderLevel
    on_hand: Decimal
    on_order: Decimal
    requested: Decimal

    @property
    def available(self) -> Decimal:
        return self.on_hand + self.on_order + self.requested

    @property
    def low(self) -> bool:
        return self.available <= self.row.level


def positions(rows) -> list[Position]:
    """Each level with what is in the store, ordered (still to come) and requested."""
    rows = list(rows)
    if not rows:
        return []
    items = {r.item_id for r in rows}
    stores = {r.store_id for r in rows}
    divisions = {r.store.division_id for r in rows}
    stock = {
        (m["item_id"], m["store_id"]): m["total"]
        for m in StockMovement.objects.filter(item_id__in=items, store_id__in=stores)
        .values("item_id", "store_id")
        .annotate(total=Sum("quantity"))
    }
    ordered = {
        (m["item_id"], m["order__division_id"]): m["total"]
        for m in PurchaseOrderLine.objects.filter(
            item_id__in=items, order__division_id__in=divisions, order__status__in=COMING
        )
        .values("item_id", "order__division_id")
        .annotate(total=Sum(F("quantity") - F("received_quantity")))
    }
    requested = {
        (m["item_id"], m["request__division_id"]): m["total"]
        for m in PurchaseRequestLine.objects.filter(
            item_id__in=items, request__division_id__in=divisions, request__status__in=REQUESTED
        )
        .values("item_id", "request__division_id")
        .annotate(total=Sum("quantity"))
    }
    return [
        Position(
            row=r,
            on_hand=stock.get((r.item_id, r.store_id)) or ZERO,
            on_order=max(ordered.get((r.item_id, r.store.division_id)) or ZERO, ZERO),
            requested=requested.get((r.item_id, r.store.division_id)) or ZERO,
        )
        for r in rows
    ]


def _people(division: Division) -> list[User]:
    """The stores person and purchasing of the division, to be told."""
    found = []
    for user in User.objects.filter(is_active=True).prefetch_related("divisions"):
        access = effective_access(user)
        if not (access.has("stores", "enter") or access.has("purchasing", "enter")):
            continue
        if division_scope(user).filter(pk=division.pk).exists():
            found.append(user)
    return found


def check(rows=None) -> int:
    """Tell the stores person and purchasing of each level newly reached; clear the alert of
    those above their level again. Returns how many alerts were sent."""
    if rows is None:
        rows = ReorderLevel.objects.all()
    rows = [r for r in rows if r.item.is_active and r.store.is_active]
    sent = 0
    for position in positions(rows):
        row = position.row
        if position.low and row.alerted_at is None:
            with transaction.atomic():
                row.alerted_at = timezone.now()
                row.save(update_fields=["alerted_at"])
                notify(
                    _people(row.store.division),
                    "reorder_alert",
                    title=f"{row.item.code} {row.item.name} is at its reorder level in "
                    f"{row.store.code}",
                    body=f"In the store {position.on_hand:,.3f} {row.item.unit}; coming "
                    f"{position.on_order + position.requested:,.3f}; reorder level "
                    f"{row.level:,.3f}. Raise a purchase request for {row.quantity:,.3f}.",
                    link="/reorder",
                )
            sent += 1
        elif not position.low and row.alerted_at is not None:
            row.alerted_at = None
            row.save(update_fields=["alerted_at"])
    return sent


def levels(user: User) -> QuerySet[ReorderLevel]:
    if not can_view(user):
        return ReorderLevel.objects.none()
    return ReorderLevel.objects.filter(store__division__in=division_scope(user)).select_related(
        "item", "store", "store__division", "usual_supplier"
    )


def usual_supplier(row: ReorderLevel) -> Supplier | None:
    """The level's usual supplier, or the supplier of the item's latest purchase order."""
    if row.usual_supplier_id and row.usual_supplier.is_active:
        return row.usual_supplier
    line = (
        PurchaseOrderLine.objects.filter(item=row.item, order__supplier__is_active=True)
        .exclude(order__status=PurchaseOrder.Status.DRAFT)
        .select_related("order__supplier")
        .order_by("-order__po_date", "-order_id")
        .first()
    )
    return line.order.supplier if line else None


# --- Purchase requests ---------------------------------------------------------------------


@dataclass
class LineInput:
    item: Item | None
    quantity: object
    notes: str = ""


def _fill(request: PurchaseRequest, lines: list[LineInput]) -> None:
    if not lines:
        raise PurchasingError("A purchase request needs at least one line.")
    if len(lines) > MAX_LINES:
        raise PurchasingError(f"A purchase request can have at most {MAX_LINES} lines.")
    checked = []
    for n, line in enumerate(lines, start=1):
        where = f"Line {n}"
        try:
            item = _stock_item(line.item, request.division_id) if line.item else None
        except PurchasingError as error:
            raise PurchasingError(f"{where}: {error}") from None
        if item is None:
            raise PurchasingError(f"{where}: choose an active item.")
        quantity = _quantity(line.quantity, f"{where}: the quantity")
        checked.append((item, quantity, (line.notes or "").strip()[:300]))
    request.lines.all().delete()
    for n, (item, quantity, notes) in enumerate(checked, start=1):
        PurchaseRequestLine.objects.create(
            request=request, line_no=n, item=item, quantity=quantity, notes=notes
        )


def _header(request: PurchaseRequest, values: dict) -> None:
    if "supplier" in values:
        supplier = values["supplier"]
        if supplier is not None and not supplier.is_active:
            raise PurchasingError(f"{supplier.name} is deactivated.")
        request.supplier = supplier
    if "needed_by" in values:
        when = values["needed_by"]
        if when is not None and not isinstance(when, date):
            raise PurchasingError("The date needed is not a date.")
        if when is not None and when < timezone.localdate():
            raise PurchasingError("The date needed cannot be in the past.")
        request.needed_by = when
    if "reason" in values:
        request.reason = (values["reason"] or "").strip()[:2000]


def create(
    user: User,
    *,
    division: Division | None = None,
    store: Store | None = None,
    lines: list[LineInput],
    from_reorder: bool = False,
    **values,
) -> PurchaseRequest:
    if not can_raise(user):
        raise PurchasingError("Only the stores person or purchasing raises purchase requests.")
    if store is not None:
        store = _main_store(user, store)
        division = store.division
    if not isinstance(division, Division) or division.division_type != Division.Type.PRODUCTION:
        raise PurchasingError("A purchase request is for a production division (WS or IM).")
    if not division_scope(user).filter(pk=division.pk).exists():
        raise PurchasingError(f"You do not work in division {division.code}.")
    with audit_context("purchase_request_created"), transaction.atomic():
        try:
            number = allocate(DOC, division=division, on_date=timezone.localdate())
        except NumberSeriesError as error:
            raise PurchasingError(str(error)) from None
        request = PurchaseRequest(
            number=number,
            division=division,
            store=store,
            from_reorder=from_reorder,
            created_by=user,
        )
        _header(request, values)
        request.save()
        _fill(request, lines)
        return request


def from_level(user: User, row: ReorderLevel) -> PurchaseRequest:
    """One click from a reorder alert: a draft request for the reorder quantity from the
    usual supplier, for its author to check and send."""
    if not levels(user).filter(pk=row.pk).exists():
        raise PurchasingError("You do not work in this store's division.")
    return create(
        user,
        store=row.store,
        supplier=usual_supplier(row),
        lines=[LineInput(item=row.item, quantity=row.quantity)],
        reason=f"Stock of {row.item.code} at its reorder level ({row.level:,.3f} {row.item.unit}) "
        f"in {row.store.code}.",
        from_reorder=True,
    )


def save(user: User, request: PurchaseRequest, *, lines: list[LineInput], **values):
    with audit_context("purchase_request_changed"), transaction.atomic():
        request = PurchaseRequest.objects.select_for_update().get(pk=request.pk)
        if not can_edit(user, request):
            raise PurchasingError("Only the person who raised a draft request changes it.")
        _header(request, values)
        request.save()
        _fill(request, lines)
        return request


def submit(user: User, request: PurchaseRequest, comment: str = "") -> PurchaseRequest:
    with audit_context("purchase_request_submitted", comment), transaction.atomic():
        request = PurchaseRequest.objects.select_for_update().get(pk=request.pk)
        if not can_edit(user, request):
            raise PurchasingError("Only the person who raised a draft request sends it.")
        if not request.lines.exists():
            raise PurchasingError("A purchase request needs at least one line.")
        try:
            approvals.submit(
                user,
                DOC,
                request.pk,
                created_by=request.created_by,
                division=request.division,
                comment=comment,
                title=f"Purchase request {request.number}",
                link=f"/purchase-requests/{request.pk}",
            )
        except ApprovalError as error:
            raise PurchasingError(str(error)) from None
        request.status = St.AWAITING_APPROVAL
        request.save(update_fields=["status"])
        return request


def _waiting(request: PurchaseRequest) -> PurchaseRequest:
    request = PurchaseRequest.objects.select_for_update().get(pk=request.pk)
    if request.status != St.AWAITING_APPROVAL:
        raise PurchasingError("The purchase request is not waiting for approval.")
    return request


def approve(user: User, request: PurchaseRequest, comment: str = "") -> PurchaseRequest:
    with transaction.atomic():
        request = _waiting(request)
        try:
            state = approvals.approve(user, DOC, request.pk, comment)
        except ApprovalError as error:
            raise PurchasingError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("purchase_request_approved", comment):
                request.status = St.APPROVED
                request.approved_at = timezone.now()
                request.save(update_fields=["status", "approved_at"])
        return request


def send_back(user: User, request: PurchaseRequest, reason: str) -> PurchaseRequest:
    with transaction.atomic():
        request = _waiting(request)
        try:
            approvals.send_back(user, DOC, request.pk, reason)
        except ApprovalError as error:
            raise PurchasingError(str(error)) from None
        with audit_context("purchase_request_returned", reason):
            request.status = St.DRAFT
            request.save(update_fields=["status"])
        return request


def reject(user: User, request: PurchaseRequest, reason: str) -> PurchaseRequest:
    with transaction.atomic():
        request = _waiting(request)
        try:
            approvals.reject(user, DOC, request.pk, reason)
        except ApprovalError as error:
            raise PurchasingError(str(error)) from None
        with audit_context("purchase_request_rejected", reason):
            request.status = St.REJECTED
            request.end_reason = (reason or "").strip()[:1000]
            request.save(update_fields=["status", "end_reason"])
        return request


def cancel(user: User, request: PurchaseRequest, reason: str) -> PurchaseRequest:
    reason = (reason or "").strip()
    if not reason:
        raise PurchasingError("Give a reason for cancelling the request.")
    with audit_context("purchase_request_cancelled", reason), transaction.atomic():
        request = PurchaseRequest.objects.select_for_update().get(pk=request.pk)
        if not can_cancel(user, request):
            raise PurchasingError(
                "A draft request is cancelled by its author; an approved one by the stores "
                "person or purchasing, before it is ordered."
            )
        request.status = St.CANCELLED
        request.end_reason = reason[:1000]
        request.save(update_fields=["status", "end_reason"])
        return request


def last_line(item: Item, supplier: Supplier) -> PurchaseOrderLine | None:
    """The item's line on the latest purchase order to this supplier that left draft."""
    return (
        PurchaseOrderLine.objects.filter(item=item, order__supplier=supplier)
        .exclude(order__status=PurchaseOrder.Status.DRAFT)
        .select_related("tax_code")
        .order_by("-order__po_date", "-order_id")
        .first()
    )


def make_order(
    user: User,
    request: PurchaseRequest,
    *,
    supplier: Supplier | None = None,
    prices: dict | None = None,
) -> PurchaseOrder:
    """An approved request becomes a draft purchase order from purchasing, at the last price
    paid to the supplier unless a price is given (by line number)."""
    prices = prices or {}
    with audit_context("purchase_request_ordered"), transaction.atomic():
        request = PurchaseRequest.objects.select_for_update().get(pk=request.pk)
        if not can_order(user, request):
            raise PurchasingError("Only purchasing makes an approved request into an order.")
        supplier = supplier or request.supplier
        if supplier is None:
            raise PurchasingError("Choose the supplier.")
        lines = []
        for line in request.lines.select_related("item"):
            previous = last_line(line.item, supplier)
            price = prices.get(line.line_no) or prices.get(str(line.line_no))
            if not price:
                if previous is None:
                    raise PurchasingError(
                        f"Line {line.line_no}: {supplier.name} has no earlier price for "
                        f"{line.item.code}; enter the price."
                    )
                price = previous.unit_price
            lines.append(
                orders.LineInput(
                    item=line.item,
                    quantity=line.quantity,
                    unit_price=price,
                    tax_code=previous.tax_code if previous else None,
                    description=line.notes,
                )
            )
        order = orders.create(
            user,
            supplier=supplier,
            division=request.division,
            lines=lines,
            delivery_date=request.needed_by
            if request.needed_by and request.needed_by >= timezone.localdate()
            else None,
            notes=f"From purchase request {request.number}.",
        )
        request.status = St.ORDERED
        request.purchase_order = order
        request.save(update_fields=["status", "purchase_order"])
        return order
