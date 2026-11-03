"""Payment voucher rules (spec 4). P1-01: voucher types, kept by the Admin. P1-02: the
Clerk's voucher: create, edit while Draft or Returned, attach scans, submit for approval.

Who sees which vouchers (spec 1.1): approvers (Accountant, Director) all vouchers of their
divisions; the Clerk their own; the Cashier approved ones; view-only roles (Auditor,
Admin) all of their divisions.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max, Q, QuerySet, Sum
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import Account, TaxCode, TaxComponent
from apps.accounting.services import AccountingError
from apps.core import approvals
from apps.core.access import division_scope, effective_access, has_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, Division, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters.models import CompanyAccount, Supplier
from apps.masters.services import is_in_use, mark_used

from .models import (
    TYPE_CODE_REGEX,
    Voucher,
    VoucherAttachment,
    VoucherCancellation,
    VoucherLine,
    VoucherLineSplit,
    VoucherPrint,
    VoucherType,
)

CODE = re.compile(TYPE_CODE_REGEX)
CENT = Decimal("0.01")
MAX_LINES = 100
MAX_FILES = 30
MAX_FILE_BYTES = 20 * 1024 * 1024
FILE_TYPES = {  # what the file really is, read from its first bytes
    b"%PDF-": ("application/pdf", ".pdf"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", ".png"),
}
EDITABLE = (Voucher.Status.DRAFT, Voucher.Status.RETURNED)
OPEN = (
    Voucher.Status.SUBMITTED,
    Voucher.Status.ACCOUNTANT_APPROVED,
    Voucher.Status.DIRECTOR_APPROVED,
    Voucher.Status.PARTLY_PAID,
)
DOC = "voucher"


class VoucherError(Exception):
    pass


def _admin(user: User) -> None:
    if not has_access(user, "settings", "manage"):
        raise VoucherError("Only the Admin can change voucher types.")


def _code(value) -> str:
    code = (value or "").strip().upper()
    if not CODE.match(code):
        raise VoucherError(
            "The type code must be 2 to 10 letters or digits, starting with a letter, e.g. CHQ."
        )
    return code


# --- Voucher types (P1-01) --------------------------------------------------------------


def _apply(vt: VoucherType, values: dict) -> None:
    if "name" in values:
        name = " ".join((values["name"] or "").split())
        if not name:
            raise VoucherError("The type name is required.")
        if len(name) > 50:
            raise VoucherError("The type name can have at most 50 characters.")
        clash = VoucherType.objects.filter(name__iexact=name).exclude(pk=vt.pk)
        if clash.exists():
            raise VoucherError(f"There is already a voucher type called {name}.")
        vt.name = name
    if "payment_method" in values:
        if values["payment_method"] not in VoucherType.Method.values:
            raise VoucherError("Choose how this type is paid.")
        vt.payment_method = values["payment_method"]
    for flag in ("needs_payee", "is_advance"):
        if flag in values:
            setattr(vt, flag, bool(values[flag]))
    if "payee_category" in values:
        category = values["payee_category"] or ""
        if category and category not in Supplier.Category.values:
            raise VoucherError("Choose a payee category, or none for any payee.")
        vt.payee_category = category
    if "notes" in values:
        vt.notes = (values["notes"] or "").strip()[:300]
    if "sort_order" in values:
        try:
            vt.sort_order = max(0, min(int(values["sort_order"]), 32767))
        except (TypeError, ValueError):
            raise VoucherError("The order must be a whole number.") from None
    internal = vt.payment_method == VoucherType.Method.INTERNAL
    if internal and vt.needs_payee:
        vt.needs_payee = False  # money moves between the company's own accounts
    if not vt.needs_payee:
        if not internal:
            raise VoucherError("Only transfers between the company's own accounts have no payee.")
        if vt.payee_category or vt.is_advance:
            raise VoucherError("A type with no payee cannot limit payees or be an advance.")


def create_type(user: User, *, code, name, payment_method, reason="", **values) -> VoucherType:
    _admin(user)
    vt = VoucherType(code=_code(code), payment_method="")
    with audit_context("voucher_type_created", reason), transaction.atomic():
        if VoucherType.objects.filter(code=vt.code).exists():
            raise VoucherError(f"The type code {vt.code} is already used.")
        _apply(vt, {"name": name, "payment_method": payment_method, **values})
        vt.save()
        return vt


def update_type(user: User, vt: VoucherType, values: dict, reason: str = "") -> VoucherType:
    _admin(user)
    with transaction.atomic():
        vt = VoucherType.objects.select_for_update().get(pk=vt.pk)
        used = is_in_use(vt)
        event = "voucher_type_changed"
        if "code" in values:
            code = _code(values["code"])
            if code != vt.code:
                if used:
                    raise VoucherError(f"{vt.code} has been used on vouchers; its code is fixed.")
                if VoucherType.objects.filter(code=code).exclude(pk=vt.pk).exists():
                    raise VoucherError(f"The type code {code} is already used.")
                vt.code = code
        if used and any(
            key in values and values[key] != getattr(vt, key)
            for key in ("payment_method", "needs_payee", "is_advance")
        ):
            raise VoucherError(
                f"{vt.code} has been used on vouchers, so how it is paid cannot change. "
                "Add a new type and switch this one off."
            )
        _apply(vt, values)
        if "is_active" in values and bool(values["is_active"]) != vt.is_active:
            if not values["is_active"]:
                if not (reason or "").strip():
                    raise VoucherError("Give a reason for switching off the voucher type.")
                if not VoucherType.objects.filter(is_active=True).exclude(pk=vt.pk).exists():
                    raise VoucherError("At least one voucher type must stay in use.")
                event = "voucher_type_switched_off"
            else:
                event = "voucher_type_switched_on"
            vt.is_active = bool(values["is_active"])
        with audit_context(event, reason):
            vt.save()
        return vt


def delete_type(user: User, vt: VoucherType, reason: str) -> None:
    """Remove a type added by mistake; a type used on vouchers is switched off instead."""
    _admin(user)
    if not (reason or "").strip():
        raise VoucherError("Give a reason for deleting the voucher type.")
    with audit_context("voucher_type_deleted", reason), transaction.atomic():
        vt = VoucherType.objects.select_for_update().get(pk=vt.pk)
        if is_in_use(vt):
            raise VoucherError(f"{vt.code} has been used on vouchers; switch it off instead.")
        if not VoucherType.objects.filter(is_active=True).exclude(pk=vt.pk).exists():
            raise VoucherError("At least one voucher type must stay in use.")
        vt.delete()


# --- Who sees what ----------------------------------------------------------------------


def approved_only(user: User) -> bool:
    """True for a user (a Cashier) who sees only Director-approved vouchers."""
    access = effective_access(user)
    return (
        access.has("vouchers", "view")
        and not access.has("vouchers", "approve")
        and not access.has("vouchers", "enter")
        and access.can("record_payment")
    )


def visible(user: User, *, deleted: bool | None = False) -> QuerySet[Voucher]:
    """The vouchers this user may see: working vouchers; with deleted=True the deleted ones
    (the Deleted Vouchers report); with deleted=None both."""
    access = effective_access(user)
    rows = Voucher.objects.filter(division__in=division_scope(user))
    if deleted:
        rows = rows.filter(status=Voucher.Status.DELETED)
    elif deleted is not None:
        rows = rows.exclude(status=Voucher.Status.DELETED)
    if not access.has("vouchers", "view"):
        return rows.none()
    if access.has("vouchers", "approve"):
        return rows
    if access.has("vouchers", "enter"):
        return rows.filter(created_by=user)
    if access.can("record_payment"):
        return rows.filter(
            status__in=[
                Voucher.Status.DIRECTOR_APPROVED,
                Voucher.Status.PARTLY_PAID,
                Voucher.Status.PAID,
            ]
        )
    return rows


def _creator_editing(user: User, voucher: Voucher) -> None:
    if voucher.created_by_id != user.pk:
        raise VoucherError("Only the person who created the voucher can change it here.")
    if voucher.status not in EDITABLE:
        raise VoucherError(
            f"Voucher {voucher.number} is {voucher.get_status_display().lower()}; only a draft "
            "or a returned voucher can be changed by its creator."
        )


# --- Saving -----------------------------------------------------------------------------


@dataclass
class LineInput:
    amount: object
    invoice_no: str = ""
    invoice_date: date | None = None
    description: str = ""
    tax_code: TaxCode | None = None
    tax_amount: object = "0"
    supplier_invoice: object = None  # apps.purchasing.models.SupplierInvoice (P16-11)
    advance_order: object = None  # apps.purchasing.models.PurchaseOrder (P16-11a)


def _money(value, where: str, *, positive: bool) -> Decimal:
    if isinstance(value, float):
        raise VoucherError(f"{where}: amounts must be exact decimals, not floating point.")
    try:
        amount = Decimal(str(value if value not in (None, "") else "0").replace(",", ""))
    except InvalidOperation:
        raise VoucherError(f"{where}: the amount is not a number.") from None
    if not amount.is_finite() or amount != amount.quantize(CENT):
        raise VoucherError(f"{where}: amounts are to the cent.")
    if positive and amount <= 0:
        raise VoucherError(f"{where}: the amount must be more than zero.")
    if amount < 0:
        raise VoucherError(f"{where}: the amount cannot be negative.")
    if amount >= Decimal("1e16"):
        raise VoucherError(f"{where}: the amount is too large.")
    return amount


def _lines(voucher: Voucher, lines: list[LineInput]) -> list[VoucherLine]:
    if len(lines) > MAX_LINES:
        raise VoucherError(f"A voucher can have at most {MAX_LINES} lines.")
    built = []
    for number, line in enumerate(lines, start=1):
        where = f"Line {number}"
        amount = _money(line.amount, where, positive=True)
        if line.supplier_invoice is not None:
            built.append(_invoice_line(voucher, line.supplier_invoice, amount, number, where))
            continue
        if line.advance_order is not None:
            built.append(_advance_line(voucher, line, amount, number, where))
            continue
        if line.tax_code is not None:
            code = line.tax_code
            if not code.is_active or code.use == TaxCode.Use.SALES:
                raise VoucherError(f"{where}: the tax code {code.code} is not for purchases.")
            try:
                tax = taxes.calculate(code, amount, line.invoice_date or voucher.voucher_date).tax
            except Exception as error:  # noqa: BLE001 - shown to the Clerk as it is
                raise VoucherError(f"{where}: {error}") from None
        else:
            tax = _money(line.tax_amount, f"{where} tax", positive=False)
        if line.invoice_date and line.invoice_date > timezone.localdate():
            raise VoucherError(f"{where}: the invoice date is in the future.")
        built.append(
            VoucherLine(
                voucher=voucher,
                line_no=number,
                invoice_no=(line.invoice_no or "").strip()[:50],
                invoice_date=line.invoice_date,
                description=(line.description or "").strip()[:500],
                amount=amount,
                tax_code=line.tax_code,
                tax_amount=tax,
                division=voucher.division,
            )
        )
    return built


def _invoice_line(voucher: Voucher, invoice, amount: Decimal, number: int, where: str):
    """A line paying a matched supplier invoice (P16-11, spec 5A.5): it pays the supplier's
    account in Accounts payable, never more than what is still unpaid on the invoice."""
    from apps.purchasing import invoices  # purchasing reads this module

    if invoice.status != invoice.Status.POSTED:
        raise VoucherError(f"{where}: supplier invoice {invoice.invoice_no} is not matched yet.")
    if voucher.payee_id != invoice.supplier_id:
        raise VoucherError(f"{where}: supplier invoice {invoice.invoice_no} is of another payee.")
    if voucher.division_id != invoice.division_id:
        raise VoucherError(
            f"{where}: supplier invoice {invoice.invoice_no} is of division "
            f"{invoice.division.code}; pay it on a voucher of that division."
        )
    unpaid = invoices.unpaid(invoice, excluding=voucher)
    if amount > unpaid:
        raise VoucherError(
            f"{where}: {amount:,.2f} is more than the {unpaid:,.2f} still unpaid on supplier "
            f"invoice {invoice.invoice_no}. An invoice is never paid twice."
        )
    payable = Account.objects.filter(system_role="accounts_payable", is_active=True).first()
    if payable is None:
        raise VoucherError("There is no active Accounts payable account (Chart of accounts).")
    return VoucherLine(
        voucher=voucher,
        line_no=number,
        invoice_no=invoice.invoice_no,
        invoice_date=invoice.invoice_date,
        description=f"Supplier invoice {invoice.number}"[:500],
        amount=amount,
        tax_code=None,
        tax_amount=Decimal("0"),
        account=payable,
        division=invoice.division,
        supplier_invoice=invoice,
    )


ADVANCE_ORDER_STATUSES = ("approved", "partly_received")


def _advance_line(voucher: Voucher, given: LineInput, amount: Decimal, number: int, where: str):
    """An advance on an approved purchase order before the goods arrive (P16-11a, spec 5A.5):
    an exception the Director approves with the voucher. Coded to Advances to suppliers and
    set off against the supplier's invoice once paid; the advances on a PO never exceed it."""
    order = given.advance_order
    if order.status not in ADVANCE_ORDER_STATUSES:
        raise VoucherError(
            f"{where}: purchase order {order.label} is {order.get_status_display().lower()}; an "
            "advance is paid only on an approved PO still waiting for goods."
        )
    if voucher.payee_id != order.supplier_id:
        raise VoucherError(f"{where}: purchase order {order.label} is of another supplier.")
    if voucher.division_id != order.division_id:
        raise VoucherError(
            f"{where}: purchase order {order.label} is of division {order.division.code}."
        )
    prefix = f"Advance on PO {order.label}: "
    reason = (given.description or "").strip()
    reason = reason[len(prefix) :] if reason.startswith(prefix) else reason
    if not reason:
        raise VoucherError(f"{where}: say why this advance is needed (the Director approves it).")
    others = VoucherLine.objects.filter(advance_order=order).exclude(
        voucher__status__in=INVOICE_FREED
    )
    if voucher.pk:
        others = others.exclude(voucher=voucher)
    already = sum((line.amount + line.tax_amount for line in others), Decimal("0"))
    left = order.total_lkr - already
    if amount > left:
        raise VoucherError(
            f"{where}: {amount:,.2f} is more than the {max(left, Decimal('0')):,.2f} of purchase "
            f"order {order.label} not yet paid in advance."
        )
    account = Account.objects.filter(system_role="supplier_advances", is_active=True).first()
    if account is None:
        raise VoucherError("There is no active Advances to suppliers account (Chart of accounts).")
    return VoucherLine(
        voucher=voucher,
        line_no=number,
        invoice_no="",
        invoice_date=None,
        description=(prefix + reason)[:500],
        amount=amount,
        tax_code=None,
        tax_amount=Decimal("0"),
        account=account,
        division=order.division,
        advance_order=order,
    )


