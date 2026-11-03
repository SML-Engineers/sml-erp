"""Bank reconciliation (backlog P2-16, spec 6).

Each imported statement line is matched to the journal entry that moved the same money through
the bank account in our books (a supplier payment, a deposit slip, a receipt or advance into
the bank, an internal transfer, a journal): same amount and direction, close in date. The
system suggests the match, preferring the entry whose cheque number, deposit number or
reference appears in the line's description; the Accountant accepts it with a click.

A line with nothing in the books behind it (bank charges, interest, a standing order) is
posted from the line in one click: to the account a rule gives (description contains...) or
that the same kind of line went to before, or one the Accountant chooses. Nothing is matched
or posted without the Accountant's click.

A month is finished when every statement line up to its end is in the books and the balance
per bank equals the book balance less the book items not yet on the statement (unpresented
cheques, deposits in transit). Finishing locks the month (database guard) and marks the
matched cheques cleared.
"""

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.accounting import journal
from apps.accounting.models import Account, JournalEntry, JournalLine
from apps.accounting.services import AccountingError
from apps.core.audit import audit_context
from apps.core.models import Division, User
from apps.masters.models import CompanyAccount

from .models import (
    BankReconciliation,
    BankRule,
    BankStatementLine,
    ChequeClearance,
    Deposit,
    StatementMatch,
)
from .services import BankingError
from .statements import can_import

ZERO = Decimal("0")
BEFORE = timedelta(days=90)  # a cheque may reach the bank long after it was written
AFTER = timedelta(days=10)
NOT_TO_POST = ("accounts_receivable", "accounts_payable", "bank")


def _accountant(user: User) -> None:
    if not can_import(user):
        raise BankingError("Only the Accountant reconciles the bank.")


def ledger(account: CompanyAccount) -> Account:
    if account.ledger_account_id is None:
        raise BankingError(f"The account {account.code} has no ledger account.")
    return account.ledger_account


def amount(line: BankStatementLine) -> Decimal:
    """The line's effect on our bank balance: money in is +, money out is −."""
    return line.money_in - line.money_out


def locked_to(account: CompanyAccount) -> date | None:
    last = BankReconciliation.objects.filter(account=account).order_by("-period_end").first()
    return last.period_end if last else None


def history_start(account: CompanyAccount) -> date | None:
    first = BankStatementLine.objects.filter(account=account).order_by("date").first()
    return first.date if first else None


# --- Book items --------------------------------------------------------------------------


@dataclass
class Item:
    entry: JournalEntry
    amount: Decimal  # effect on the bank: debit +, credit −

    def as_dict(self) -> dict:
        e = self.entry
        return {
            "entry": {"id": e.pk, "number": e.number},
            "date": e.entry_date,
            "narration": e.narration,
            "source_type": e.source_type,
            "source_id": e.source_id,
            "amount": f"{self.amount:.2f}",
        }


def book_items(account: CompanyAccount, upto: date | None = None, start: date | None = None):
    """Entries that moved money through the bank account and are not matched to a statement
    line: their net effect on it. An entry and its reversal, both unmatched, cancel out."""
    bank = ledger(account)
    rows = JournalLine.objects.filter(account=bank, entry__statement_match__isnull=True)
    if upto is not None:
        rows = rows.filter(entry__entry_date__lte=upto)
    if start is not None:
        rows = rows.filter(entry__entry_date__gte=start)
    totals = {
        r["entry"]: r["net"]
        for r in rows.values("entry").annotate(net=Sum(F("debit") - F("credit")))
        if r["net"]
    }
    entries = JournalEntry.objects.in_bulk(list(totals))
    reversed_pairs = set()
    for e in entries.values():
        if e.reversal_of_id in entries:
            reversed_pairs |= {e.pk, e.reversal_of_id}
    return sorted(
        (Item(entries[pk], net) for pk, net in totals.items() if pk not in reversed_pairs),
        key=lambda i: (i.entry.entry_date, i.entry.pk),
    )


