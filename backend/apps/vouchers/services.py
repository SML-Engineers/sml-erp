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
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import TaxCode
from apps.core import approvals
from apps.core.access import division_scope, effective_access, has_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, Division, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters.models import CompanyAccount, Supplier
from apps.masters.services import is_in_use, mark_used

from .models import TYPE_CODE_REGEX, Voucher, VoucherAttachment, VoucherLine, VoucherType

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


def visible(user: User) -> QuerySet[Voucher]:
    access = effective_access(user)
    rows = Voucher.objects.filter(division__in=division_scope(user)).exclude(
        status=Voucher.Status.DELETED
    )
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
        new_lines = _lines(voucher, list(lines))
        voucher.total_amount = sum((line.total for line in new_lines), Decimal("0"))
        voucher.save()
        coding = {line.line_no: (line.account_id, line.division_id) for line in voucher.lines.all()}
        voucher.lines.all().delete()
        for line in new_lines:
            if line.line_no in coding:
                line.account_id, line.division_id = coding[line.line_no]
            line.save()
        return voucher


def duplicate_invoices(voucher: Voucher) -> list[str]:
    """Warnings: the same payee and invoice number on another voucher (spec 4.4)."""
    if voucher.payee_id is None:
        return []
    warnings = []
    for line in voucher.lines.exclude(invoice_no=""):
        others = (
            VoucherLine.objects.filter(
                voucher__payee_id=voucher.payee_id, invoice_no__iexact=line.invoice_no
            )
            .exclude(voucher=voucher)
            .exclude(voucher__status__in=[Voucher.Status.DELETED, Voucher.Status.REJECTED])
            .select_related("voucher")
        )
        numbers = sorted({o.voucher.number for o in others})
        if numbers:
            warnings.append(
                f"Invoice {line.invoice_no} of this payee is already on voucher "
                f"{', '.join(numbers)}."
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
            .exclude(voucher__status=Voucher.Status.DELETED)
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
    if state is None:
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
        if vt.needs_payee and not voucher.attachments.exists():
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