def _check_payee(vt: VoucherType, payee: Supplier | None, transfer_to) -> None:
    if vt.needs_payee:
        if transfer_to is not None:
            raise VoucherError("Only internal transfers have a receiving company account.")
        if payee is None:
            return  # may be chosen later; required to submit
        if not payee.is_active:
            raise VoucherError(f"The payee {payee.name} is deactivated.")
        if vt.payee_category and payee.category != vt.payee_category:
            wanted = Supplier.Category(vt.payee_category).label
            raise VoucherError(f"A {vt.name} voucher is paid to a payee of category {wanted}.")
    else:
        if payee is not None:
            raise VoucherError(f"A {vt.name} has no payee.")
        if transfer_to is not None and not transfer_to.is_active:
            raise VoucherError(f"The company account {transfer_to.code} is closed.")


def save(
    user: User,
    voucher: Voucher | None,
    *,
    voucher_type: VoucherType,
    division: Division | None = None,
    payee: Supplier | None = None,
    transfer_to: CompanyAccount | None = None,
    description: str = "",
    lines: list[LineInput] = (),
) -> Voucher:
    """Create a draft (numbered now, in its division) or change a draft or returned voucher.
    The lines are replaced; coding the Accountant gave a line is kept for the same line."""
    access = effective_access(user)
    if not access.has("vouchers", "enter"):
        raise VoucherError("Only the Clerk enters vouchers.")
    with audit_context("voucher_saved"), transaction.atomic():
        if voucher is None:
            if division is None or not division.is_active:
                raise VoucherError("Choose an active division.")
            if not division_scope(user).filter(pk=division.pk).exists():
                raise VoucherError(f"You do not work in division {division.code}.")
            today = timezone.localdate()
            try:
                number = allocate("voucher", division=division, on_date=today)
            except NumberSeriesError as error:
                raise VoucherError(str(error)) from None
            voucher = Voucher(number=number, division=division, voucher_date=today, created_by=user)
        else:
            voucher = Voucher.objects.select_for_update().get(pk=voucher.pk)
            _creator_editing(user, voucher)
            if division is not None and division.pk != voucher.division_id:
                raise VoucherError(
                    "The division is part of the voucher number and cannot change; "
                    "create a new voucher in the other division."
                )
        if not voucher_type.is_active and voucher_type.pk != voucher.voucher_type_id:
            raise VoucherError(f"The voucher type {voucher_type.name} is switched off.")
        _check_payee(voucher_type, payee, transfer_to)
        voucher.voucher_type = voucher_type
        voucher.payee = payee
        voucher.transfer_to = transfer_to
        voucher.description = (description or "").strip()[:500]
        if payee is not None:
            # One at a time per supplier, so two clerks cannot enter the same invoice at once.
            Supplier.objects.select_for_update().filter(pk=payee.pk).first()
        new_lines = _lines(voucher, list(lines))
        clashes = duplicate_invoices(voucher, new_lines)
        if clashes:
            raise VoucherError(
                " ".join(clashes) + " The same supplier invoice cannot be entered twice."
            )
        coding = {}
        if voucher.pk is not None:
            coding = {
                line.line_no: (line.account_id, line.division_id, line.job_ref, line.wht_component)
                for line in voucher.lines.select_related("wht_component")
            }
        for line in new_lines:
            if line.line_no not in coding:
                continue
            account_id, division_id, job_ref, wht = coding[line.line_no]
            if not (line.supplier_invoice_id or line.advance_order_id):
                line.account_id, line.division_id, line.job_ref = account_id, division_id, job_ref
                line.division_id = line.division_id or voucher.division_id
            if wht is not None and not line.advance_order_id and voucher.payee_id:
                # The WHT the Accountant chose stays, worked out again on the new amount.
                set_wht(voucher, line, wht, f"Line {line.line_no}")
        _set_totals(voucher, new_lines)
        voucher.save()
        voucher.lines.all().delete()
        for line in new_lines:
            line.save()
        return voucher