def _digits(text: str) -> set[str]:
    return {d.lstrip("0") for d in re.findall(r"\d{4,}", text or "") if d.lstrip("0")}


def _references(entry: JournalEntry) -> set[str]:
    """Numbers the bank may print for this entry: the cheque number, the transfer or deposit
    reference, the document number."""
    found = _digits(entry.source_id)
    payment = getattr(entry, "supplier_payment", None)
    if payment is not None:
        found |= _digits(payment.reference)
        if payment.cheque_id:
            found.add(str(payment.cheque.number))
    deposit = getattr(entry, "deposit", None)
    if deposit is not None:
        found |= _digits(deposit.slip_no) | _digits(deposit.number)
    receipt = getattr(entry, "customer_receipt", None)
    if receipt is not None:
        found |= _digits(receipt.reference)
    advance = getattr(entry, "customer_advance", None)
    if advance is not None:
        found |= _digits(advance.reference)
    return found


def candidates(line: BankStatementLine, items: list[Item] | None = None) -> list[dict]:
    """Book items with the line's amount and direction near its date, best first."""
    if items is None:
        items = book_items(line.account)
    want = amount(line)
    seen = _digits(line.description) | _digits(line.reference)
    found = []
    for item in items:
        if item.amount != want:
            continue
        gap = (line.date - item.entry.entry_date).days
        if not (-AFTER.days <= gap <= BEFORE.days):
            continue
        hit = bool(seen & _references(item.entry))
        found.append((0 if hit else 1, abs(gap), item, hit))
    found.sort(key=lambda x: (x[0], x[1], x[2].entry.pk))
    return [item.as_dict() | {"reference_found": hit} for _, _, item, hit in found]


def suggestion(line: BankStatementLine, items: list[Item]) -> dict | None:
    """A match to suggest: the only candidate, or the one whose reference is on the line."""
    found = candidates(line, items)
    if len(found) == 1 or (
        found
        and found[0]["reference_found"]
        and not (len(found) > 1 and found[1]["reference_found"])
    ):
        return found[0]
    return None


# --- Posting a line without a book entry ------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[\d/.\-]+", " ", (text or "").upper()).split())


def coding_for(line: BankStatementLine) -> dict | None:
    """The account to post an unmatched line to: from a rule, else from the last line with the
    same description (without its numbers) posted from the statement."""
    direction = "in" if line.money_in else "out"
    text = (line.description or "").upper()
    for rule in (
        BankRule.objects.filter(is_active=True)
        .filter(Q(account=line.account) | Q(account__isnull=True))
        .select_related("ledger", "division")
    ):
        if rule.direction in ("any", direction) and rule.text.upper() in text:
            return {
                "ledger": {
                    "id": rule.ledger_id,
                    "number": rule.ledger.number,
                    "name": rule.ledger.name,
                },
                "division": rule.division.code if rule.division_id else None,
                "from": "rule",
            }
    key = _norm(line.description)
    if not key:
        return None
    earlier = (
        StatementMatch.objects.filter(posted=True, line__account=line.account)
        .exclude(line=line)
        .select_related("line", "entry")
        .order_by("-matched_at")
    )
    bank_id = line.account.ledger_account_id
    for match in earlier[:500]:
        if _norm(match.line.description) == key:
            other = (
                match.entry.lines.exclude(account_id=bank_id)
                .select_related("account", "division")
                .first()
            )
            if other is not None:
                return {
                    "ledger": {
                        "id": other.account_id,
                        "number": other.account.number,
                        "name": other.account.name,
                    },
                    "division": other.division.code if other.division_id else None,
                    "from": "earlier",
                }
    return None


