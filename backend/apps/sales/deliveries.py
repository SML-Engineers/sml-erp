"""Delivery notes (backlog P2-04, spec 5.3 and 6).

- Made against an open (or partly delivered) sales order by Sales or the stores: the
  quantity of each order line that leaves now, the vehicle, driver and delivery address.
- Numbered DN{YY}{MM}{DD}{XX} on creation, in the saving transaction (rule 10).
- Issuing it checks that no line delivers more than is still to deliver (also a database
  rule), moves the order to Partly delivered or Delivered, and makes it printable for the
  customer to sign. The signed copy, who received the goods and when are recorded when it
  comes back.
- An issued note never changes (database guard). A mistake is corrected by cancelling it with
  a reason: its quantities are open on the order again. (From P2-05 a note that has been
  invoiced cannot be cancelled.)
- Finished-goods stock: none until Phase 3 (owner's question 4, the recommended default of
  3 Nov 2026). A delivery note records what was delivered and posts nothing.
"""

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.core.numbering import NumberSeriesError, allocate

from .models import DeliveryNote, DeliveryNoteLine, SalesOrder, SalesOrderLine
from .services import SalesError, _decimal

DOC = "delivery_note"
QTY = Decimal("0.001")
St = DeliveryNote.Status
OS = SalesOrder.Status
DELIVERABLE = (OS.OPEN, OS.PARTLY_DELIVERED)
COUNTED = (St.ISSUED, St.RECEIVED)
MAX_FILE_BYTES = 20 * 1024 * 1024
FILE_TYPES = {
    b"%PDF": ("application/pdf", ".pdf"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", ".png"),
}


@dataclass
class LineInput:
    order_line: SalesOrderLine
    quantity: object


# --- Who may do what ---------------------------------------------------------------------


def can_view(user: User) -> bool:
    access = effective_access(user)
    return access.has("sales", "view") or access.has("stores", "view")


def can_enter(user: User) -> bool:
    access = effective_access(user)
    return access.has("sales", "enter") or access.has("stores", "enter")


def can_manage(user: User) -> bool:
    """Cancels issued notes: the Sales Manager or the store supervisor."""
    access = effective_access(user)
    return access.has("sales", "approve") or access.has("stores", "enter")


def _sees_all(user: User) -> bool:
    """A Sales Executive (Sales: Enter, without Approve, and no stores access) sees the notes
    of their own orders; everyone else sees all of their divisions'."""
    access = effective_access(user)
    if access.has("stores", "view") or access.has("sales", "approve"):
        return True
    return not access.has("sales", "enter")


def visible(user: User) -> QuerySet[DeliveryNote]:
    if not can_view(user):
        return DeliveryNote.objects.none()
    rows = DeliveryNote.objects.filter(order__division__in=division_scope(user))
    return rows if _sees_all(user) else rows.filter(order__created_by=user)


def orders_to_deliver(user: User) -> QuerySet[SalesOrder]:
    """The orders this user may make a delivery note for."""
    if not can_enter(user):
        return SalesOrder.objects.none()
    rows = SalesOrder.objects.filter(
        status__in=DELIVERABLE, division__in=division_scope(user)
    ).select_related("customer", "division")
    return rows if _sees_all(user) else rows.filter(created_by=user)


def can_edit(user: User, note: DeliveryNote) -> bool:
    return note.status == St.DRAFT and note.created_by_id == user.pk and can_enter(user)


def can_receive(user: User, note: DeliveryNote) -> bool:
    return note.status == St.ISSUED and can_enter(user)


def can_cancel(user: User, note: DeliveryNote) -> bool:
    return note.status in COUNTED and can_manage(user)


# --- Quantities ------------------------------------------------------------------------------


def delivered(order: SalesOrder, *, besides: DeliveryNote | None = None) -> dict[int, Decimal]:
    """Quantity delivered so far per order line (issued and signed notes)."""
    lines = DeliveryNoteLine.objects.filter(note__order=order, note__status__in=COUNTED)
    if besides is not None:
        lines = lines.exclude(note=besides)
    return {
        row["order_line"]: row["total"]
        for row in lines.values("order_line").annotate(total=Sum("quantity"))
    }


def remaining(order: SalesOrder) -> dict[int, Decimal]:
    done = delivered(order)
    return {line.pk: line.quantity - done.get(line.pk, Decimal("0")) for line in order.lines.all()}


def _order_status(order: SalesOrder) -> str:
    done = delivered(order)
    if not done:
        return OS.OPEN
    if all(done.get(line.pk, 0) >= line.quantity for line in order.lines.all()):
        return OS.DELIVERED
    return OS.PARTLY_DELIVERED


def _move_order(order: SalesOrder) -> None:
    """Open, Partly delivered or Delivered, from what the issued notes deliver. An order
    completed or cancelled by hand stays so."""
    if order.status in (OS.COMPLETED, OS.CANCELLED):
        return
    status = _order_status(order)
    if status != order.status:
        with audit_context("sales_order_delivery_status"):
            order.status = status
            order.save(update_fields=["status"])


# --- Making and changing -----------------------------------------------------------------------


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _header(note: DeliveryNote, values: dict) -> None:
    if "delivery_date" in values:
        when = values["delivery_date"]
        if not isinstance(when, date):
            raise SalesError("The delivery date is not a date.")
        if when > timezone.localdate() + timedelta(days=30):
            raise SalesError("The delivery date is more than 30 days ahead.")
        note.delivery_date = when
    if "vehicle_no" in values:
        note.vehicle_no = _text(values["vehicle_no"], 30).upper()
    if "driver" in values:
        note.driver = _text(values["driver"], 100)
    if "delivery_address" in values:
        note.delivery_address = str(values["delivery_address"] or "").strip()[:1000]
    if "notes" in values:
        note.notes = str(values["notes"] or "").strip()[:2000]


def _fill(note: DeliveryNote, given: list[LineInput], *, check_remaining: bool) -> None:
    if not given:
        raise SalesError("Enter the quantity delivered on at least one line.")
    order = note.order
    left = remaining(order) if check_remaining else {}
    seen = set()
    rows = []
    for g in given:
        line = g.order_line
        if line.order_id != order.pk:
            raise SalesError("A line is not on this sales order.")
        if line.pk in seen:
            raise SalesError(f"Line {line.line_no} appears twice.")
        seen.add(line.pk)
        quantity = _decimal(g.quantity, f"quantity on line {line.line_no}", QTY, positive=True)
        if check_remaining and quantity > left[line.pk]:
            raise SalesError(
                f"Line {line.line_no}: only {left[line.pk].normalize():f} {line.unit} is still "
                f"to deliver."
            )
        rows.append(DeliveryNoteLine(note=note, order_line=line, quantity=quantity))
    note.lines.all().delete()
    DeliveryNoteLine.objects.bulk_create(rows)


def create(user: User, order: SalesOrder, *, lines: list[LineInput], **values) -> DeliveryNote:
    if not can_enter(user):
        raise SalesError("Only Sales or the stores make delivery notes.")
    with audit_context("delivery_note_created"), transaction.atomic():
        order = SalesOrder.objects.select_for_update().get(pk=order.pk)
        if not orders_to_deliver(user).filter(pk=order.pk).exists():
            raise SalesError("Delivery notes are made only for open sales orders you may see.")
        today = timezone.localdate()
        note = DeliveryNote(
            order=order,
            delivery_date=today,
            delivery_address=order.delivery_address,
            created_by=user,
        )
        _header(note, values)
        try:
            note.number = allocate(DOC, division=order.division, on_date=today)
        except NumberSeriesError as error:
            raise SalesError(str(error)) from None
        note.save()
        _fill(note, lines, check_remaining=True)
        return note


def save(user: User, note: DeliveryNote, *, lines: list[LineInput], **values) -> DeliveryNote:
    with audit_context("delivery_note_changed"), transaction.atomic():
        note = DeliveryNote.objects.select_for_update().get(pk=note.pk)
        if not can_edit(user, note):
            raise SalesError("Only the person who made a draft delivery note changes it.")
        _header(note, values)
        note.updated_at = timezone.now()
        note.save()
        _fill(note, lines, check_remaining=True)
        return note


def delete(user: User, note: DeliveryNote) -> None:
    with audit_context("delivery_note_deleted"), transaction.atomic():
        note = DeliveryNote.objects.select_for_update().get(pk=note.pk)
        if not can_edit(user, note):
            raise SalesError("Only the person who made a draft delivery note deletes it.")
        note.delete()


def issue(user: User, note: DeliveryNote) -> DeliveryNote:
    """The goods leave: the order's quantities are checked again (another note may have been
    issued since the draft was made), and the order moves on."""
    with audit_context("delivery_note_issued"), transaction.atomic():
        note = DeliveryNote.objects.select_for_update().get(pk=note.pk)
        if not can_edit(user, note):
            raise SalesError("Only the person who made a draft delivery note issues it.")
        order = SalesOrder.objects.select_for_update().get(pk=note.order_id)
        if order.status not in DELIVERABLE:
            raise SalesError(f"Sales order {order.number} is {order.get_status_display().lower()}.")
        left = remaining(order)
        for line in note.lines.select_related("order_line"):
            if line.quantity > left[line.order_line_id]:
                ol = line.order_line
                raise SalesError(
                    f"Line {ol.line_no}: only {left[ol.pk].normalize():f} {ol.unit} is still to "
                    "deliver. Change the draft."
                )
        if not note.lines.exists():
            raise SalesError("The delivery note has no lines.")
        note.status = St.ISSUED
        note.issued_by = user
        note.issued_at = timezone.now()
        note.updated_at = note.issued_at
        note.save(update_fields=["status", "issued_by", "issued_at", "updated_at"])
        _move_order(order)
        return note


def record_receipt(
    user: User, note: DeliveryNote, *, received_by: str, received_on, signed_copy=None
) -> DeliveryNote:
    """The customer's signed copy has come back."""
    name = _text(received_by, 100)
    if not name:
        raise SalesError("Enter the name of the person who received the goods.")
    if not isinstance(received_on, date):
        raise SalesError("Enter the date the goods were received.")
    with audit_context("delivery_note_received"), transaction.atomic():
        note = DeliveryNote.objects.select_for_update().get(pk=note.pk)
        if not can_receive(user, note):
            raise SalesError("Only an issued delivery note is marked as signed by the customer.")
        if received_on < note.delivery_date or received_on > timezone.localdate():
            raise SalesError("The date received is between the delivery date and today.")
        note.received_by = name
        note.received_on = received_on
        if signed_copy is not None:
            _attach(note, signed_copy)
        note.status = St.RECEIVED
        note.updated_at = timezone.now()
        note.save()
        return note


def _attach(note: DeliveryNote, uploaded) -> None:
    if uploaded.size > MAX_FILE_BYTES:
        raise SalesError("The file is larger than 20 MB.")
    content = uploaded.read()
    kind = next((k for magic, k in FILE_TYPES.items() if content.startswith(magic)), None)
    if kind is None:
        raise SalesError("The signed copy must be a JPG, PNG or PDF file.")
    content_type, extension = kind
    digest = hashlib.sha256(content).hexdigest()
    uploaded.seek(0)
    note.signed_copy_name = (uploaded.name or f"signed{extension}").replace("/", "_")[-200:]
    note.signed_copy_type = content_type
    note.signed_copy_sha256 = digest
    note.signed_copy.save(f"{note.number}-signed{extension}", uploaded, save=False)


def cancel(user: User, note: DeliveryNote, reason: str) -> DeliveryNote:
    reason = (reason or "").strip()
    if not reason:
        raise SalesError("Give a reason for cancelling the delivery note.")
    with audit_context("delivery_note_cancelled", reason), transaction.atomic():
        note = DeliveryNote.objects.select_for_update().get(pk=note.pk)
        if not can_cancel(user, note):
            raise SalesError(
                "An issued delivery note is cancelled by the Sales Manager or the stores."
            )
        order = SalesOrder.objects.select_for_update().get(pk=note.order_id)
        note.status = St.CANCELLED
        note.cancel_reason = reason[:1000]
        note.updated_at = timezone.now()
        note.save(update_fields=["status", "cancel_reason", "updated_at"])
        _move_order(order)
        return note


def has_open_notes(order: SalesOrder) -> bool:
    """Draft, issued or signed notes stop an order being cancelled."""
    return order.deliveries.filter(~Q(status=St.CANCELLED)).exists()