# A supplier invoice on these vouchers no longer counts: it may be entered again.
INVOICE_FREED = (
    Voucher.Status.DELETED,
    Voucher.Status.REJECTED,
    Voucher.Status.AMENDED,
    Voucher.Status.CANCELLED,
)


def invoice_key(invoice_no: str) -> str:
    """The same invoice however it is typed: case and spaces are ignored ("inv 77" = "INV77")."""
    return re.sub(r"\s+", "", invoice_no or "").upper()


def duplicate_invoices(voucher: Voucher, lines=None) -> list[str]:
    """The same supplier and invoice number on another voucher (spec 4.4). Refused on saving
    (owner's decision, 31 Oct 2026); also checked by the database."""
    if voucher.payee_id is None:
        return []
    others = VoucherLine.objects.filter(voucher__payee_id=voucher.payee_id).exclude(invoice_no="")
    if voucher.pk:
        others = others.exclude(voucher_id=voucher.pk)
    others = list(others.exclude(voucher__status__in=INVOICE_FREED).select_related("voucher"))
    from apps.purchasing.models import SupplierInvoice  # P16-10; purchasing reads vouchers

    invoices = list(
        SupplierInvoice.objects.filter(supplier_id=voucher.payee_id).exclude(
            status=SupplierInvoice.Status.CANCELLED
        )
    )
    warnings = []
    mine = lines if lines is not None else list(voucher.lines.all())
    seen = set()
    others = [o for o in others if o.supplier_invoice_id is None]
    for line in mine:
        if getattr(line, "supplier_invoice_id", None):
            continue  # checked by what is unpaid on the invoice
        key = invoice_key(line.invoice_no)
        if not key or key in seen:
            continue
        seen.add(key)
        numbers = sorted({o.voucher.number for o in others if invoice_key(o.invoice_no) == key})
        if numbers:
            warnings.append(
                f"Invoice {line.invoice_no} of this payee is already on voucher "
                f"{', '.join(numbers)}."
            )
        entered = sorted(i.number for i in invoices if invoice_key(i.invoice_no) == key)
        if entered:
            warnings.append(
                f"Invoice {line.invoice_no} of this payee is already entered as supplier "
                f"invoice {', '.join(entered)}."
            )
    return warnings


# --- Attachments ------------------------------------------------------------------------


def _kind(head: bytes) -> tuple[str, str] | None:
    for magic, kind in FILE_TYPES.items():
        if head.startswith(magic):
            return kind
    return None