def post_line(
    user: User,
    line: BankStatementLine,
    *,
    account: Account,
    division: Division | None = None,
    description: str = "",
) -> StatementMatch:
    """Post a statement line that has nothing in the books (bank charges, interest) and match
    it: money out Dr the account, Cr the bank; money in Dr the bank, Cr the account."""
    _accountant(user)
    if not isinstance(account, Account) or not account.is_active or account.merged_into_id:
        raise BankingError("Choose an active account to post the line to.")
    if account.account_type in NOT_TO_POST:
        raise BankingError(
            f"{account.name} is not posted from a statement line; match the line to its "
            "payment, receipt or transfer instead."
        )
    with audit_context("bank_line_posted"), transaction.atomic():
        line = (
            BankStatementLine.objects.select_for_update().select_related("account").get(pk=line.pk)
        )
        if StatementMatch.objects.filter(line=line).exists():
            raise BankingError("This statement line is already in the books.")
        bank = ledger(line.account)
        text = (description or line.description or "Bank statement line").strip()[:500]
        value = abs(amount(line))
        other = journal.Line(account=account, division=division, description=text)
        mine = journal.Line(account=bank, description=text)
        if line.money_out:
            other.debit, mine.credit = value, value
        else:
            mine.debit, other.credit = value, value
        try:
            entry = journal.post(
                user,
                entry_date=line.date,
                narration=f"{line.account.code} statement {line.date:%d/%m/%Y}: {text}",
                lines=[other, mine],
                source_type="bank_line",
                source_id=str(line.pk),
            )
        except AccountingError as error:
            raise BankingError(str(error)) from None
        return StatementMatch.objects.create(line=line, entry=entry, posted=True, matched_by=user)


# --- Matching ------------------------------------------------------------------------------


def match(user: User, line: BankStatementLine, entry: JournalEntry) -> StatementMatch:
    _accountant(user)
    with audit_context("bank_line_matched"), transaction.atomic():
        line = (
            BankStatementLine.objects.select_for_update().select_related("account").get(pk=line.pk)
        )
        if StatementMatch.objects.filter(line=line).exists():
            raise BankingError("This statement line is already matched.")
        if StatementMatch.objects.filter(entry=entry).exists():
            raise BankingError(f"{entry.number} is already matched to another statement line.")
        bank = ledger(line.account)
        net = entry.lines.filter(account=bank).aggregate(t=Sum(F("debit") - F("credit")))["t"]
        if (net or ZERO) != amount(line):
            raise BankingError(
                f"{entry.number} does not move {abs(amount(line)):,.2f} "
                f"{'into' if line.money_in else 'out of'} {line.account.code}."
            )
        upto = locked_to(line.account)
        if upto is not None and line.date <= upto:
            raise BankingError(
                f"{line.account.code} is reconciled to {upto:%d/%m/%Y}; it is locked."
            )
        return StatementMatch.objects.create(line=line, entry=entry, matched_by=user)


def unmatch(user: User, line: BankStatementLine) -> None:
    """Take a match off (a line posted from the statement keeps its entry, which can then be
    matched again or reversed)."""
    _accountant(user)
    found = StatementMatch.objects.filter(line=line).select_related("line__account").first()
    if found is None:
        raise BankingError("This statement line is not matched.")
    upto = locked_to(line.account)
    if upto is not None and line.date <= upto:
        raise BankingError(f"{line.account.code} is reconciled to {upto:%d/%m/%Y}; it is locked.")
    with audit_context("bank_line_unmatched"):
        found.delete()


def accept_suggestions(user: User, account: CompanyAccount, upto: date) -> int:
    """Match every line up to `upto` that has a suggestion (the Accountant's one click)."""
    _accountant(user)
    made = 0
    items = book_items(account)
    lines = BankStatementLine.objects.filter(
        account=account, date__lte=upto, match__isnull=True
    ).order_by("date", "id")
    for line in lines:
        found = suggestion(line, items)
        if found is None:
            continue
        entry = JournalEntry.objects.get(pk=found["entry"]["id"])
        match(user, line, entry)
        items = [i for i in items if i.entry.pk != entry.pk]
        made += 1
    return made


