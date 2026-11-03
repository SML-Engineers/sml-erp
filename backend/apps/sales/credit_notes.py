"""Credit notes (backlog P2-06).

- Made against an issued tax invoice by Sales or the Accountant, with the kind (goods returned,
  price correction, other) and the reason, both required. Each line credits part or all of an
  invoice line: the amount before tax (and, for returned goods, the quantity), never more than
  is left of the line after the approved credit notes (also a database rule, checked again at
  approval). The taxes are worked out on the credited amounts at the invoice's rates, so the
  credit reverses exactly what was charged.
- Sent for approval through the approval engine ("credit_note"): the Director, or a person the
  Admin gives the "Approve credit notes" right to and the Director confirms (owner, 3 Nov
  2026). Nobody approves a note they made (rule 5).
- Approval numbers it (CN{YY}{MM}{DD}{XX}, in the same transaction) and posts the reverse of
  the invoice: Dr each sales account, Dr SSCL and VAT payable, Cr Accounts receivable (the
  customer). Returned: back to draft; rejected: stays rejected. Approved or rejected notes
  never change (database guard).
- Returned goods do not go back into a stock until finished-goods stock exists (Phase 3,
  question 4).
"""

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import QuerySet, Sum
from django.utils import timezone

from apps.accounting import journal, taxes
from apps.accounting.models import Account, TaxCodeLine
from apps.accounting.services import AccountingError
from apps.core import approvals
from apps.core.access import division_scope
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User
from apps.core.numbering import NumberSeriesError, allocate

from . import invoices, words
from .models import CreditNote, CreditNoteLine, CreditNoteTax, TaxInvoice, TaxInvoiceLine
from .services import SalesError, _decimal

DOC = "credit_note"
CENT = Decimal("0.01")
QTY = Decimal("0.001")
St = CreditNote.Status


@dataclass
class LineInput:
    invoice_line: TaxInvoiceLine
    amount: object
    quantity: object = "0"


# --- Who may do what ---------------------------------------------------------------------


def visible(user: User) -> QuerySet[CreditNote]:
    """Those of the invoices the user may see."""
    if not invoices.can_view(user):
        return CreditNote.objects.none()
    return CreditNote.objects.filter(
        division__in=division_scope(user), invoice__in=invoices.visible(user)
    )


def can_edit(user: User, note: CreditNote) -> bool:
    return note.status == St.DRAFT and note.created_by_id == user.pk and invoices.can_prepare(user)


def can_approve(user: User, note: CreditNote) -> bool:
    state = approvals.state_of(DOC, note.pk)
    return (
        note.status == St.AWAITING_APPROVAL
        and state is not None
        and approvals.why_not(user, state) is None
    )


# --- What is left to credit -----------------------------------------------------------------


def credited(invoice: TaxInvoice, *, besides: CreditNote | None = None) -> dict[int, dict]:
    """Per invoice line: the amount and quantity already credited by approved notes."""
    rows = CreditNoteLine.objects.filter(note__invoice=invoice, note__status=St.APPROVED)
    if besides is not None:
        rows = rows.exclude(note=besides)
    return {
        r["invoice_line"]: {"amount": r["amount"], "quantity": r["quantity"]}
        for r in rows.values("invoice_line").annotate(
            amount=Sum("amount"), quantity=Sum("quantity")
        )
    }


def left(invoice: TaxInvoice, *, besides: CreditNote | None = None) -> dict[int, dict]:
    done = credited(invoice, besides=besides)
    zero = {"amount": Decimal("0"), "quantity": Decimal("0")}
    return {
        line.pk: {
            "amount": line.net - done.get(line.pk, zero)["amount"],
            "quantity": line.quantity - done.get(line.pk, zero)["quantity"],
        }
        for line in invoice.lines.all()
    }


def _compute(note: CreditNote) -> None:
    """Taxes on each credited amount at the invoice's rates, grouped as printed."""
    groups: OrderedDict = OrderedDict()
    subtotal = Decimal("0")
    on_date = note.invoice.invoice_date
    try:
        for line in note.lines.select_related("invoice_line__tax_code"):
            code = line.invoice_line.tax_code
            tax = Decimal("0")
            if code is not None:
                bases = dict(
                    TaxCodeLine.objects.filter(tax_code=code).values_list("component_id", "base")
                )
                for part in taxes.calculate(code, line.amount, on_date).lines:
                    on_tax = bases.get(part.component.pk) == TaxCodeLine.Base.NET_AND_TAX
                    key = (part.component.pk, part.rate, on_tax)
                    if key not in groups:
                        groups[key] = [part.component, Decimal("0")]
                    groups[key][1] += part.amount
                    tax += part.amount
            if line.tax_amount != tax:
                line.tax_amount = tax
                line.save(update_fields=["tax_amount"])
            subtotal += line.amount
    except AccountingError as error:
        raise SalesError(str(error)) from None
    note.taxes.all().delete()
    ordered = sorted(groups.items(), key=lambda item: item[0][2])
    for seq, ((_, rate, on_tax), (component, amount)) in enumerate(ordered, start=1):
        CreditNoteTax.objects.create(
            note=note,
            seq=seq,
            component=component,
            label=component.label,
            rate=rate,
            on_tax=on_tax,
            amount=amount,
        )
    note.subtotal = subtotal
    note.tax_total = sum((amount for _, amount in groups.values()), Decimal("0"))
    note.total_amount = subtotal + note.tax_total
    note.amount_in_words = words.amount(note.total_amount)