def add_attachment(user: User, voucher: Voucher, uploaded) -> tuple[VoucherAttachment, list]:
    """Attach a scan. PDF, JPG or PNG (checked from the file itself), at most 20 MB.
    Returns the attachment and warnings (the same file already in the system)."""
    with audit_context("voucher_attachment_added"), transaction.atomic():
        voucher = Voucher.objects.select_for_update().get(pk=voucher.pk)
        _creator_editing(user, voucher)
        if voucher.attachments.count() >= MAX_FILES:
            raise VoucherError(f"A voucher can have at most {MAX_FILES} files.")
        if uploaded.size > MAX_FILE_BYTES:
            raise VoucherError("The file is larger than 20 MB.")
        content = uploaded.read()
        kind = _kind(content[:8])
        if kind is None:
            raise VoucherError("Only PDF, JPG and PNG files can be attached.")
        content_type, extension = kind
        digest = hashlib.sha256(content).hexdigest()
        same = (
            VoucherAttachment.objects.filter(sha256=digest)
            .exclude(voucher=voucher)
            .exclude(voucher__status__in=[Voucher.Status.DELETED, Voucher.Status.AMENDED])
            .select_related("voucher")
        )
        warnings = [
            f"This file is already attached to voucher {number}."
            for number in sorted({a.voucher.number for a in same})
        ]
        name = (uploaded.name or f"scan{extension}").replace("/", "_").replace("\\", "_")[-200:]
        uploaded.seek(0)
        attachment = VoucherAttachment(
            voucher=voucher,
            file_name=name,
            content_type=content_type,
            size=len(content),
            sha256=digest,
            uploaded_by=user,
        )
        attachment.file.save(f"{voucher.number}-{digest[:12]}{extension}", uploaded, save=False)
        attachment.save()
        return attachment, warnings


def remove_attachment(user: User, attachment: VoucherAttachment) -> None:
    with audit_context("voucher_attachment_removed"), transaction.atomic():
        voucher = Voucher.objects.select_for_update().get(pk=attachment.voucher_id)
        _creator_editing(user, voucher)
        attachment.delete()


# --- Submitting and following the approval ----------------------------------------------


STATUS_FROM_ENGINE = {
    ApprovalState.Status.APPROVED: Voucher.Status.DIRECTOR_APPROVED,
    ApprovalState.Status.RETURNED: Voucher.Status.RETURNED,
    ApprovalState.Status.REJECTED: Voucher.Status.REJECTED,
}


def sync_status(voucher: Voucher) -> Voucher:
    """Keep the voucher's status in step with its approval (levels 2 and 3)."""
    state = approvals.state_of(DOC, voucher.pk)
    if state is None or state.status == ApprovalState.Status.WITHDRAWN:
        return voucher
    if state.status == ApprovalState.Status.IN_PROGRESS:
        status = (
            Voucher.Status.SUBMITTED
            if state.current_level == state.route[0]["level"]
            else Voucher.Status.ACCOUNTANT_APPROVED
        )
    else:
        status = STATUS_FROM_ENGINE[state.status]
    if voucher.status != status:
        voucher.status = status
        voucher.save(update_fields=["status", "updated_at"])
        if status == Voucher.Status.REJECTED:
            _restore_parent(voucher)
    return voucher


def title(voucher: Voucher) -> str:
    who = voucher.payee.name if voucher.payee else voucher.voucher_type.name
    return f"Voucher {voucher.number} – {who} – LKR {voucher.total_amount:,.2f}"


def submit(user: User, voucher: Voucher, comment: str = "") -> Voucher:
    """Send a draft or returned voucher to the Accountant (L2), then the Director (L3)."""
    with audit_context("voucher_submitted", comment), transaction.atomic():
        voucher = Voucher.objects.select_for_update().get(pk=voucher.pk)
        _creator_editing(user, voucher)
        vt = voucher.voucher_type
        if not vt.is_active:
            raise VoucherError(f"The voucher type {vt.name} is switched off; choose another.")
        lines = list(voucher.lines.select_related("tax_code"))
        if not lines:
            raise VoucherError("Add at least one invoice line.")
        if voucher.total_amount <= 0:
            raise VoucherError("The voucher total must be more than zero.")
        if vt.needs_payee and voucher.payee is None:
            raise VoucherError("Choose the payee.")
        _check_payee(vt, voucher.payee, voucher.transfer_to)
        if not vt.needs_payee and voucher.transfer_to is None:
            raise VoucherError("Choose the company account the money goes to.")
        scanned_on_invoices = all(line.supplier_invoice_id for line in lines)
        if vt.needs_payee and not voucher.attachments.exists() and not scanned_on_invoices:
            raise VoucherError("Attach the scanned invoice or receipt before submitting.")
        try:
            approvals.submit(
                user,
                DOC,
                voucher.pk,
                created_by=voucher.created_by,
                amount=voucher.total_amount,
                division=voucher.division,
                subtype=vt.code,
                comment=comment,
                title=title(voucher),
                link=f"/vouchers/{voucher.pk}",
            )
        except ApprovalError as error:
            raise VoucherError(str(error)) from None
        voucher.submitted_at = timezone.now()
        voucher.save(update_fields=["submitted_at", "updated_at"])
        mark_used(vt)
        if voucher.payee:
            mark_used(voucher.payee)
        for line in lines:
            if line.tax_code:
                taxes.mark_used(line.tax_code)
                for part in line.tax_code.lines.select_related("component"):
                    taxes.mark_used(part.component)
        return sync_status(voucher)


# --- Payee balance ----------------------------------------------------------------------


def payee_balance(payee: Supplier) -> dict:
    """What is owed to the payee on vouchers: waiting for approval, and approved but not
    yet paid. Payments (P1-07) will reduce the approved figure."""
    rows = Voucher.objects.filter(payee=payee)
    waiting = rows.filter(
        status__in=[Voucher.Status.SUBMITTED, Voucher.Status.ACCOUNTANT_APPROVED]
    ).aggregate(total=Sum("total_amount"))["total"] or Decimal("0")
    approved = rows.filter(
        Q(status=Voucher.Status.DIRECTOR_APPROVED) | Q(status=Voucher.Status.PARTLY_PAID)
    ).aggregate(total=Sum("total_amount"))["total"] or Decimal("0")
    return {
        "waiting_approval": f"{waiting:.2f}",
        "approved_unpaid": f"{approved:.2f}",
        "outstanding": f"{waiting + approved:.2f}",
    }


# --- The Accountant's review and the approvals (P1-03) ----------------------------------


def waiting(user: User) -> QuerySet[Voucher]:
    """Vouchers waiting at a level this user can approve now (their queue)."""
    ids = [state.document_id for state in approvals.waiting_for(user, DOC)]
    return visible(user).filter(pk__in=ids)


def _acting_state(user: User, voucher: Voucher) -> ApprovalState:
    state = approvals.state_of(DOC, voucher.pk)
    if state is None or state.status != ApprovalState.Status.IN_PROGRESS:
        raise VoucherError(f"Voucher {voucher.number} is not waiting for approval.")
    refusal = approvals.why_not(user, state)
    if refusal:
        raise VoucherError(refusal)
    return state


NOT_TO_CODE = {"bank", "accounts_receivable", "accounts_payable"}


def _check_account(voucher: Voucher, account: Account, where: str) -> None:
    if not account.is_active or account.merged_into_id:
        raise VoucherError(f"{where}: {account.name} is inactive or merged.")
    internal = voucher.voucher_type.payment_method == VoucherType.Method.INTERNAL
    if internal and account.account_type != "bank":
        raise VoucherError(f"{where}: an internal transfer goes to a Bank-type account.")
    if not internal and account.account_type in NOT_TO_CODE:
        raise VoucherError(
            f"{where}: {account.name} cannot be the account of a payment; choose the expense, "
            "asset or liability the payment is for."
        )


@dataclass
class SplitInput:
    division: Division
    amount: object = None
    percent: object = None


