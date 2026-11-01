"""Goods receiving notes (backlog P16-06, spec 5A.2; owner's decisions of 31 Oct 2026).

- The stores person (Stores: Enter) makes a GRN from an approved or partly received purchase
  order; the lines start with what the PO still expects. They enter what actually arrived and
  how much of it is damaged, the delivery note, vehicle and supplier's invoice number, and
  photos. With one stores person, they also confirm it; QC acceptance by someone else is the
  check (P16-08).
- Confirming adds the good quantity (received less damaged) to the PO lines and moves the PO
  to Partly received or Received. The goods are in the division's quarantine store.
- Good quantity above what the PO still expects is an excess: the GRN then waits for the
  Director, who approves it (the excess is accepted) or sends it back to be corrected.
- A confirmed GRN never changes (database guard). A mistake is a reversal, with a reason,
  approved by the Director: the PO's received quantities go back down.
"""

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters.services import mark_used
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine

from . import packages
from .models import (
    GoodsReceipt,
    GoodsReceiptLine,
    GoodsReceiptPhoto,
    Item,
    ReceiptPackage,
    Store,
)
from .packages import PackageInput

DOC = "goods_receipt"
REVERSAL = "goods_receipt_reversal"
St = GoodsReceipt.Status
PO = PurchaseOrder.Status
QTY = Decimal("0.001")
RECEIVABLE = (PO.APPROVED, PO.PARTLY_RECEIVED)
MAX_PHOTOS = 20
MAX_FILE_BYTES = 20 * 1024 * 1024
FILE_TYPES = {
    b"%PDF-": ("application/pdf", ".pdf"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", ".png"),
}


class ReceiptError(Exception):
    pass


@dataclass
class LineInput:
    po_line: int
    received: object
    damaged: object = "0"
    notes: str = ""


# --- Who may do what ---------------------------------------------------------------------


def can_enter(user: User) -> bool:
    return effective_access(user).has("stores", "enter")


def visible(user: User) -> QuerySet[GoodsReceipt]:
    if not effective_access(user).has("stores", "view"):
        return GoodsReceipt.objects.none()
    return GoodsReceipt.objects.filter(division__in=division_scope(user))


def receivable(user: User) -> QuerySet[PurchaseOrder]:
    """Purchase orders goods can be received against."""
    return PurchaseOrder.objects.filter(
        status__in=RECEIVABLE, division__in=division_scope(user)
    ).select_related("supplier", "division")


def can_edit(user: User, grn: GoodsReceipt) -> bool:
    return grn.status == St.DRAFT and grn.created_by_id == user.pk and can_enter(user)


def _waiting(user: User, grn: GoodsReceipt, kind: str, status: str) -> bool:
    if grn.status != status:
        return False
    state = approvals.state_of(kind, grn.pk)
    return state is not None and approvals.why_not(user, state) is None


def can_approve_excess(user: User, grn: GoodsReceipt) -> bool:
    return _waiting(user, grn, DOC, St.AWAITING_APPROVAL)


def can_request_reversal(user: User, grn: GoodsReceipt) -> bool:
    return grn.status == St.CONFIRMED and can_enter(user)


def can_approve_reversal(user: User, grn: GoodsReceipt) -> bool:
    return _waiting(user, grn, REVERSAL, St.REVERSAL_REQUESTED)


# --- Checking -----------------------------------------------------------------------------


def _quantity(value, what: str) -> Decimal:
    try:
        number = Decimal(str(value if value not in (None, "") else "0").replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise ReceiptError(f"The {what} is not a number.") from None
    if not number.is_finite() or number < 0:
        raise ReceiptError(f"The {what} cannot be negative.")
    if number != number.quantize(QTY):
        raise ReceiptError(f"The {what} can have at most 3 decimal places.")
    return number


def _outstanding(po_line: PurchaseOrderLine) -> Decimal:
    return max(po_line.quantity - po_line.received_quantity, Decimal("0"))


def _quarantine(division) -> Store:
    store = Store.objects.filter(
        division=division, kind=Store.Kind.QUARANTINE, is_active=True
    ).first()
    if store is None:
        raise ReceiptError(f"Division {division.code} has no quarantine store (Settings → Stores).")
    return store


def _header(grn: GoodsReceipt, values: dict) -> None:
    if "receipt_date" in values:
        when = values["receipt_date"]
        if not isinstance(when, date):
            raise ReceiptError("The receipt date is not a date.")
        if when > timezone.localdate():
            raise ReceiptError("Goods cannot be received in the future.")
        if when < grn.purchase_order.po_date:
            raise ReceiptError("Goods cannot be received before the purchase order's date.")
        grn.receipt_date = when
    for field, limit in (
        ("delivery_note_no", 50),
        ("vehicle_no", 30),
        ("supplier_invoice_no", 50),
        ("notes", 5000),
    ):
        if field in values:
            setattr(grn, field, (values[field] or "").strip()[:limit])


def _fill(grn: GoodsReceipt, lines: list[LineInput]) -> None:
    """Set the lines. A line received by package (P16-07) keeps the totals of its packages;
    lines keep their numbers, so the packages' lot numbers never change."""
    po_lines = {line.pk: line for line in grn.purchase_order.lines.select_related("item")}
    existing = {line.po_line_id: line for line in grn.lines.all()}
    packed = {line.po_line_id for line in grn.lines.all() if line.packages.exists()}
    seen = set()
    rows = []
    for n, line in enumerate(lines, start=1):
        where = f"Line {n}: "
        po_line = po_lines.get(line.po_line)
        if po_line is None:
            raise ReceiptError(where + "choose a line of the purchase order.")
        if po_line.pk in seen:
            raise ReceiptError(where + "each line of the purchase order can appear once.")
        seen.add(po_line.pk)
        if po_line.pk in packed:
            current = existing[po_line.pk]
            received, damaged = current.received_quantity, current.damaged_quantity
        else:
            try:
                received = _quantity(line.received, "received quantity")
                damaged = _quantity(line.damaged, "damaged quantity")
            except ReceiptError as error:
                raise ReceiptError(where + str(error)) from None
            if damaged > received:
                raise ReceiptError(where + "the damaged quantity cannot be more than received.")
        rows.append((po_line, received, damaged, (line.notes or "").strip()[:300]))
    if not rows or all(received == 0 for _, received, _, _ in rows):
        raise ReceiptError("Enter the quantity received on at least one line.")
    for po_line_id, line in existing.items():
        if po_line_id not in seen:
            line.delete()
    next_no = max((line.line_no for line in existing.values()), default=0) + 1
    for po_line, received, damaged, notes in rows:
        line = existing.get(po_line.pk)
        if line is None:
            line = GoodsReceiptLine(
                receipt=grn, line_no=next_no, po_line=po_line, item=po_line.item
            )
            next_no += 1
        line.received_quantity = received
        line.damaged_quantity = damaged
        line.notes = notes
        line.save()


# --- Packages (P16-07) ------------------------------------------------------------------


def set_packages(
    user: User, grn: GoodsReceipt, line_no: int, given: list[PackageInput]
) -> GoodsReceiptLine:
    """Replace the packages of one line. The line's received quantity becomes the total of
    its packages, and its damaged quantity the total of the damaged ones."""
    with audit_context("goods_receipt_packages_changed"), transaction.atomic():
        grn = GoodsReceipt.objects.select_for_update().get(pk=grn.pk)
        if not can_edit(user, grn):
            raise ReceiptError("Only the person who made a draft GRN enters its packages.")
        line = grn.lines.select_related("item").filter(line_no=line_no).first()
        if line is None:
            raise ReceiptError("Choose a line of the GRN.")
        item = line.item
        if item.package_type == Item.PackageType.NONE:
            raise ReceiptError(
                f'Item {item.code} is not received by package (Items: "Arrives as").'
            )
        if len(given) > packages.MAX_PACKAGES:
            raise ReceiptError(f"A line can have at most {packages.MAX_PACKAGES} packages.")
        line.weight_tolerance_pct = item.weight_tolerance_pct
        line.standard_kg_per_m = item.standard_kg_per_m
        line.density = item.density
        rows = []
        for n, values in enumerate(given, start=1):
            package = ReceiptPackage(
                line=line, package_no=n, lot_no=f"{grn.number}-{line.line_no}-{n:03d}"
            )
            try:
                packages.fill(package, values, item)
            except packages.PackageError as error:
                raise ReceiptError(f"Package {n}: {error}") from None
            rows.append(package)
        line.packages.all().delete()
        for package in rows:  # one by one, so each is in the audit log
            package.save()
        line.received_quantity = sum((p.quantity or 0 for p in rows), Decimal("0"))
        line.damaged_quantity = sum((p.quantity or 0 for p in rows if p.damaged), Decimal("0"))
        line.save()
        return line


def _packages_complete(line: GoodsReceiptLine) -> None:
    item = line.item
    if item.package_type == Item.PackageType.NONE:
        return
    rows = list(line.packages.all())
    if not rows:
        if line.received_quantity == 0:
            return
        raise ReceiptError(
            f"Line {line.line_no} ({item.code}): enter the "
            f"{item.get_package_type_display().split(' (')[0].split(',')[0].lower()} "
            "received, one by one."
        )
    for package in rows:
        lacking = packages.missing(package, item)
        if lacking:
            raise ReceiptError(
                f"Line {line.line_no} ({item.code}), package {package.package_no}: enter {lacking}."
            )


# --- Making and changing ----------------------------------------------------------------


def create(user: User, order: PurchaseOrder, **values) -> GoodsReceipt:
    """A draft GRN for the PO, its lines set to what the PO still expects."""
    if not can_enter(user):
        raise ReceiptError("Only the stores person receives goods.")
    if not receivable(user).filter(pk=order.pk).exists():
        raise ReceiptError("Goods are received only against an approved purchase order.")
    with audit_context("goods_receipt_created"), transaction.atomic():
        order = PurchaseOrder.objects.select_for_update().get(pk=order.pk)
        lines = [
            LineInput(line.pk, _outstanding(line))
            for line in order.lines.all()
            if _outstanding(line) > 0
        ]
        if not lines:
            raise ReceiptError("Everything on this purchase order has already been received.")
        today = timezone.localdate()
        try:
            number = allocate(DOC, division=order.division, on_date=today)
        except NumberSeriesError as error:
            raise ReceiptError(str(error)) from None
        grn = GoodsReceipt(
            number=number,
            purchase_order=order,
            supplier=order.supplier,
            division=order.division,
            store=_quarantine(order.division),
            receipt_date=today,
            created_by=user,
        )
        _header(grn, values)
        grn.save()
        _fill(grn, lines)
        return grn


def save(user: User, grn: GoodsReceipt, *, lines: list[LineInput], **values) -> GoodsReceipt:
    with audit_context("goods_receipt_changed"), transaction.atomic():
        grn = GoodsReceipt.objects.select_for_update().get(pk=grn.pk)
        if not can_edit(user, grn):
            raise ReceiptError("Only the person who made a draft GRN changes it.")
        _header(grn, values)
        grn.save()
        _fill(grn, lines)
        return grn


def _apply(grn: GoodsReceipt, user: User) -> None:
    """Add the good quantities to the PO and update its status; the GRN is confirmed."""
    order = PurchaseOrder.objects.select_for_update().get(pk=grn.purchase_order_id)
    for line in grn.lines.select_related("po_line"):
        po_line = PurchaseOrderLine.objects.select_for_update().get(pk=line.po_line_id)
        po_line.received_quantity += line.good_quantity
        po_line.save(update_fields=["received_quantity"])
    _po_status(order)
    grn.status = St.CONFIRMED
    grn.confirmed_by = grn.confirmed_by or user
    grn.confirmed_at = timezone.now()
    grn.save(update_fields=["status", "confirmed_by", "confirmed_at"])
    mark_used(grn.store)


def _po_status(order: PurchaseOrder) -> None:
    lines = list(order.lines.all())
    if all(line.received_quantity >= line.quantity for line in lines):
        status = PO.RECEIVED
    elif any(line.received_quantity > 0 for line in lines):
        status = PO.PARTLY_RECEIVED
    else:
        status = PO.APPROVED
    if order.status != status and order.status in (PO.APPROVED, PO.PARTLY_RECEIVED, PO.RECEIVED):
        order.status = status
        order.save(update_fields=["status"])


def confirm(user: User, grn: GoodsReceipt, comment: str = "") -> GoodsReceipt:
    """Confirm the receipt; an excess over the PO first goes to the Director."""
    with audit_context("goods_receipt_confirmed", comment), transaction.atomic():
        grn = GoodsReceipt.objects.select_for_update().get(pk=grn.pk)
        if not can_edit(user, grn):
            raise ReceiptError("Only the person who made a draft GRN confirms it.")
        order = PurchaseOrder.objects.select_for_update().get(pk=grn.purchase_order_id)
        if order.status not in RECEIVABLE:
            raise ReceiptError(
                f"Purchase order {order.label} is {order.get_status_display().lower()}; goods "
                "cannot be received against it."
            )
        lines = list(grn.lines.select_related("po_line", "item"))
        if all(line.received_quantity == 0 for line in lines):
            raise ReceiptError("Enter the quantity received on at least one line.")
        excess = []
        for line in lines:
            _packages_complete(line)
            outstanding = _outstanding(line.po_line)
            line.outstanding_quantity = outstanding
            line.excess_quantity = max(line.good_quantity - outstanding, Decimal("0"))
            line.save(update_fields=["outstanding_quantity", "excess_quantity"])
            if line.excess_quantity:
                excess.append(f"{line.item.code}: {line.excess_quantity.normalize():f} over")
        if not excess:
            _apply(grn, user)
            return grn
        try:
            approvals.submit(
                user,
                DOC,
                grn.pk,
                created_by=grn.created_by,
                amount=None,
                division=grn.division,
                comment="; ".join(filter(None, [comment, *excess])),
                title=f"GRN {grn.number}: more delivered than PO {order.label} expects",
                link=f"/goods-receipts/{grn.pk}",
            )
        except ApprovalError as error:
            raise ReceiptError(str(error)) from None
        grn.status = St.AWAITING_APPROVAL
        grn.confirmed_by = user
        grn.save(update_fields=["status", "confirmed_by"])
        return grn


def approve_excess(user: User, grn: GoodsReceipt, comment: str = "") -> GoodsReceipt:
    with transaction.atomic():
        grn = GoodsReceipt.objects.select_for_update().get(pk=grn.pk)
        if grn.status != St.AWAITING_APPROVAL:
            raise ReceiptError("This GRN is not waiting for the Director.")
        order = PurchaseOrder.objects.select_for_update().get(pk=grn.purchase_order_id)
        if order.status not in RECEIVABLE:
            raise ReceiptError(
                f"Purchase order {order.label} is {order.get_status_display().lower()}; send "
                "the GRN back instead."
            )
        try:
            state = approvals.approve(user, DOC, grn.pk, comment)
        except ApprovalError as error:
            raise ReceiptError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("goods_receipt_excess_approved", comment):
                _apply(grn, grn.confirmed_by)
        return grn


def send_back(user: User, grn: GoodsReceipt, reason: str) -> GoodsReceipt:
    """The Director does not accept the excess: the GRN goes back to be corrected."""
    with transaction.atomic():
        grn = GoodsReceipt.objects.select_for_update().get(pk=grn.pk)
        if grn.status != St.AWAITING_APPROVAL:
            raise ReceiptError("This GRN is not waiting for the Director.")
        try:
            approvals.send_back(user, DOC, grn.pk, reason)
        except ApprovalError as error:
            raise ReceiptError(str(error)) from None
        with audit_context("goods_receipt_returned", reason):
            grn.status = St.DRAFT
            grn.confirmed_by = None
            grn.save(update_fields=["status", "confirmed_by"])
        return grn


def delete(user: User, grn: GoodsReceipt) -> None:
    with audit_context("goods_receipt_deleted"), transaction.atomic():
        grn = GoodsReceipt.objects.select_for_update().get(pk=grn.pk)
        if not can_edit(user, grn):
            raise ReceiptError("Only the person who made a draft GRN deletes it.")
        for photo in grn.photos.all():
            photo.file.delete(save=False)
        grn.photos.all().delete()
        grn.delete()


# --- Reversal -----------------------------------------------------------------------------


def request_reversal(user: User, grn: GoodsReceipt, reason: str) -> GoodsReceipt:
    reason = (reason or "").strip()
    if not reason:
        raise ReceiptError("Give a reason for reversing the GRN.")
    with audit_context("goods_receipt_reversal_requested", reason), transaction.atomic():
        grn = GoodsReceipt.objects.select_for_update().get(pk=grn.pk)
        if not can_request_reversal(user, grn):
            raise ReceiptError("Only a confirmed GRN is reversed, at the stores person's request.")
        try:
            approvals.submit(
                user,
                REVERSAL,
                grn.pk,
                created_by=user,
                amount=None,
                division=grn.division,
                comment=reason,
                title=f"Reverse GRN {grn.number} (PO {grn.purchase_order.label})",
                link=f"/goods-receipts/{grn.pk}",
            )
        except ApprovalError as error:
            raise ReceiptError(str(error)) from None
        grn.status = St.REVERSAL_REQUESTED
        grn.reversal_reason = reason[:1000]
        grn.save(update_fields=["status", "reversal_reason"])
        return grn


def approve_reversal(user: User, grn: GoodsReceipt, comment: str = "") -> GoodsReceipt:
    with transaction.atomic():
        grn = GoodsReceipt.objects.select_for_update().get(pk=grn.pk)
        if grn.status != St.REVERSAL_REQUESTED:
            raise ReceiptError("No reversal of this GRN is waiting for the Director.")
        try:
            state = approvals.approve(user, REVERSAL, grn.pk, comment)
        except ApprovalError as error:
            raise ReceiptError(str(error)) from None
        if state.status != ApprovalState.Status.APPROVED:
            return grn
        with audit_context("goods_receipt_reversed", grn.reversal_reason):
            order = PurchaseOrder.objects.select_for_update().get(pk=grn.purchase_order_id)
            for line in grn.lines.all():
                po_line = PurchaseOrderLine.objects.select_for_update().get(pk=line.po_line_id)
                po_line.received_quantity = max(
                    po_line.received_quantity - line.good_quantity, Decimal("0")
                )
                po_line.save(update_fields=["received_quantity"])
            _po_status(order)
            grn.status = St.REVERSED
            grn.reversed_at = timezone.now()
            grn.save(update_fields=["status", "reversed_at"])
        return grn


def refuse_reversal(user: User, grn: GoodsReceipt, reason: str) -> GoodsReceipt:
    with transaction.atomic():
        grn = GoodsReceipt.objects.select_for_update().get(pk=grn.pk)
        if grn.status != St.REVERSAL_REQUESTED:
            raise ReceiptError("No reversal of this GRN is waiting for the Director.")
        try:
            approvals.send_back(user, REVERSAL, grn.pk, reason)
        except ApprovalError as error:
            raise ReceiptError(str(error)) from None
        with audit_context("goods_receipt_reversal_refused", reason):
            grn.status = St.CONFIRMED
            grn.save(update_fields=["status"])
        return grn


# --- Photos ---------------------------------------------------------------------------------


def add_photo(user: User, grn: GoodsReceipt, uploaded) -> GoodsReceiptPhoto:
    """A photo or scan (JPG, PNG or PDF, checked from the file itself, at most 20 MB). Added
    while the GRN is a draft or after it is confirmed; never removed once confirmed."""
    with audit_context("goods_receipt_photo_added"), transaction.atomic():
        grn = GoodsReceipt.objects.select_for_update().get(pk=grn.pk)
        if not can_enter(user) or grn.status == St.REVERSED:
            raise ReceiptError("Only the stores person adds photos to a GRN.")
        if grn.photos.count() >= MAX_PHOTOS:
            raise ReceiptError(f"A GRN can have at most {MAX_PHOTOS} photos.")
        if uploaded.size > MAX_FILE_BYTES:
            raise ReceiptError("The file is larger than 20 MB.")
        content = uploaded.read()
        kind = next((k for magic, k in FILE_TYPES.items() if content.startswith(magic)), None)
        if kind is None:
            raise ReceiptError("Only JPG, PNG and PDF files can be added.")
        content_type, extension = kind
        digest = hashlib.sha256(content).hexdigest()
        name = (uploaded.name or f"photo{extension}").replace("/", "_").replace("\\", "_")
        uploaded.seek(0)
        photo = GoodsReceiptPhoto(
            receipt=grn,
            file_name=name[-200:],
            content_type=content_type,
            size=len(content),
            sha256=digest,
            uploaded_by=user,
        )
        photo.file.save(f"{grn.number}-{digest[:12]}{extension}", uploaded, save=False)
        photo.save()
        return photo


def remove_photo(user: User, photo: GoodsReceiptPhoto) -> None:
    """Only while the GRN is a draft, by the person who made it."""
    with audit_context("goods_receipt_photo_removed"), transaction.atomic():
        grn = GoodsReceipt.objects.select_for_update().get(pk=photo.receipt_id)
        if not can_edit(user, grn):
            raise ReceiptError(
                "A photo is removed only from a draft GRN, by the person who made it."
            )
        photo.file.delete(save=False)
        photo.delete()