# --- Making and changing -----------------------------------------------------------------------


def _header(note: CreditNote, values: dict) -> None:
    if "kind" in values:
        if values["kind"] not in CreditNote.Kind.values:
            raise SalesError("Choose why: goods returned, a price correction or other.")
        note.kind = values["kind"]
    if "reason" in values:
        note.reason = " ".join(str(values["reason"] or "").split())[:1000]
    if not note.reason:
        raise SalesError("Give the reason for the credit note.")
    if "credit_date" in values:
        when = values["credit_date"]
        if not isinstance(when, date):
            raise SalesError("The credit note date is not a date.")
        if when > timezone.localdate():
            raise SalesError("The credit note date cannot be in the future.")
        if when < note.invoice.invoice_date:
            raise SalesError("A credit note cannot be dated before its invoice.")
        note.credit_date = when


def _fill(note: CreditNote, given: list[LineInput]) -> None:
    rows = [g for g in given if str(g.amount).strip() not in ("", "0", "0.00")]
    if not rows:
        raise SalesError("Enter the amount credited on at least one line.")
    remaining = left(note.invoice, besides=note)
    seen = set()
    made = []
    for g in rows:
        line = g.invoice_line
        where = f"Line {line.line_no}"
        if line.invoice_id != note.invoice_id:
            raise SalesError("A line is not on this invoice.")
        if line.pk in seen:
            raise SalesError(f"{where} appears twice.")
        seen.add(line.pk)
        try:
            amount = _decimal(g.amount, "amount", CENT, positive=True)
            quantity = _decimal(g.quantity or "0", "quantity", QTY, positive=False)
        except SalesError as error:
            raise SalesError(f"{where}: {error}") from None
        if amount > remaining[line.pk]["amount"]:
            raise SalesError(
                f"{where}: at most {remaining[line.pk]['amount']:,.2f} is left to credit."
            )
        if quantity > remaining[line.pk]["quantity"]:
            raise SalesError(
                f"{where}: at most {remaining[line.pk]['quantity'].normalize():f} {line.unit} "
                "is left to credit."
            )
        if note.kind == CreditNote.Kind.RETURN and quantity <= 0:
            raise SalesError(f"{where}: enter the quantity returned.")
        made.append(CreditNoteLine(note=note, invoice_line=line, quantity=quantity, amount=amount))
    note.lines.all().delete()
    CreditNoteLine.objects.bulk_create(made)


def create(user: User, invoice: TaxInvoice, *, lines: list[LineInput], **values) -> CreditNote:
    if not invoices.can_prepare(user):
        raise SalesError("Only Sales or the Accountant make credit notes.")
    with audit_context("credit_note_created"), transaction.atomic():
        invoice = TaxInvoice.objects.select_for_update().get(pk=invoice.pk)
        if not invoices.visible(user).filter(pk=invoice.pk).exists():
            raise SalesError("Credit notes are made against invoices you may see.")
        if invoice.status != TaxInvoice.Status.ISSUED:
            raise SalesError("A credit note is made against an issued invoice.")
        note = CreditNote(
            invoice=invoice,
            customer=invoice.customer,
            division=invoice.division,
            kind=CreditNote.Kind.OTHER,
            credit_date=timezone.localdate(),
            created_by=user,
        )
        _header(note, values)
        note.save()
        _fill(note, lines)
        _compute(note)
        note.save()
        return note


def save(user: User, note: CreditNote, *, lines: list[LineInput], **values) -> CreditNote:
    with audit_context("credit_note_changed"), transaction.atomic():
        note = CreditNote.objects.select_for_update().get(pk=note.pk)
        if not can_edit(user, note):
            raise SalesError("Only the person who made a draft credit note changes it.")
        _header(note, values)
        note.updated_at = timezone.now()
        note.save()
        _fill(note, lines)
        _compute(note)
        note.save()
        return note


def delete(user: User, note: CreditNote) -> None:
    with audit_context("credit_note_deleted"), transaction.atomic():
        note = CreditNote.objects.select_for_update().get(pk=note.pk)
        if not can_edit(user, note):
            raise SalesError("Only the person who made a draft credit note deletes it.")
        note.delete()


# --- Approval -------------------------------------------------------------------------------


def _label(note: CreditNote) -> str:
    return f"Credit note {note.number or note.pk} on {note.invoice.number}"