@dataclass
class CodingInput:
    line_no: int
    account: Account | None = None
    division: Division | None = None
    tax_code: TaxCode | None = None
    tax_amount: object = "0"
    job_ref: str = ""
    splits: list = ()
    wht_component: TaxComponent | None = None


def _percent(value, where: str) -> Decimal:
    try:
        percent = Decimal(str(value))
    except InvalidOperation:
        raise VoucherError(f"{where}: the percentage is not a number.") from None
    if not percent.is_finite() or percent <= 0 or percent > 100:
        raise VoucherError(f"{where}: a percentage is more than 0 and at most 100.")
    if percent != percent.quantize(Decimal("0.0001")):
        raise VoucherError(f"{where}: a percentage has at most four decimals.")
    return percent


def _split(total: Decimal, splits: list[SplitInput], where: str) -> list[VoucherLineSplit]:
    """The parts of a line, by amount or by percentage. They add up to the line total; with
    percentages, the last part takes the cent left over by rounding."""
    if len(splits) < 2:
        raise VoucherError(f"{where}: a split needs at least two divisions.")
    divisions = [s.division for s in splits]
    if len({d.pk for d in divisions}) != len(divisions):
        raise VoucherError(f"{where}: each division can appear once in a split.")
    for division in divisions:
        if not division.is_active:
            raise VoucherError(f"{where}: division {division.code} is deactivated.")
    by_percent = [s.percent not in (None, "") for s in splits]
    if any(by_percent) and not all(by_percent):
        raise VoucherError(f"{where}: split either by amount or by percentage, not both.")
    parts = []
    if all(by_percent):
        percents = [_percent(s.percent, where) for s in splits]
        if sum(percents) != 100:
            raise VoucherError(f"{where}: the percentages add up to {sum(percents)}, not 100.")
        amounts = [(total * p / 100).quantize(CENT, ROUND_HALF_UP) for p in percents[:-1]]
        amounts.append(total - sum(amounts, Decimal("0")))
        for s, p, a in zip(splits, percents, amounts, strict=True):
            if a <= 0:
                raise VoucherError(f"{where}: a part of the split is not more than zero.")
            parts.append(VoucherLineSplit(division=s.division, amount=a, percent=p))
    else:
        for s in splits:
            parts.append(
                VoucherLineSplit(
                    division=s.division,
                    amount=_money(s.amount, where, positive=True),
                )
            )
        added = sum((p.amount for p in parts), Decimal("0"))
        if added != total:
            raise VoucherError(
                f"{where}: the split adds up to {added:,.2f}, not the line total {total:,.2f}."
            )
    return parts


def code_lines(user: User, voucher: Voucher, codings: list[CodingInput]) -> Voucher:
    """The approver at the waiting level (the Accountant at L2) sets each line's account,
    division or division split, tax and job reference. The amounts stay as entered."""
    with audit_context("voucher_coded"), transaction.atomic():
        voucher = Voucher.objects.select_for_update().get(pk=voucher.pk)
        state = _acting_state(user, voucher)
        before, wht_before = voucher.total_amount, voucher.wht_total
        lines = {line.line_no: line for line in voucher.lines.select_for_update()}
        for coding in codings:
            where = f"Line {coding.line_no}"
            line = lines.get(coding.line_no)
            if line is None:
                raise VoucherError(f"{where} is not on this voucher.")
            if line.advance_order_id and coding.wht_component is not None:
                raise VoucherError(
                    f"{where}: an advance is paid in full; WHT is kept from the invoice payment."
                )
            set_wht(voucher, line, coding.wht_component, where)
            if line.supplier_invoice_id or line.advance_order_id:
                # Pays a matched supplier invoice (Accounts payable) or an advance on a PO
                # (Advances to suppliers): the account is fixed, no tax (P16-11, P16-11a).
                line.job_ref = (coding.job_ref or "").strip()[:50]
                line.save(update_fields=["job_ref", "wht_component", "wht_rate", "wht_amount"])
                continue
            if coding.account is not None:
                _check_account(voucher, coding.account, where)
            line.account = coding.account
            if coding.tax_code is not None:
                code = coding.tax_code
                if not code.is_active or code.use == TaxCode.Use.SALES:
                    raise VoucherError(f"{where}: the tax code {code.code} is not for purchases.")
                try:
                    on = line.invoice_date or voucher.voucher_date
                    line.tax_amount = taxes.calculate(code, line.amount, on).tax
                except Exception as error:  # noqa: BLE001 - shown as it is
                    raise VoucherError(f"{where}: {error}") from None
            else:
                line.tax_amount = _money(coding.tax_amount, f"{where} tax", positive=False)
            line.tax_code = coding.tax_code
            line.job_ref = (coding.job_ref or "").strip()[:50]
            line.splits.all().delete()
            if coding.splits:
                parts = _split(line.amount + line.tax_amount, list(coding.splits), where)
                line.division = None
                line.save()
                for part in parts:
                    part.line = line
                    part.save()
            else:
                if coding.division is not None and not coding.division.is_active:
                    raise VoucherError(f"{where}: division {coding.division.code} is deactivated.")
                line.division = coding.division
                line.save()
        _set_totals(voucher, lines.values())
        if voucher.total_amount <= 0:
            raise VoucherError("The voucher total must be more than zero.")
        voucher.save()
        changes = []
        if voucher.total_amount != before:
            changes.append(f"Total: {before:,.2f} → {voucher.total_amount:,.2f}")
        if voucher.wht_total != wht_before:
            changes.append(f"WHT: {wht_before:,.2f} → {voucher.wht_total:,.2f}")
        if changes and state.current_level != state.route[0]["level"]:
            # A later approver changed the tax and so the amount: the Accountant checks again.
            _send_down(user, voucher, changes)
        return voucher


def wht_choices(on: date) -> list[TaxComponent]:
    """The withholding taxes that can be kept on a payment on a date: active, with an account
    for the tax kept and a confirmed rate. None until the Director confirms a rate (P2-12:
    built switched off)."""
    found = []
    components = TaxComponent.objects.filter(
        kind=TaxComponent.Kind.WITHHELD, is_active=True, sales_account__isnull=False
    )
    for component in components.order_by("code"):
        try:
            taxes.rate_on(component, on)
        except AccountingError:
            continue
        found.append(component)
    return found


def set_wht(voucher: Voucher, line: VoucherLine, component: TaxComponent | None, where: str):
    """Withholding tax on a line (P2-12): the rate in force on the invoice date, on the amount
    before VAT, rounded half-up to the cent. It is kept from the payment to the payee."""
    if component is None:
        line.wht_component, line.wht_rate, line.wht_amount = None, Decimal("0"), Decimal("0")
        return
    if voucher.payee_id is None:
        raise VoucherError(f"{where}: withholding tax is kept only from a payment to a payee.")
    if component.kind != TaxComponent.Kind.WITHHELD or not component.is_active:
        raise VoucherError(f"{where}: {component.code} is not an active withholding tax.")
    if component.sales_account_id is None:
        raise VoucherError(
            f"{where}: {component.code} has no account for the tax kept; set it under "
            "Settings → Tax rates."
        )
    on = line.invoice_date or voucher.voucher_date
    try:
        rate = taxes.rate_on(component, on).rate
    except AccountingError as error:
        raise VoucherError(f"{where}: {error}") from None
    taxes.mark_used(component)
    line.wht_component = component
    line.wht_rate = rate
    line.wht_amount = (line.amount * rate / Decimal("100")).quantize(CENT, ROUND_HALF_UP)