# --- The month ---------------------------------------------------------------------------


def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def summary(account: CompanyAccount, period_end: date) -> dict:
    """The reconciliation to `period_end`: balance per bank and per books, the items on one
    and not the other, and the difference (nil when reconciled)."""
    bank = ledger(account)
    lines = BankStatementLine.objects.filter(account=account, date__lte=period_end)
    last = lines.exclude(balance=None).order_by("-date", "-statement_id", "-line_no").first()
    bank_balance = last.balance if last else None
    book_balance = (
        JournalLine.objects.filter(account=bank, entry__entry_date__lte=period_end).aggregate(
            t=Sum(F("debit") - F("credit"))
        )["t"]
        or ZERO
    )
    start = history_start(account)
    unpresented = book_items(account, period_end, start) if start else []
    not_in_books = list(lines.filter(match__isnull=True).order_by("date", "id"))
    u = sum((i.amount for i in unpresented), ZERO)
    b = sum((amount(x) for x in not_in_books), ZERO)
    difference = None if bank_balance is None else bank_balance - (book_balance - u + b)
    return {
        "account": account,
        "period_end": period_end,
        "bank_balance": bank_balance,
        "book_balance": book_balance,
        "unpresented": unpresented,
        "unpresented_total": u,
        "not_in_books": not_in_books,
        "not_in_books_total": b,
        "difference": difference,
        "locked_to": locked_to(account),
    }


def finish(user: User, account: CompanyAccount, period_end: date, note: str = ""):
    """Lock the month: every statement line to its end is in the books and the difference is
    nil. The matched cheques are marked cleared on the statement date."""
    _accountant(user)
    if period_end != month_end(period_end):
        raise BankingError("A reconciliation ends on the last day of a month.")
    if period_end > timezone.localdate():
        raise BankingError("The month has not ended yet.")
    with audit_context("bank_reconciled", note), transaction.atomic():
        CompanyAccount.objects.select_for_update().filter(pk=account.pk).first()
        upto = locked_to(account)
        if upto is not None and period_end <= upto:
            raise BankingError(f"{account.code} is already reconciled to {upto:%d/%m/%Y}.")
        figures = summary(account, period_end)
        if figures["bank_balance"] is None:
            raise BankingError("There is no imported statement up to that date.")
        if figures["not_in_books"]:
            raise BankingError(
                f"{len(figures['not_in_books'])} statement line(s) are not in the books yet; "
                "match or post them first."
            )
        if figures["difference"] != ZERO:
            raise BankingError(
                f"The reconciliation is out by {figures['difference']:,.2f}; it cannot be finished."
            )
        made = BankReconciliation.objects.create(
            account=account,
            period_end=period_end,
            bank_balance=figures["bank_balance"],
            book_balance=figures["book_balance"],
            unpresented=figures["unpresented_total"],
            note=(note or "").strip()[:2000],
            done_by=user,
        )
        _clear_cheques(user, account, period_end)
        return made


def _clear_cheques(user: User, account: CompanyAccount, period_end: date) -> None:
    matches = StatementMatch.objects.filter(
        line__account=account, line__date__lte=period_end
    ).select_related("line", "entry")
    for m in matches:
        payment = getattr(m.entry, "supplier_payment", None)
        if payment is not None and payment.cheque_id and not payment.cancelled:
            ChequeClearance.objects.get_or_create(
                leaf_id=payment.cheque_id, defaults={"cleared_on": m.line.date, "created_by": user}
            )
        deposit = Deposit.objects.filter(journal_entry=m.entry).first()
        if deposit is not None:
            for slip_line in deposit.lines.all():
                ChequeClearance.objects.get_or_create(
                    deposit_line=slip_line,
                    defaults={"cleared_on": m.line.date, "created_by": user},
                )
