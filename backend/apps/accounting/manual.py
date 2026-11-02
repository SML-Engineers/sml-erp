"""Manual journals (backlog P2-01, spec 6 and 4.6).

- The Accountant (Accounting: Enter) types a journal: date, narration and lines (account,
  division, supplier for a payables line, description, debit or credit), with supporting
  files. It is numbered at once (MJ{YY}{MM}{DD}{XX}) and stays a draft until sent.
- Sent for approval, it goes through the approval engine ("manual_journal": the Director).
  Nobody approves a journal they made. Approved, it is posted as an ordinary journal entry
  (the journal's rules apply: balanced, open month, divisions on income and expense lines);
  returned, it is a draft again; rejected, it stays rejected.
- Suppliers are paid only through vouchers: a journal that debits accounts payable and
  credits a bank or cash account is refused (also by the database for every entry that is
  not a supplier payment). Customer balances change only through sales documents, so
  accounts receivable is not used here.
- Once sent, a journal never changes (database guard). A posted journal is corrected by
  reversing its entry.
"""

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, Division, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters.models import Supplier

from . import journal
from .catalogue import PROFIT_AND_LOSS, section_of
from .models import Account, ManualJournal, ManualJournalAttachment, ManualJournalLine
from .services import AccountingError

DOC = "manual_journal"
St = ManualJournal.Status
MAX_LINES = 200
MAX_FILES = 20
MAX_FILE_BYTES = 20 * 1024 * 1024
FILE_TYPES = {
    b"%PDF-": ("application/pdf", ".pdf"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", ".png"),
}
LOCK_MESSAGE = (
    "Suppliers are paid only through an approved voucher: a journal cannot debit accounts "
    "payable and credit a bank or cash account."
)


@dataclass
class LineInput:
    account: Account | None
    debit: object = "0"
    credit: object = "0"
    division: Division | None = None
    supplier: Supplier | None = None
    description: str = ""


# --- Who may do what -----------------------------------------------------------------------


def can_view(user: User) -> bool:
    return effective_access(user).has("accounting", "view")


def can_enter(user: User) -> bool:
    return effective_access(user).has("accounting", "enter")


def visible(user: User) -> QuerySet[ManualJournal]:
    if not can_view(user):
        return ManualJournal.objects.none()
    return ManualJournal.objects.all()


def can_edit(user: User, mj: ManualJournal) -> bool:
    return mj.status == St.DRAFT and mj.created_by_id == user.pk and can_enter(user)


def can_approve(user: User, mj: ManualJournal) -> bool:
    if mj.status != St.AWAITING_APPROVAL:
        return False
    state = approvals.state_of(DOC, mj.pk)
    return state is not None and approvals.why_not(user, state) is None


# --- Checking --------------------------------------------------------------------------------


def _header(mj: ManualJournal, values: dict) -> None:
    if "entry_date" in values:
        when = values["entry_date"]
        if not isinstance(when, date):
            raise AccountingError("The journal date is not a date.")
        if journal.is_closed(when):
            raise AccountingError(f"The period {when:%Y-%m} is closed: choose an open month.")
        mj.entry_date = when
    if "narration" in values:
        mj.narration = " ".join((values["narration"] or "").split())[:500]
    if not mj.narration:
        raise AccountingError("The narration is required: say what the journal is for.")


def _line(n: int, given: LineInput, user: User) -> ManualJournalLine:
    where = f"Line {n}"
    account = given.account
    if not isinstance(account, Account):
        raise AccountingError(f"{where}: choose the account.")
    if not account.is_active or account.merged_into_id:
        raise AccountingError(f"{where}: {account.name} is inactive or merged; choose another.")
    if account.account_type == "accounts_receivable":
        raise AccountingError(
            f"{where}: customer balances change only through invoices, receipts and credit "
            "notes, not a manual journal."
        )
    debit = journal._amount(given.debit, where)
    credit = journal._amount(given.credit, where)
    if (debit > 0) == (credit > 0):
        raise AccountingError(f"{where}: enter either a debit or a credit, more than zero.")
    division = given.division
    if division is not None and not division_scope(user).filter(pk=division.pk).exists():
        raise AccountingError(f"{where}: you do not work in division {division.code}.")
    if section_of(account.account_type) == PROFIT_AND_LOSS and division is None:
        raise AccountingError(
            f"{where}: {account.name} is an income or expense account: choose the division."
        )
    supplier = given.supplier
    if account.account_type == "accounts_payable":
        if supplier is None:
            raise AccountingError(f"{where}: a payables line needs the supplier.")
    elif supplier is not None:
        raise AccountingError(f"{where}: a supplier goes only on an accounts payable line.")
    return ManualJournalLine(
        line_no=n,
        account=account,
        division=division,
        supplier=supplier,
        description=(given.description or "").strip()[:500],
        debit=debit,
        credit=credit,
    )


def _locked(lines) -> bool:
    """True when the lines would pay a supplier from a bank or cash account (spec 4.6)."""
    pays = any(x.debit > 0 and x.account.account_type == "accounts_payable" for x in lines)
    from_bank = any(x.credit > 0 and x.account.account_type == "bank" for x in lines)
    return pays and from_bank


def _fill(mj: ManualJournal, given: list[LineInput], user: User) -> None:
    if not given:
        raise AccountingError("Add the journal's lines.")
    if len(given) > MAX_LINES:
        raise AccountingError(f"A journal can have at most {MAX_LINES} lines.")
    rows = [_line(n, g, user) for n, g in enumerate(given, start=1)]
    if _locked(rows):
        raise AccountingError(LOCK_MESSAGE)
    mj.lines.all().delete()
    for row in rows:
        row.journal = mj
        row.save()


def totals(mj: ManualJournal) -> tuple[Decimal, Decimal]:
    lines = list(mj.lines.all())
    return (
        sum((x.debit for x in lines), Decimal("0")),
        sum((x.credit for x in lines), Decimal("0")),
    )


def _ledger_lines(mj: ManualJournal) -> list[journal.Line]:
    return [
        journal.Line(
            account=x.account,
            debit=x.debit,
            credit=x.credit,
            division=x.division,
            supplier=x.supplier,
            description=x.description,
        )
        for x in mj.lines.select_related("account", "account__merged_into", "division", "supplier")
    ]


# --- Making and changing -----------------------------------------------------------------------


def create(user: User, *, lines: list[LineInput], **values) -> ManualJournal:
    if not can_enter(user):
        raise AccountingError("Only the Accountant enters journals.")
    with audit_context("manual_journal_created"), transaction.atomic():
        today = timezone.localdate()
        mj = ManualJournal(entry_date=today, created_by=user)
        _header(mj, values)
        try:
            mj.number = allocate(DOC, on_date=today)
        except NumberSeriesError as error:
            raise AccountingError(str(error)) from None
        mj.save()
        _fill(mj, lines, user)
        return mj


def save(user: User, mj: ManualJournal, *, lines: list[LineInput], **values) -> ManualJournal:
    with audit_context("manual_journal_changed"), transaction.atomic():
        mj = ManualJournal.objects.select_for_update().get(pk=mj.pk)
        if not can_edit(user, mj):
            raise AccountingError("Only the person who made a draft journal changes it.")
        _header(mj, values)
        mj.updated_at = timezone.now()
        mj.save()
        _fill(mj, lines, user)
        return mj


def delete(user: User, mj: ManualJournal) -> None:
    with audit_context("manual_journal_deleted"), transaction.atomic():
        mj = ManualJournal.objects.select_for_update().get(pk=mj.pk)
        if not can_edit(user, mj):
            raise AccountingError("Only the person who made a draft journal deletes it.")
        try:
            approvals.withdraw(user, DOC, mj.pk, "The draft journal was deleted.")
        except ApprovalError as error:
            raise AccountingError(str(error)) from None
        for attachment in mj.attachments.all():
            attachment.file.delete(save=False)
            attachment.delete()
        mj.delete()


# --- Approval --------------------------------------------------------------------------------


def submit(user: User, mj: ManualJournal, comment: str = "") -> ManualJournal:
    with audit_context("manual_journal_submitted", comment), transaction.atomic():
        mj = ManualJournal.objects.select_for_update().get(pk=mj.pk)
        if not can_edit(user, mj):
            raise AccountingError("Only the person who made a draft journal sends it.")
        if journal.is_closed(mj.entry_date):
            raise AccountingError(
                f"The period {mj.entry_date:%Y-%m} is closed: change the date to an open month."
            )
        lines = _ledger_lines(mj)
        journal._check_lines(lines)  # balanced, active accounts, divisions: as when posting
        debits, _ = totals(mj)
        try:
            approvals.submit(
                user,
                DOC,
                mj.pk,
                created_by=mj.created_by,
                amount=debits,
                comment=comment,
                title=f"Journal {mj.number}: {mj.narration}"[:200],
                link=f"/journals/manual/{mj.pk}",
            )
        except ApprovalError as error:
            raise AccountingError(str(error)) from None
        mj.status = St.AWAITING_APPROVAL
        mj.updated_at = timezone.now()
        mj.save(update_fields=["status", "updated_at"])
        return mj


def approve(user: User, mj: ManualJournal, comment: str = "") -> ManualJournal:
    with transaction.atomic():
        mj = ManualJournal.objects.select_for_update().get(pk=mj.pk)
        if mj.status != St.AWAITING_APPROVAL:
            raise AccountingError("The journal is not waiting for approval.")
        try:
            state = approvals.approve(user, DOC, mj.pk, comment)
        except ApprovalError as error:
            raise AccountingError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("manual_journal_posted", comment):
                entry = journal.post(
                    user,
                    entry_date=mj.entry_date,
                    narration=f"{mj.number}: {mj.narration}",
                    lines=_ledger_lines(mj),
                    source_type=DOC,
                    source_id=mj.number,
                )
                mj.status = St.POSTED
                mj.journal_entry = entry
                mj.updated_at = timezone.now()
                mj.save(update_fields=["status", "journal_entry", "updated_at"])
        return mj


def send_back(user: User, mj: ManualJournal, reason: str) -> ManualJournal:
    """Returned to the Accountant to correct and send again."""
    with transaction.atomic():
        mj = ManualJournal.objects.select_for_update().get(pk=mj.pk)
        if mj.status != St.AWAITING_APPROVAL:
            raise AccountingError("The journal is not waiting for approval.")
        try:
            approvals.send_back(user, DOC, mj.pk, reason)
        except ApprovalError as error:
            raise AccountingError(str(error)) from None
        with audit_context("manual_journal_returned", reason):
            mj.status = St.DRAFT
            mj.updated_at = timezone.now()
            mj.save(update_fields=["status", "updated_at"])
        return mj


def reject(user: User, mj: ManualJournal, reason: str) -> ManualJournal:
    with transaction.atomic():
        mj = ManualJournal.objects.select_for_update().get(pk=mj.pk)
        if mj.status != St.AWAITING_APPROVAL:
            raise AccountingError("The journal is not waiting for approval.")
        try:
            approvals.reject(user, DOC, mj.pk, reason)
        except ApprovalError as error:
            raise AccountingError(str(error)) from None
        with audit_context("manual_journal_rejected", reason):
            mj.status = St.REJECTED
            mj.updated_at = timezone.now()
            mj.save(update_fields=["status", "updated_at"])
        return mj


# --- Supporting files ---------------------------------------------------------------------------


def add_attachment(user: User, mj: ManualJournal, uploaded) -> ManualJournalAttachment:
    with audit_context("manual_journal_attachment_added"), transaction.atomic():
        mj = ManualJournal.objects.select_for_update().get(pk=mj.pk)
        if not can_edit(user, mj):
            raise AccountingError("Files are added while the journal is a draft.")
        if mj.attachments.count() >= MAX_FILES:
            raise AccountingError(f"A journal can have at most {MAX_FILES} files.")
        if uploaded.size > MAX_FILE_BYTES:
            raise AccountingError("The file is larger than 20 MB.")
        content = uploaded.read()
        kind = next((k for magic, k in FILE_TYPES.items() if content.startswith(magic)), None)
        if kind is None:
            raise AccountingError("Only JPG, PNG and PDF files can be added.")
        content_type, extension = kind
        digest = hashlib.sha256(content).hexdigest()
        name = (uploaded.name or f"document{extension}").replace("/", "_").replace("\\", "_")
        uploaded.seek(0)
        attachment = ManualJournalAttachment(
            journal=mj,
            file_name=name[-200:],
            content_type=content_type,
            size=len(content),
            sha256=digest,
            uploaded_by=user,
        )
        attachment.file.save(f"{mj.number}-{digest[:12]}{extension}", uploaded, save=False)
        attachment.save()
        return attachment


def remove_attachment(user: User, attachment: ManualJournalAttachment) -> None:
    with audit_context("manual_journal_attachment_removed"), transaction.atomic():
        mj = ManualJournal.objects.select_for_update().get(pk=attachment.journal_id)
        if not can_edit(user, mj):
            raise AccountingError("A file is removed only from a draft.")
        attachment.file.delete(save=False)
        attachment.delete()