def _set_totals(voucher: Voucher, lines) -> None:
    lines = list(lines)
    voucher.total_amount = sum((line.total for line in lines), Decimal("0"))
    voucher.wht_total = sum((line.wht_amount for line in lines), Decimal("0"))


def payable(voucher: Voucher) -> Decimal:
    """What the payee receives: the total less the withholding tax kept (P2-12)."""
    return voucher.total_amount - voucher.wht_total


def uncoded_lines(voucher: Voucher) -> list[int]:
    return [
        line.line_no
        for line in voucher.lines.prefetch_related("splits")
        if line.account_id is None or (line.division_id is None and not line.splits.all())
    ]


def approve(user: User, voucher: Voucher, comment: str = "") -> Voucher:
    """Approve at the waiting level. The Accountant (L2) can only approve once every line
    has its account and division (or division split)."""
    with transaction.atomic():
        voucher = Voucher.objects.select_for_update().get(pk=voucher.pk)
        state = _acting_state(user, voucher)
        if state.current_level == state.route[0]["level"]:
            missing = uncoded_lines(voucher)
            if missing:
                raise VoucherError(
                    "Give every line its account and division before approving: line "
                    + ", ".join(str(n) for n in missing)
                    + "."
                )
        try:
            approvals.approve(user, DOC, voucher.pk, comment)
        except ApprovalError as error:
            raise VoucherError(str(error)) from None
        return sync_status(voucher)


def send_back(user: User, voucher: Voucher, reason: str) -> Voucher:
    """Return to the Clerk to correct and resubmit (reason required)."""
    with transaction.atomic():
        voucher = Voucher.objects.select_for_update().get(pk=voucher.pk)
        _acting_state(user, voucher)
        try:
            approvals.send_back(user, DOC, voucher.pk, reason)
        except ApprovalError as error:
            raise VoucherError(str(error)) from None
        return sync_status(voucher)


def reject(user: User, voucher: Voucher, reason: str) -> Voucher:
    """Reject for good (reason required)."""
    with transaction.atomic():
        voucher = Voucher.objects.select_for_update().get(pk=voucher.pk)
        _acting_state(user, voucher)
        try:
            approvals.reject(user, DOC, voucher.pk, reason)
        except ApprovalError as error:
            raise VoucherError(str(error)) from None
        return sync_status(voucher)


# --- The Director's page: several decisions at once (P1-04) -----------------------------


@dataclass
class Decision:
    voucher_id: int
    decision: str  # "approve" or "reject"
    reason: str = ""


class BulkRefused(VoucherError):
    def __init__(self, errors: dict[int, str]):
        super().__init__("Nothing was confirmed: " + "; ".join(errors.values()))
        self.errors = errors


def decide_many(user: User, decisions: list[Decision]) -> list[Voucher]:
    """Confirm the ticked Approve and Reject boxes together, all or nothing: if any row is
    refused (a Reject without a reason, a voucher no longer waiting for this user…), nothing
    is confirmed and every refused row is reported by voucher id."""
    if not decisions:
        raise VoucherError("Tick Approve or Reject on at least one voucher.")
    errors: dict[int, str] = {}
    seen = set()
    for d in decisions:
        if d.voucher_id in seen:
            errors[d.voucher_id] = "The voucher is ticked twice."
        seen.add(d.voucher_id)
        if d.decision not in ("approve", "reject"):
            errors[d.voucher_id] = "Choose Approve or Reject."
        elif d.decision == "reject" and not (d.reason or "").strip():
            errors[d.voucher_id] = "Give a reason for rejecting."
    if errors:
        raise BulkRefused(errors)
    allowed = {v.pk: v for v in visible(user).filter(pk__in=seen)}
    done = []
    with transaction.atomic():
        for d in decisions:
            voucher = allowed.get(d.voucher_id)
            if voucher is None:
                errors[d.voucher_id] = "Voucher not found."
                continue
            try:
                with transaction.atomic():
                    if d.decision == "approve":
                        done.append(approve(user, voucher, d.reason))
                    else:
                        done.append(reject(user, voucher, d.reason))
            except VoucherError as error:
                errors[d.voucher_id] = f"{voucher.number}: {error}"
        if errors:
            transaction.set_rollback(True)
    if errors:
        raise BulkRefused(errors)
    return done


# --- Row actions: edit while waiting, delete, print (P1-04b) ----------------------------


def _send_down(user: User, voucher: Voucher, changes: list[str]) -> Voucher:
    try:
        approvals.send_down(user, DOC, voucher.pk, "Changed: " + "; ".join(changes))
    except ApprovalError as error:
        raise VoucherError(str(error)) from None
    return sync_status(voucher)


def waiting_levels(user: User) -> dict[int, bool]:
    """Vouchers this user can act on now: voucher id -> True when waiting at the first
    approval level (the Accountant's), False at a later one (the Director's)."""
    return {
        state.document_id: state.current_level == state.route[0]["level"]
        for state in approvals.waiting_for(user, DOC)
    }


def can_delete(user: User, voucher: Voucher) -> str | None:
    """Why this user cannot delete the voucher, or None if they can (spec 4.4)."""
    access = effective_access(user)
    if voucher.status == Voucher.Status.DELETED:
        return f"Voucher {voucher.number} is already deleted."
    if voucher.status in (Voucher.Status.PARTLY_PAID, Voucher.Status.PAID):
        return f"Voucher {voucher.number} has payments and cannot be deleted."
    if voucher.status == Voucher.Status.AMENDED:
        return f"Voucher {voucher.number} is replaced by an amendment; delete that instead."
    if pending_cancellation(voucher):
        return "A cancellation of this voucher is waiting for the Director."
    if voucher.status == Voucher.Status.DRAFT:
        if voucher.created_by_id == user.pk or access.has("settings", "manage"):
            return None
        return "Only its creator or the Admin can delete a draft."
    if not access.can("delete_submitted_voucher"):
        return "Only the Director or the Admin can delete a submitted voucher."
    return None


def actions(user: User, voucher: Voucher, waiting: dict[int, bool] | None = None) -> list[str]:
    """The row actions this user may take on the voucher (spec 4.4, row actions menu).
    "edit": the Clerk's form; "edit_coding": the Accountant's review at L2; "revise": the
    Director's changes at L3. The server checks each one again when it is used."""
    allowed = ["resources", "print"]
    if voucher.status == Voucher.Status.DELETED:
        return allowed
    if waiting is None:
        waiting = waiting_levels(user)
    if (
        voucher.created_by_id == user.pk
        and voucher.status in EDITABLE
        and has_access(user, "vouchers", "enter")
    ):
        allowed.append("edit")
    elif voucher.pk in waiting:
        allowed.append("edit_coding" if waiting[voucher.pk] else "revise")
    elif (
        voucher.status == Voucher.Status.DIRECTOR_APPROVED
        and has_access(user, "vouchers", "enter")
        and not pending_cancellation(voucher)
    ):
        allowed.append("amend")  # after Director approval, Edit becomes Amend
    if why_not_cancel(user, voucher) is None:
        allowed.append("cancel")
    if effective_access(user).can("record_payment"):
        from apps.payments.services import why_not_payable

        if why_not_payable(voucher) is None:
            allowed.append("pay")
    if can_delete(user, voucher) is None:
        allowed.append("delete")
    return allowed


