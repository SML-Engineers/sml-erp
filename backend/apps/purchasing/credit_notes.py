"""The supplier's credit note matched to our debit note (owner, 22 Nov 2026).

When invoiced goods go back, our own debit note (DN…) is raised as they leave (P16-12) and
reduces what we owe at once. The supplier then sends their credit note. It is recorded here
against our debit note, with its number, date and scan, so that:
- we can see which debit notes the supplier has not yet confirmed with a credit note;
- the supplier's statement check finds their credit note number.

Nothing is posted: our debit note already did that. One supplier credit note may cover several
of our debit notes. A recorded match is never changed (database guard); the Accountant can
remove a mistake with a reason (kept in the audit log) and it is recorded again.
"""

import hashlib
from datetime import date

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.vouchers.services import FILE_TYPES, MAX_FILE_BYTES

from . import invoices
from .models import DebitNote, SupplierCreditNote


class CreditNoteError(Exception):
    pass


def can_record(user: User) -> bool:
    """The Accounts Clerk (who enters supplier invoices) and the Accountant."""
    return invoices.can_enter(user) or effective_access(user).has("accounting", "enter")


def can_remove(user: User) -> bool:
    return effective_access(user).has("accounting", "manage")


def visible(user: User) -> QuerySet[DebitNote]:
    if not (invoices.can_view(user) or effective_access(user).has("purchasing", "view")):
        return DebitNote.objects.none()
    return DebitNote.objects.filter(invoice__division__in=division_scope(user)).select_related(
        "invoice", "invoice__supplier", "invoice__currency", "supplier_return"
    )


def _day(value, what: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        raise CreditNoteError(f"Give the {what}, for example 2026-12-05.") from None


def record(user: User, debit_note: DebitNote, *, number, credit_date, uploaded):
    """Record the supplier's credit note against our debit note, with its scan."""
    if not can_record(user):
        raise CreditNoteError("Only the Accounts Clerk or the Accountant records credit notes.")
    number = " ".join(str(number or "").split())
    if not number:
        raise CreditNoteError("Give the supplier's credit note number.")
    if len(number) > 50:
        raise CreditNoteError("The credit note number can have at most 50 characters.")
    when = _day(credit_date, "date of the supplier's credit note")
    if when > timezone.localdate():
        raise CreditNoteError("The supplier's credit note cannot be dated in the future.")
    if when < debit_note.invoice.invoice_date:
        raise CreditNoteError(
            f"The credit note is dated before the invoice {debit_note.invoice.invoice_no} "
            f"({debit_note.invoice.invoice_date:%d/%m/%Y}) it credits."
        )
    if uploaded is None:
        raise CreditNoteError("Attach the scan of the supplier's credit note.")
    if uploaded.size > MAX_FILE_BYTES:
        raise CreditNoteError("The file is larger than 20 MB.")
    content = uploaded.read()
    kind = next((k for magic, k in FILE_TYPES.items() if content.startswith(magic)), None)
    if kind is None:
        raise CreditNoteError("Only JPG, PNG and PDF files can be added.")
    content_type, extension = kind
    digest = hashlib.sha256(content).hexdigest()
    name = (uploaded.name or f"credit-note{extension}").replace("/", "_").replace("\\", "_")
    uploaded.seek(0)
    with audit_context("supplier_credit_note_recorded"), transaction.atomic():
        found = DebitNote.objects.select_for_update().get(pk=debit_note.pk)
        existing = SupplierCreditNote.objects.filter(debit_note=found).first()
        if existing is not None:
            raise CreditNoteError(
                f"Debit note {found.number} already has the supplier's credit note "
                f"{existing.credit_note_no}."
            )
        credit = SupplierCreditNote(
            debit_note=found,
            credit_note_no=number,
            credit_note_date=when,
            file_name=name[-200:],
            content_type=content_type,
            size=len(content),
            sha256=digest,
            recorded_by=user,
        )
        credit.file.save(f"{found.number}-{digest[:12]}{extension}", uploaded, save=False)
        credit.save()
    return credit


def remove(user: User, credit: SupplierCreditNote, reason: str) -> None:
    """The Accountant removes a credit note recorded by mistake, with a reason."""
    if not can_remove(user):
        raise CreditNoteError("Only the Accountant removes a recorded credit note.")
    reason = " ".join(str(reason or "").split())
    if not reason:
        raise CreditNoteError("Give the reason for removing the credit note.")
    with audit_context("supplier_credit_note_removed", reason=reason), transaction.atomic():
        credit.file.delete(save=False)
        credit.delete()


def rows(user: User, *, division: str = "", waiting_only: bool = False) -> list[dict]:
    """Our debit notes with the supplier's credit note, or the days we have waited for it."""
    today = timezone.localdate()
    found = visible(user).select_related("supplier_credit")
    if division:
        found = found.filter(invoice__division__code=division.upper())
    out = []
    for note in found.order_by("created_at", "id"):
        credit = getattr(note, "supplier_credit", None)
        if waiting_only and credit is not None:
            continue
        raised = timezone.localtime(note.created_at).date()
        out.append(
            {
                "id": note.id,
                "number": note.number,
                "date": raised,
                "division": note.invoice.division.code,
                "supplier": note.invoice.supplier.name,
                "invoice_id": note.invoice_id,
                "invoice": note.invoice.invoice_no,
                "return_id": note.supplier_return_id,
                "return": note.supplier_return.number,
                "total_lkr": f"{note.total_lkr:.2f}",
                "credit_note": credit.credit_note_no if credit else "",
                "credit_note_date": credit.credit_note_date if credit else None,
                "days_waiting": None if credit else (today - raised).days,
            }
        )
    return out