def submit(user: User, note: CreditNote, comment: str = "") -> CreditNote:
    with audit_context("credit_note_submitted", comment), transaction.atomic():
        note = CreditNote.objects.select_for_update().get(pk=note.pk)
        if not can_edit(user, note):
            raise SalesError("Only the person who made a draft credit note sends it.")
        if journal.is_closed(note.credit_date):
            raise SalesError(
                f"The period {note.credit_date:%Y-%m} is closed: change the date to an open month."
            )
        _compute(note)  # the figures as they will be approved
        note.save()
        try:
            approvals.submit(
                user,
                DOC,
                note.pk,
                created_by=note.created_by,
                amount=note.total_amount,
                division=note.division,
                comment=comment,
                title=f"Credit note on {note.invoice.number} for {note.customer.name}",
                link=f"/credit-notes/{note.pk}",
            )
        except ApprovalError as error:
            raise SalesError(str(error)) from None
        note.status = St.AWAITING_APPROVAL
        note.updated_at = timezone.now()
        note.save(update_fields=["status", "updated_at"])
        return note


def _journal_lines(note: CreditNote) -> list[journal.Line]:
    receivable = Account.objects.filter(system_role="accounts_receivable").first()
    if receivable is None:
        raise SalesError("The chart of accounts has no accounts receivable account.")
    division = note.division
    text = f"Credit note {note.number} on {note.invoice.number}"
    lines = []
    income: OrderedDict = OrderedDict()
    for line in note.lines.select_related("invoice_line__account"):
        account = line.invoice_line.account
        income[account] = income.get(account, Decimal("0")) + line.amount
    for account, amount in income.items():
        lines.append(
            journal.Line(account=account, debit=amount, division=division, description=text)
        )
    for tax in note.taxes.select_related("component__sales_account"):
        if not tax.amount:
            continue
        account = tax.component.sales_account
        if account is None:
            raise SalesError(f"Tax {tax.component.code} has no sales account.")
        lines.append(
            journal.Line(
                account=account,
                debit=tax.amount,
                division=division,
                description=f"{text}: {tax.label} {tax.rate.normalize():f}%",
            )
        )
    lines.append(
        journal.Line(
            account=receivable,
            credit=note.total_amount,
            division=division,
            customer=note.customer,
            description=text,
        )
    )
    return lines


def approve(user: User, note: CreditNote, comment: str = "") -> CreditNote:
    with transaction.atomic():
        note = CreditNote.objects.select_for_update().get(pk=note.pk)
        if note.status != St.AWAITING_APPROVAL:
            raise SalesError("The credit note is not waiting for approval.")
        try:
            state = approvals.approve(user, DOC, note.pk, comment)
        except ApprovalError as error:
            raise SalesError(str(error)) from None
        if state.status != ApprovalState.Status.APPROVED:
            return note
        with audit_context("credit_note_approved", comment):
            remaining = left(note.invoice, besides=note)
            for line in note.lines.select_related("invoice_line"):
                room = remaining[line.invoice_line_id]
                if line.amount > room["amount"] or line.quantity > room["quantity"]:
                    raise SalesError(
                        f"Line {line.invoice_line.line_no}: another credit note has been approved "
                        "since; return this one to be corrected."
                    )
            try:
                note.number = allocate(DOC, division=note.division, on_date=note.credit_date)
            except NumberSeriesError as error:
                raise SalesError(str(error)) from None
            try:
                entry = journal.post(
                    user,
                    entry_date=note.credit_date,
                    narration=f"Credit note {note.number} on tax invoice {note.invoice.number} "
                    f"to {note.customer.name}: {note.reason}"[:500],
                    lines=_journal_lines(note),
                    source_type=DOC,
                    source_id=note.number,
                )
            except AccountingError as error:
                raise SalesError(str(error)) from None
            note.journal_entry = entry
            note.status = St.APPROVED
            note.updated_at = timezone.now()
            note.save(update_fields=["number", "journal_entry", "status", "updated_at"])
        return note


def send_back(user: User, note: CreditNote, reason: str) -> CreditNote:
    with transaction.atomic():
        note = CreditNote.objects.select_for_update().get(pk=note.pk)
        if note.status != St.AWAITING_APPROVAL:
            raise SalesError("The credit note is not waiting for approval.")
        try:
            approvals.send_back(user, DOC, note.pk, reason)
        except ApprovalError as error:
            raise SalesError(str(error)) from None
        with audit_context("credit_note_returned", reason):
            note.status = St.DRAFT
            note.updated_at = timezone.now()
            note.save(update_fields=["status", "updated_at"])
        return note


def reject(user: User, note: CreditNote, reason: str) -> CreditNote:
    with transaction.atomic():
        note = CreditNote.objects.select_for_update().get(pk=note.pk)
        if note.status != St.AWAITING_APPROVAL:
            raise SalesError("The credit note is not waiting for approval.")
        try:
            approvals.reject(user, DOC, note.pk, reason)
        except ApprovalError as error:
            raise SalesError(str(error)) from None
        with audit_context("credit_note_rejected", reason):
            note.status = St.REJECTED
            note.updated_at = timezone.now()
            note.save(update_fields=["status", "updated_at"])
        return note