def delete(user: User, voucher: Voucher, reason: str = "") -> Voucher:
    """Mark the voucher Deleted (spec 4.4). It leaves every working list but keeps its
    number, lines, files and history, listed in the Deleted Vouchers report. A submitted
    voucher needs the Director or the Admin and a reason; a voucher with payments cannot be
    deleted (also refused by the database)."""
    reason = (reason or "").strip()[:500]
    with audit_context("voucher_deleted", reason), transaction.atomic():
        voucher = Voucher.objects.select_for_update().get(pk=voucher.pk)
        refusal = can_delete(user, voucher)
        if refusal:
            raise VoucherError(refusal)
        if voucher.status != Voucher.Status.DRAFT and not reason:
            raise VoucherError("Give a reason for deleting a submitted voucher.")
        if approvals.state_of(DOC, voucher.pk) is not None:
            try:
                approvals.withdraw(user, DOC, voucher.pk, reason or "Voucher deleted")
            except ApprovalError as error:
                raise VoucherError(str(error)) from None
        was_approved = voucher.status == Voucher.Status.DIRECTOR_APPROVED
        voucher.status = Voucher.Status.DELETED
        voucher.deleted_at = timezone.now()
        voucher.deleted_by = user
        voucher.delete_reason = reason
        voucher.save()
        if not was_approved:
            # An amendment dropped before approval: the original stands again. (Deleting an
            # approved amendment does not bring the replaced voucher back to be paid.)
            _restore_parent(voucher)
        return voucher


def _line_text(line: VoucherLine) -> dict:
    return {
        "invoice": line.invoice_no,
        "date": line.invoice_date,
        "amount": line.amount,
        "tax": line.tax_amount,
        "tax_code": line.tax_code_id,
        "supplier_invoice": line.supplier_invoice_id,
        "advance_order": line.advance_order_id,
    }


def _changes(voucher: Voucher, payee, transfer_to, new_lines: list[VoucherLine]) -> list[str]:
    """What a change by a later approver alters in the payee, amounts or lines."""
    changes = []
    if payee != voucher.payee:
        changes.append(
            f"Payee: {voucher.payee.name if voucher.payee else '—'} → "
            f"{payee.name if payee else '—'}"
        )
    if transfer_to != voucher.transfer_to:
        changes.append(
            f"Transfer to: {voucher.transfer_to.code if voucher.transfer_to else '—'} → "
            f"{transfer_to.code if transfer_to else '—'}"
        )
    old = {line.line_no: line for line in voucher.lines.all()}
    new = {line.line_no: line for line in new_lines}
    for number in sorted(set(old) | set(new)):
        if number not in new:
            changes.append(f"Line {number} removed ({old[number].total:,.2f})")
        elif number not in old:
            changes.append(f"Line {number} added ({new[number].total:,.2f})")
        else:
            a, b = _line_text(old[number]), _line_text(new[number])
            labels = {
                "invoice": "invoice no.",
                "date": "invoice date",
                "amount": "amount",
                "tax": "tax",
                "tax_code": "tax code",
            }
            for key, label in labels.items():
                if a[key] != b[key]:
                    if key in ("amount", "tax"):
                        changes.append(f"Line {number} {label}: {a[key]:,.2f} → {b[key]:,.2f}")
                    elif key != "tax_code" or a["tax"] == b["tax"]:
                        changes.append(f"Line {number} {label}: {a[key] or '—'} → {b[key] or '—'}")
    total = sum((line.total for line in new_lines), Decimal("0"))
    if total != voucher.total_amount:
        changes.append(f"Total: {voucher.total_amount:,.2f} → {total:,.2f}")
    return changes


def revise(
    user: User,
    voucher: Voucher,
    *,
    payee: Supplier | None = None,
    transfer_to: CompanyAccount | None = None,
    description: str = "",
    lines: list[LineInput] = (),
) -> Voucher:
    """Edit by an approver while the voucher waits for them (spec 4.4). The description can
    be corrected at any level (coding has its own page). A change to the payee, amounts or
    lines can only come from a later level (the Director): it sends the voucher back to the
    Accountant, with the changes listed in the approval history."""
    with audit_context("voucher_revised"), transaction.atomic():
        voucher = Voucher.objects.select_for_update().get(pk=voucher.pk)
        state = _acting_state(user, voucher)
        vt = voucher.voucher_type
        _check_payee(vt, payee, transfer_to)
        if vt.needs_payee and payee is None:
            raise VoucherError("Choose the payee.")
        if not vt.needs_payee and transfer_to is None:
            raise VoucherError("Choose the company account the money goes to.")
        new_lines = _lines(voucher, list(lines))
        if not new_lines:
            raise VoucherError("Add at least one invoice line.")
        changes = _changes(voucher, payee, transfer_to, new_lines)
        if changes and state.current_level == state.route[0]["level"]:
            raise VoucherError(
                "Return the voucher to the Clerk to change its payee, amounts or lines."
            )
        voucher.description = (description or "").strip()[:500]
        if not changes:
            voucher.save()
            return voucher
        old = {
            line.line_no: line
            for line in voucher.lines.select_related("wht_component").prefetch_related("splits")
        }
        kept_splits = {}
        for line in new_lines:
            before = old.get(line.line_no)
            if before is None:
                continue
            if before.wht_component_id and not line.advance_order_id and payee is not None:
                set_wht(voucher, line, before.wht_component, f"Line {line.line_no}")
            if line.supplier_invoice_id or line.advance_order_id:
                continue
            line.account_id, line.job_ref = before.account_id, before.job_ref
            splits = list(before.splits.all())
            if before.total == line.total and splits:
                line.division_id = None
                kept_splits[line.line_no] = [(p.division_id, p.amount, p.percent) for p in splits]
            else:
                # A changed amount needs its division split again (the Accountant checks).
                line.division_id = before.division_id or (None if splits else voucher.division_id)
        voucher.payee = payee
        voucher.transfer_to = transfer_to
        _set_totals(voucher, new_lines)
        voucher.save()
        voucher.lines.all().delete()
        for line in new_lines:
            line.save()
            for division_id, amount, percent in kept_splits.get(line.line_no, []):
                VoucherLineSplit.objects.create(
                    line=line, division_id=division_id, amount=amount, percent=percent
                )
        if payee:
            mark_used(payee)
        return _send_down(user, voucher, changes)


def record_print(user: User, voucher: Voucher, paper: str) -> VoucherPrint:
    """Log a print (audit log too); every print after the first is a copy."""
    if paper not in VoucherPrint.Paper.values:
        raise VoucherError("Choose A4 or A5 paper.")
    with audit_context("voucher_printed"), transaction.atomic():
        voucher = Voucher.objects.select_for_update().get(pk=voucher.pk)
        return VoucherPrint.objects.create(
            voucher=voucher,
            printed_by=user,
            paper=paper,
            is_copy=voucher.prints.exists(),
        )


# --- Amendments (P1-05) ---------------------------------------------------------------

REVISION_SUFFIX = re.compile(r"-R\d+$")


def _restore_parent(voucher: Voucher) -> None:
    """An amendment rejected or deleted: the voucher it would have replaced stands again,
    approved as before."""
    if voucher.parent_id is None:
        return
    parent = Voucher.objects.select_for_update().get(pk=voucher.parent_id)
    if parent.status == Voucher.Status.AMENDED:
        parent.status = Voucher.Status.DIRECTOR_APPROVED
        parent.save(update_fields=["status", "updated_at"])


