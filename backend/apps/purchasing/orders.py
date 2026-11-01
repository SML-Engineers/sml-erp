"""Purchase orders (backlog P16-04, spec 5A.1; owner's decisions of 31 Oct 2026).

- The Purchasing Officer (Purchasing: Enter) raises a PO for a supplier and division, with
  items from the item master, quantities, agreed prices and tax; it is numbered at once
  (PO{YY}{MM}{DD}{XX}) and in the supplier's currency at the day's rate.
- Every PO goes to the Director through the approval engine (never approved by the person who
  raised it). Approved, it can be printed and sent (P16-05) and goods received against it
  (P16-06).
- A PO that has left draft never changes (database guard). To change an approved PO with
  nothing received yet, it is revised: Rev 1 is a new draft with the same lines and the old
  one is marked "Replaced by a revision"; the revision is approved again.
- A PO is cancelled (with a reason) while nothing has been received; one partly received is
  closed short (with a reason) instead.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import TaxCode
from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, Company, Division, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.inventory import items as item_master
from apps.inventory.models import Item
from apps.masters import currencies
from apps.masters.models import Supplier
from apps.masters.services import MastersError
from apps.masters.services import mark_used as mark_supplier_used

from .models import PurchaseOrder, PurchaseOrderLine

DOC = "purchase_order"
St = PurchaseOrder.Status
CENT = Decimal("0.01")
QTY = Decimal("0.001")
MAX_LINES = 100
OPEN = (St.APPROVED, St.PARTLY_RECEIVED)


class PurchasingError(Exception):
    pass


@dataclass
class LineInput:
    item: Item | None
    quantity: object
    unit_price: object
    tax_code: TaxCode | None = None
    description: str = ""


# --- Who may do what ---------------------------------------------------------------------


def can_enter(user: User) -> bool:
    return effective_access(user).has("purchasing", "enter")


def visible(user: User) -> QuerySet[PurchaseOrder]:
    if not effective_access(user).has("purchasing", "view"):
        return PurchaseOrder.objects.none()
    return PurchaseOrder.objects.filter(division__in=division_scope(user))


def can_edit(user: User, order: PurchaseOrder) -> bool:
    return order.status == St.DRAFT and order.created_by_id == user.pk and can_enter(user)


def can_approve(user: User, order: PurchaseOrder) -> bool:
    if order.status != St.AWAITING_APPROVAL:
        return False
    state = approvals.state_of(DOC, order.pk)
    return state is not None and approvals.why_not(user, state) is None


def _received(order: PurchaseOrder) -> bool:
    return order.lines.filter(received_quantity__gt=0).exists()


def can_revise(user: User, order: PurchaseOrder) -> bool:
    return order.status == St.APPROVED and can_enter(user) and not _received(order)


def can_cancel(user: User, order: PurchaseOrder) -> bool:
    if order.status == St.DRAFT:
        return can_edit(user, order)
    return order.status == St.APPROVED and can_enter(user) and not _received(order)


def can_close(user: User, order: PurchaseOrder) -> bool:
    return order.status == St.PARTLY_RECEIVED and can_enter(user)


# --- Checking and working out ------------------------------------------------------------


def _decimal(value, what: str, step: Decimal) -> Decimal:
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise PurchasingError(f"The {what} is not a number.") from None
    if not number.is_finite() or number <= 0:
        raise PurchasingError(f"The {what} must be more than 0.")
    if number != number.quantize(step):
        places = len(str(step).split(".")[1])
        raise PurchasingError(f"The {what} can have at most {places} decimal places.")
    return number


def _check_line(n: int, line: LineInput, order: PurchaseOrder) -> dict:
    where = f"Line {n}: "
    item = line.item
    if not isinstance(item, Item) or not item.is_active:
        raise PurchasingError(where + "choose an active item.")
    if item.division_id and item.division_id != order.division_id:
        raise PurchasingError(where + f"item {item.code} is for division {item.division.code}.")
    try:
        quantity = _decimal(line.quantity, "quantity", QTY)
        price = _decimal(line.unit_price, "unit price", CENT)
    except PurchasingError as error:
        raise PurchasingError(where + str(error)) from None
    tax_code = line.tax_code
    if tax_code is not None and (not tax_code.is_active or tax_code.use == TaxCode.Use.SALES):
        raise PurchasingError(where + f"tax code {tax_code.code} cannot be used on purchases.")
    return {
        "item": item,
        "description": ((line.description or "").strip() or item.name)[:300],
        "unit": item.unit,
        "quantity": quantity,
        "unit_price": price,
        "tax_code": tax_code,
    }


def _header(values: dict, order: PurchaseOrder) -> None:
    if "delivery_date" in values:
        when = values["delivery_date"]
        if when is not None and not isinstance(when, date):
            raise PurchasingError("The delivery date is not a date.")
        if when is not None and when < order.po_date:
            raise PurchasingError("The delivery date cannot be before the PO date.")
        order.delivery_date = when
    if "pay_mode" in values:
        if values["pay_mode"] not in PurchaseOrder.PayMode.values:
            raise PurchasingError("Choose the pay mode: online, cheque or cash.")
        order.pay_mode = values["pay_mode"]
    for field, limit in (("deliver_to", 1000), ("payment_terms", 100), ("notes", 5000)):
        if field in values:
            setattr(order, field, (values[field] or "").strip()[:limit])


def _fill(order: PurchaseOrder, lines: list[LineInput]) -> None:
    if not lines:
        raise PurchasingError("A purchase order needs at least one line.")
    if len(lines) > MAX_LINES:
        raise PurchasingError(f"A purchase order can have at most {MAX_LINES} lines.")
    checked = [_check_line(n, line, order) for n, line in enumerate(lines, start=1)]
    order.lines.all().delete()
    subtotal = tax_total = Decimal("0")
    for n, line in enumerate(checked, start=1):
        amount = (line["quantity"] * line["unit_price"]).quantize(CENT, ROUND_HALF_UP)
        tax = Decimal("0")
        if line["tax_code"] is not None:
            tax = taxes.calculate(line["tax_code"], amount, order.po_date).tax
        PurchaseOrderLine.objects.create(
            order=order, line_no=n, amount=amount, tax_amount=tax, total=amount + tax, **line
        )
        subtotal += amount
        tax_total += tax
    order.subtotal = subtotal
    order.tax_total = tax_total
    order.total_amount = subtotal + tax_total
    lookup = currencies.RateLookup(
        order.currency.code, order.po_date, order.exchange_rate, order.rate_date, None
    )
    order.total_lkr = currencies.to_lkr(order.total_amount, lookup)
    order.save()


def _company_address() -> str:
    company = Company.objects.filter(pk=1).first()
    if company is None:
        return ""
    return "\n".join(filter(None, [company.name, company.address]))


# --- Making and changing ----------------------------------------------------------------


def create(
    user: User, *, supplier: Supplier, division: Division, lines: list[LineInput], **values
) -> PurchaseOrder:
    if not can_enter(user):
        raise PurchasingError("Only the Purchasing Officer raises purchase orders.")
    if not isinstance(supplier, Supplier) or not supplier.is_active:
        raise PurchasingError("Choose an active supplier.")
    if not isinstance(division, Division) or division.division_type != Division.Type.PRODUCTION:
        raise PurchasingError("A purchase order is for a production division (WS or IM).")
    if not division_scope(user).filter(pk=division.pk).exists():
        raise PurchasingError(f"You do not work in division {division.code}.")
    today = timezone.localdate()
    try:
        lookup = currencies.rate_on(supplier.currency, today)
    except MastersError as error:
        raise PurchasingError(str(error)) from None
    with audit_context("purchase_order_created"), transaction.atomic():
        try:
            number = allocate(DOC, division=division, on_date=today)
        except NumberSeriesError as error:
            raise PurchasingError(str(error)) from None
        order = PurchaseOrder(
            number=number,
            supplier=supplier,
            division=division,
            po_date=today,
            currency=supplier.currency,
            exchange_rate=lookup.rate,
            rate_date=lookup.rate_date,
            deliver_to=_company_address(),
            payment_terms=f"Net {supplier.payment_terms_days}"
            if supplier.payment_terms_days
            else "",
            created_by=user,
        )
        _header(values, order)
        order.save()
        _fill(order, lines)
        currencies.mark_rate_used(lookup)
        return order


def save(user: User, order: PurchaseOrder, *, lines: list[LineInput], **values) -> PurchaseOrder:
    with audit_context("purchase_order_changed"), transaction.atomic():
        order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
        if not can_edit(user, order):
            raise PurchasingError("Only the person who raised a draft purchase order changes it.")
        _header(values, order)
        _fill(order, lines)
        return order


def submit(user: User, order: PurchaseOrder, comment: str = "") -> PurchaseOrder:
    """Send the draft to the Director."""
    with audit_context("purchase_order_submitted", comment), transaction.atomic():
        order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
        if not can_edit(user, order):
            raise PurchasingError("Only the person who raised a draft purchase order sends it.")
        if not order.lines.exists():
            raise PurchasingError("A purchase order needs at least one line.")
        if order.delivery_date is None:
            raise PurchasingError("Give the delivery date.")
        try:
            approvals.submit(
                user,
                DOC,
                order.pk,
                created_by=order.created_by,
                amount=order.total_lkr,
                division=order.division,
                comment=comment,
                title=f"Purchase order {order.label} to {order.supplier.name}",
                link=f"/purchase-orders/{order.pk}",
            )
        except ApprovalError as error:
            raise PurchasingError(str(error)) from None
        order.status = St.AWAITING_APPROVAL
        order.save(update_fields=["status"])
        return order


def approve(user: User, order: PurchaseOrder, comment: str = "") -> PurchaseOrder:
    with transaction.atomic():
        order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
        if order.status != St.AWAITING_APPROVAL:
            raise PurchasingError("The purchase order is not waiting for approval.")
        try:
            state = approvals.approve(user, DOC, order.pk, comment)
        except ApprovalError as error:
            raise PurchasingError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("purchase_order_approved", comment):
                order.status = St.APPROVED
                order.approved_at = timezone.now()
                order.save(update_fields=["status", "approved_at"])
            mark_supplier_used(order.supplier)
            for line in order.lines.select_related("item"):
                item_master.mark_used(line.item)
        return order


def send_back(user: User, order: PurchaseOrder, reason: str) -> PurchaseOrder:
    with transaction.atomic():
        order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
        if order.status != St.AWAITING_APPROVAL:
            raise PurchasingError("The purchase order is not waiting for approval.")
        try:
            approvals.send_back(user, DOC, order.pk, reason)
        except ApprovalError as error:
            raise PurchasingError(str(error)) from None
        with audit_context("purchase_order_returned", reason):
            order.status = St.DRAFT
            order.save(update_fields=["status"])
        return order


def revise(user: User, order: PurchaseOrder, reason: str) -> PurchaseOrder:
    """A new draft revision of an approved PO with nothing received; the old one is replaced."""
    reason = (reason or "").strip()
    if not reason:
        raise PurchasingError("Give a reason for revising the purchase order.")
    with audit_context("purchase_order_revised", reason), transaction.atomic():
        order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
        if not can_revise(user, order):
            raise PurchasingError(
                "Only an approved purchase order with nothing received yet can be revised."
            )
        order.status = St.REVISED
        order.end_reason = reason[:1000]
        order.save(update_fields=["status", "end_reason"])
        new = PurchaseOrder.objects.create(
            number=order.number,
            revision=order.revision + 1,
            parent=order,
            supplier=order.supplier,
            division=order.division,
            po_date=timezone.localdate(),
            delivery_date=order.delivery_date,
            deliver_to=order.deliver_to,
            pay_mode=order.pay_mode,
            payment_terms=order.payment_terms,
            currency=order.currency,
            exchange_rate=order.exchange_rate,
            rate_date=order.rate_date,
            notes=order.notes,
            created_by=user,
        )
        _fill(
            new,
            [
                LineInput(
                    line.item, line.quantity, line.unit_price, line.tax_code, line.description
                )
                for line in order.lines.select_related("item", "tax_code")
            ],
        )
        return new


def cancel(user: User, order: PurchaseOrder, reason: str) -> PurchaseOrder:
    reason = (reason or "").strip()
    if not reason:
        raise PurchasingError("Give a reason for cancelling the purchase order.")
    with audit_context("purchase_order_cancelled", reason), transaction.atomic():
        order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
        if not can_cancel(user, order):
            raise PurchasingError(
                "A draft, or an approved purchase order with nothing received, can be cancelled; "
                "one partly received is closed short instead."
            )
        order.status = St.CANCELLED
        order.end_reason = reason[:1000]
        order.save(update_fields=["status", "end_reason"])
        return order


def close(user: User, order: PurchaseOrder, reason: str) -> PurchaseOrder:
    """Close a partly received PO short: the rest will not come."""
    reason = (reason or "").strip()
    if not reason:
        raise PurchasingError("Give a reason for closing the purchase order short.")
    with audit_context("purchase_order_closed", reason), transaction.atomic():
        order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
        if not can_close(user, order):
            raise PurchasingError("Only a partly received purchase order is closed short.")
        order.status = St.CLOSED
        order.end_reason = reason[:1000]
        order.save(update_fields=["status", "end_reason"])
        return order