def amend(user: User, voucher: Voucher, reason: str) -> Voucher:
    """Start an amendment of a Director-approved, unpaid voucher (spec 4.2). The approved
    voucher is never changed: a new revision (number -R1, -R2, …, linked to it) is created
    as a draft with the same payee, lines, coding and files, for the person who started it
    to correct and submit; it passes the Accountant and the Director again. Until then the
    original is marked Amended and cannot be paid; if the amendment is rejected or deleted,
    the original stands again."""
    reason = (reason or "").strip()[:500]
    if not reason:
        raise VoucherError("Say why the voucher is being amended.")
    if not has_access(user, "vouchers", "enter"):
        raise VoucherError("Only the Clerk or the Accountant starts an amendment.")
    with audit_context("voucher_amended", reason), transaction.atomic():
        voucher = Voucher.objects.select_for_update().get(pk=voucher.pk)
        if voucher.status != Voucher.Status.DIRECTOR_APPROVED:
            raise VoucherError(
                f"Voucher {voucher.number} is {voucher.get_status_display().lower()}; only a "
                "Director-approved voucher with no payment can be amended."
            )
        if pending_cancellation(voucher):
            raise VoucherError("A cancellation of this voucher is waiting for the Director.")
        base = REVISION_SUFFIX.sub("", voucher.number)
        family = Voucher.objects.filter(Q(number=base) | Q(number__startswith=f"{base}-R"))
        revision = (family.aggregate(top=Max("revision"))["top"] or 0) + 1
        # The original stops counting first, so its invoices can move to the amendment.
        voucher.status = Voucher.Status.AMENDED
        voucher.save(update_fields=["status", "updated_at"])
        amendment = Voucher.objects.create(
            number=f"{base}-R{revision}",
            voucher_type=voucher.voucher_type,
            division=voucher.division,
            payee=voucher.payee,
            transfer_to=voucher.transfer_to,
            voucher_date=timezone.localdate(),
            description=voucher.description,
            total_amount=voucher.total_amount,
            wht_total=voucher.wht_total,
            revision=revision,
            parent=voucher,
            created_by=user,
            amendment_reason=reason,
        )
        for line in voucher.lines.prefetch_related("splits"):
            splits = list(line.splits.all())
            line.pk = None
            line.voucher = amendment
            line.save()
            for part in splits:
                part.pk = None
                part.line = line
                part.save()
        for attachment in voucher.attachments.all():
            attachment.pk = None  # the same stored file, now also on the amendment
            attachment.voucher = amendment
            attachment.save()
        return amendment


def amendments(user: User) -> QuerySet[Voucher]:
    """The Amendments List: every revision this user may see, deleted ones included."""
    return visible(user, deleted=None).filter(revision__gt=0)


# --- Cancellation (P1-06) ---------------------------------------------------------------

CANCEL_DOC = "voucher_cancellation"
PAID = (Voucher.Status.PARTLY_PAID, Voucher.Status.PAID)


def pending_cancellation(voucher: Voucher) -> VoucherCancellation | None:
    return voucher.cancellations.filter(status=VoucherCancellation.Status.PENDING).first()


def why_not_cancel(user: User, voucher: Voucher) -> str | None:
    """Why this user cannot request the voucher's cancellation, or None if they can."""
    if not approvals.holds_role(user, "accountant"):
        return "Only the Accountant requests a cancellation."
    if voucher.status in PAID:
        return f"Voucher {voucher.number} has payments and cannot be cancelled."
    if voucher.status != Voucher.Status.DIRECTOR_APPROVED:
        return (
            "Only a Director-approved voucher with no payment can be cancelled; a voucher still "
            "being approved is rejected instead."
        )
    if pending_cancellation(voucher):
        return "A cancellation of this voucher is already waiting for the Director."
    return None


def request_cancellation(user: User, voucher: Voucher, reason: str) -> VoucherCancellation:
    """The Accountant asks to cancel an approved, unpaid voucher; the Director decides."""
    reason = (reason or "").strip()[:500]
    if not reason:
        raise VoucherError("Say why the voucher should be cancelled.")
    with audit_context("voucher_cancellation_requested", reason), transaction.atomic():
        voucher = Voucher.objects.select_for_update().get(pk=voucher.pk)
        refusal = why_not_cancel(user, voucher)
        if refusal:
            raise VoucherError(refusal)
        request = VoucherCancellation.objects.create(
            voucher=voucher, reason=reason, requested_by=user
        )
        who = voucher.payee.name if voucher.payee else voucher.voucher_type.name
        try:
            approvals.submit(
                user,
                CANCEL_DOC,
                request.pk,
                created_by=user,
                amount=voucher.total_amount,
                division=voucher.division,
                subtype=voucher.voucher_type.code,
                comment=reason,
                title=f"Cancellation of voucher {voucher.number} – {who} – "
                f"LKR {voucher.total_amount:,.2f}",
                link=f"/vouchers/{voucher.pk}",
            )
        except ApprovalError as error:
            raise VoucherError(str(error)) from None
        return request


def can_decide(user: User, request: VoucherCancellation) -> bool:
    state = approvals.state_of(CANCEL_DOC, request.pk)
    return (
        request.status == VoucherCancellation.Status.PENDING
        and state is not None
        and state.status == ApprovalState.Status.IN_PROGRESS
        and approvals.why_not(user, state) is None
    )


def decide_cancellation(
    user: User, request: VoucherCancellation, approve: bool, reason: str = ""
) -> VoucherCancellation:
    """The Director approves (the voucher becomes Cancelled, for good) or rejects (reason
    required; the voucher stays approved). A voucher with any payment is never cancelled."""
    event = "voucher_cancelled" if approve else "voucher_cancellation_rejected"
    with audit_context(event, reason), transaction.atomic():
        request = VoucherCancellation.objects.select_for_update().get(pk=request.pk)
        voucher = Voucher.objects.select_for_update().get(pk=request.voucher_id)
        if request.status != VoucherCancellation.Status.PENDING:
            raise VoucherError("This cancellation request has already been decided.")
        try:
            if approve:
                if voucher.status in PAID:
                    raise VoucherError(
                        f"Voucher {voucher.number} has payments and cannot be cancelled."
                    )
                state = approvals.approve(user, CANCEL_DOC, request.pk, reason)
                if state.status != ApprovalState.Status.APPROVED:
                    return request  # a further level in the matrix still has to approve
            else:
                approvals.reject(user, CANCEL_DOC, request.pk, reason)
        except ApprovalError as error:
            raise VoucherError(str(error)) from None
        request.status = (
            VoucherCancellation.Status.APPROVED if approve else VoucherCancellation.Status.REJECTED
        )
        request.decided_by = user
        request.decided_at = timezone.now()
        request.decision_reason = (reason or "").strip()[:500]
        request.save()
        if approve:
            voucher.status = Voucher.Status.CANCELLED
            voucher.save(update_fields=["status", "updated_at"])
        return request


def cancellations(user: User) -> QuerySet[VoucherCancellation]:
    """Cancellation requests on the vouchers this user may see."""
    return VoucherCancellation.objects.filter(
        voucher__in=visible(user, deleted=None)
    ).select_related("voucher", "voucher__payee", "requested_by", "decided_by")
