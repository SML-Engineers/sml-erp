"""Customer statements, receivables aging, credit control and payment reminders (backlog
P2-08, spec 6, 7A).

Statements and aging
- A customer's statement is its Accounts receivable ledger for a period: the opening balance,
  every posting (invoices, credit notes, receipts, advances set off, journals) with a running
  balance, and the closing balance; with its open invoices aged at the end date. Printed and
  emailed from the finance mailbox.
- The aging lists what each customer still owes on its invoices at a date, by days past the
  due date (not yet due, 1-30, 31-60, 61-90, over 90), next to the customer's ledger balance
  so any difference shows. Only posted receipts count as paid here.

Credit control (owner, 3 Nov 2026: block)
- A customer with overdue invoices, or who would owe more than its credit limit with the new
  document, gets no new sales order (confirming it) and no tax invoice (issuing it) until the
  Director allows that document. What it owes counts its open invoices, less receipts already
  recorded and approved advances not yet set off; an empty credit limit means no limit.
- The stopped document becomes a credit hold, the Director is told, and allows it with a
  note ("allow_credit_holds", sensitive). The allowance covers that document up to the amount
  allowed. Holds are never deleted and allowed ones never change (database guard).

Payment reminders
- The Accountant switches reminders on for a customer, with how often. A daily job emails
  the statement from the finance mailbox while the customer has overdue invoices, at most
  every so many days, and stops once they are paid. Each reminder is recorded.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.accounting.models import JournalLine
from apps.core import document_email
from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.document_email import EmailError
from apps.core.models import MailAccount, SentEmail, User
from apps.core.notifications import notify
from apps.masters.models import Customer

from . import invoices, receipts
from .models import (
    AdvanceSetOff,
    CreditHold,
    CreditNote,
    CustomerAdvance,
    CustomerReceipt,
    ReceiptAllocation,
    ReminderPlan,
    ReminderSent,
    TaxInvoice,
)
from .services import SalesError

log = logging.getLogger(__name__)

ZERO = Decimal("0.00")
ALLOW = "allow_credit_holds"
EMAIL_KIND = "customer_statement"
BUCKETS = (
    ("current", "Not yet due"),
    ("d30", "1-30 days"),
    ("d60", "31-60 days"),
    ("d90", "61-90 days"),
    ("over90", "Over 90 days"),
)
Hold = CreditHold.Status


# --- Who may do what ------------------------------------------------------------


def can_view(user: User) -> bool:
    """Statements, aging and holds: Sales or Accounting, View."""
    return invoices.can_view(user)


def can_manage(user: User) -> bool:
    """Emailing statements and setting reminders: the Accountant (Accounting: Enter)."""
    return effective_access(user).has("accounting", "enter")


def can_allow(user: User) -> bool:
    return effective_access(user).can(ALLOW)


def _bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "d30"
    if days_overdue <= 60:
        return "d60"
    if days_overdue <= 90:
        return "d90"
    return "over90"


# --- What is open at a date (posted documents only) ----------------------------------


def open_at(rows: list[TaxInvoice], as_at: date) -> dict[int, Decimal]:
    """Per issued invoice: its total less what was credited, received (posted receipts) and
    set off on or before `as_at`."""
    left = {i.pk: i.total_amount for i in rows}
    keys = list(left)
    taken = [
        CreditNote.objects.filter(
            invoice__in=keys, status=CreditNote.Status.APPROVED, credit_date__lte=as_at
        )
        .values("invoice")
        .annotate(total=Sum("total_amount")),
        ReceiptAllocation.objects.filter(
            invoice__in=keys,
            receipt__status=CustomerReceipt.Status.POSTED,
            receipt__journal_entry__entry_date__lte=as_at,
        )
        .values("invoice")
        .annotate(total=Sum("amount")),
        AdvanceSetOff.objects.filter(invoice__in=keys, set_off_date__lte=as_at)
        .values("invoice")
        .annotate(total=Sum("amount")),
    ]
    for query in taken:
        for r in query:
            left[r["invoice"]] -= r["total"]
    return left


def open_items(user: User, as_at: date, customer: Customer | None = None) -> list[dict]:
    """The invoices the user may see with something open at `as_at`, oldest first."""
    rows = invoices.visible(user).filter(status=TaxInvoice.Status.ISSUED, invoice_date__lte=as_at)
    if customer is not None:
        rows = rows.filter(customer=customer)
    rows = list(rows.select_related("customer", "division").order_by("invoice_date", "id"))
    amounts = open_at(rows, as_at)
    items = []
    for invoice in rows:
        amount = amounts[invoice.pk]
        if amount == 0:
            continue
        days = (as_at - invoice.due_date).days
        items.append(
            {"invoice": invoice, "open": amount, "days_overdue": days, "bucket": _bucket(days)}
        )
    return items


def _ledger(user: User):
    """Receivables ledger lines of the user's divisions (and those with no division)."""
    return JournalLine.objects.filter(
        account__account_type="accounts_receivable", customer__isnull=False
    ).filter(Q(division__in=division_scope(user)) | Q(division__isnull=True))


def _balance(rows) -> Decimal:
    totals = rows.aggregate(debit=Sum("debit"), credit=Sum("credit"))
    return (totals["debit"] or ZERO) - (totals["credit"] or ZERO)


def aging(user: User, as_at: date, customer: Customer | None = None) -> list[dict]:
    """One row per customer: what is open by age, the total, and the ledger balance."""
    by_customer: dict[int, dict] = {}

    def row_for(c: Customer) -> dict:
        if c.pk not in by_customer:
            by_customer[c.pk] = {
                "customer_id": c.pk,
                "code": c.code,
                "customer": c.name,
                **{key: ZERO for key, _ in BUCKETS},
                "total": ZERO,
                "ledger": ZERO,
            }
        return by_customer[c.pk]

    for item in open_items(user, as_at, customer):
        row = row_for(item["invoice"].customer)
        row[item["bucket"]] += item["open"]
        row["total"] += item["open"]
    ledger = _ledger(user).filter(entry__entry_date__lte=as_at)
    if customer is not None:
        ledger = ledger.filter(customer=customer)
    balances = ledger.values("customer").annotate(debit=Sum("debit"), credit=Sum("credit"))
    names = Customer.objects.in_bulk([b["customer"] for b in balances])
    for b in balances:
        amount = (b["debit"] or ZERO) - (b["credit"] or ZERO)
        if amount or b["customer"] in by_customer:
            row_for(names[b["customer"]])["ledger"] = amount
    rows = sorted(by_customer.values(), key=lambda r: r["customer"].lower())
    return [{k: (f"{v:.2f}" if isinstance(v, Decimal) else v) for k, v in r.items()} for r in rows]


# --- Statements ------------------------------------------------------------


@dataclass
class Statement:
    customer: Customer
    start: date
    end: date
    opening: Decimal
    lines: list[dict]
    closing: Decimal
    items: list[dict]
    buckets: dict = field(default_factory=dict)
    overdue: Decimal = ZERO
    advances_held: Decimal = ZERO


def advances_held(customer: Customer) -> Decimal:
    """Approved advances of the customer not yet set off (money held on its account)."""
    total = CustomerAdvance.objects.filter(
        customer=customer, status=CustomerAdvance.Status.APPROVED
    ).aggregate(left=Sum(F("amount_lkr") - F("set_off_lkr")))["left"]
    return total or ZERO


def statement(user: User, customer: Customer, start: date, end: date) -> Statement:
    if end < start:
        raise SalesError("The statement's end date is before its start date.")
    rows = _ledger(user).filter(customer=customer)
    opening = _balance(rows.filter(entry__entry_date__lt=start))
    balance = opening
    lines = []
    for line in (
        rows.filter(entry__entry_date__gte=start, entry__entry_date__lte=end)
        .select_related("entry")
        .order_by("entry__entry_date", "entry__number", "line_no")
    ):
        balance += line.debit - line.credit
        entry = line.entry
        lines.append(
            {
                "date": entry.entry_date,
                "reference": entry.source_id or entry.number,
                "source_type": entry.source_type,
                "description": line.description or entry.narration,
                "debit": line.debit,
                "credit": line.credit,
                "balance": balance,
            }
        )
    items = open_items(user, end, customer)
    buckets = {key: ZERO for key, _ in BUCKETS}
    for item in items:
        buckets[item["bucket"]] += item["open"]
    overdue = sum((v for k, v in buckets.items() if k != "current"), ZERO)
    return Statement(
        customer=customer,
        start=start,
        end=end,
        opening=opening,
        lines=lines,
        closing=balance,
        items=items,
        buckets=buckets,
        overdue=overdue,
        advances_held=advances_held(customer),
    )


# --- Credit control ------------------------------------------------------------


@dataclass
class Exposure:
    open_lkr: Decimal
    advances_lkr: Decimal
    overdue_lkr: Decimal
    overdue_count: int
    oldest_days: int

    @property
    def owed(self) -> Decimal:
        return self.open_lkr - self.advances_lkr


def exposure(customer: Customer, today: date | None = None) -> Exposure:
    """What the customer owes now: open on its issued invoices (receipts recorded count as
    paid), less approved advances not yet set off; and what of it is overdue."""
    today = today or timezone.localdate()
    rows = list(TaxInvoice.objects.filter(customer=customer, status=TaxInvoice.Status.ISSUED))
    figures = receipts.settlement(rows)
    open_total, overdue, count, oldest = ZERO, ZERO, 0, 0
    for invoice in rows:
        left = figures[invoice.pk]["open"]
        open_total += left
        if left > 0 and invoice.due_date < today:
            overdue += left
            count += 1
            oldest = max(oldest, (today - invoice.due_date).days)
    return Exposure(open_total, advances_held(customer), overdue, count, oldest)


def check(customer: Customer, amount_lkr: Decimal, today: date | None = None):
    """Why a new document of `amount_lkr` for the customer would be stopped (empty: it is
    not), with the figures."""
    figures = exposure(customer, today)
    reasons = []
    if figures.overdue_lkr > 0:
        plural = "s" if figures.overdue_count > 1 else ""
        reasons.append(
            f"{customer.name} has {figures.overdue_count} overdue invoice{plural} "
            f"(LKR {figures.overdue_lkr:,.2f}, the oldest {figures.oldest_days} days past due)."
        )
    limit = customer.credit_limit
    total = figures.owed + amount_lkr
    if limit is not None and total > limit:
        reasons.append(
            f"With this document {customer.name} would owe LKR {total:,.2f}, over its credit "
            f"limit of LKR {limit:,.2f}."
        )
    return reasons, figures


class CreditBlocked(SalesError):
    """A document stopped by credit control; credit.hold() records it for the Director."""

    def __init__(self, *, kind, document_id, label, customer, amount_lkr, figures, reasons):
        self.kind = kind
        self.document_id = document_id
        self.label = label
        self.customer = customer
        self.amount_lkr = amount_lkr
        self.figures = figures
        self.reasons = reasons
        super().__init__(
            "Credit hold: "
            + " ".join(reasons)
            + f" The Director has to allow {label} before it goes ahead; they have been told."
        )


def require(
    user: User, *, kind: str, document_id: int, label: str, customer: Customer, amount_lkr
) -> None:
    """Raise CreditBlocked unless the customer is within its credit, or the Director has
    allowed this document for at least this amount. Called inside the document's saving
    transaction, before anything is saved."""
    reasons, figures = check(customer, amount_lkr)
    if not reasons:
        return
    if CreditHold.objects.filter(
        document_type=kind,
        document_id=document_id,
        status=Hold.ALLOWED,
        amount_lkr__gte=amount_lkr,
    ).exists():
        return
    raise CreditBlocked(
        kind=kind,
        document_id=document_id,
        label=label,
        customer=customer,
        amount_lkr=amount_lkr,
        figures=figures,
        reasons=reasons,
    )


def allowers() -> list[User]:
    return [u for u in User.objects.filter(is_active=True) if can_allow(u)]


def link(hold: CreditHold) -> str:
    if hold.document_type == CreditHold.Kind.SALES_ORDER:
        return f"/sales-orders/{hold.document_id}"
    return f"/tax-invoices/{hold.document_id}"


def hold(user: User, blocked: CreditBlocked) -> CreditHold:
    """Record the stopped document for the Director (after its own transaction was rolled
    back). A waiting hold for the same document is brought up to date instead."""
    values = {
        "document_label": blocked.label[:100],
        "amount_lkr": blocked.amount_lkr,
        "exposure_lkr": blocked.figures.owed + blocked.amount_lkr,
        "credit_limit": blocked.customer.credit_limit,
        "overdue_lkr": blocked.figures.overdue_lkr,
        "reasons": "\n".join(blocked.reasons),
    }
    with audit_context("credit_hold"), transaction.atomic():
        waiting = (
            CreditHold.objects.select_for_update()
            .filter(
                document_type=blocked.kind, document_id=blocked.document_id, status=Hold.WAITING
            )
            .first()
        )
        if waiting is not None:
            for key, value in values.items():
                setattr(waiting, key, value)
            waiting.save()
            return waiting
        made = CreditHold.objects.create(
            document_type=blocked.kind,
            document_id=blocked.document_id,
            customer=blocked.customer,
            requested_by=user,
            **values,
        )
        notify(
            allowers(),
            "credit_hold_waiting",
            title=f"{made.document_label} for {made.customer.name} is on credit hold",
            body=made.reasons,
            link="/credit-holds",
            document_type="credit_hold",
            document_id=made.pk,
        )
        return made


def allow(user: User, credit_hold: CreditHold, note: str) -> CreditHold:
    """The Director allows the document to go ahead, with a note."""
    if not can_allow(user):
        raise SalesError("Only the Director allows a document on credit hold.")
    note = (note or "").strip()
    if not note:
        raise SalesError("Write why the document is allowed despite the credit hold.")
    with audit_context("credit_hold_allowed", note), transaction.atomic():
        credit_hold = CreditHold.objects.select_for_update().get(pk=credit_hold.pk)
        if credit_hold.status != Hold.WAITING:
            raise SalesError("This credit hold has already been allowed.")
        credit_hold.status = Hold.ALLOWED
        credit_hold.decided_by = user
        credit_hold.decided_at = timezone.now()
        credit_hold.note = note[:1000]
        credit_hold.save()
        notify(
            [credit_hold.requested_by],
            "credit_hold_allowed",
            title=f"{credit_hold.document_label} was allowed by {user.full_name}",
            body=note,
            link=link(credit_hold),
            document_type="credit_hold",
            document_id=credit_hold.pk,
        )
        return credit_hold


# --- Emailing statements and reminders ------------------------------------------------------------


def recipient(customer: Customer) -> str:
    """The main contact's email, or the customer's own."""
    contact = (
        customer.contacts.filter(is_active=True).exclude(email="").order_by("-is_main").first()
    )
    return contact.email if contact else customer.email


def _recipient_name(customer: Customer) -> str:
    contact = customer.contacts.filter(is_active=True, is_main=True).first()
    return contact.name if contact else customer.name


def _values(st: Statement) -> dict:
    return {
        "statement_date": f"{st.end:%d-%b-%Y}",
        "amount_due": f"{st.closing:,.2f}",
        "overdue_amount": f"{st.overdue:,.2f}",
        "currency": "LKR",
        "recipient_name": _recipient_name(st.customer),
    }


def _attachment(st: Statement) -> tuple[str, bytes, str]:
    from . import statement_printing

    return (
        f"Statement-{st.customer.code}-{st.end:%Y-%m-%d}.pdf",
        statement_printing.render(st),
        "application/pdf",
    )


def draft_email(user: User, st: Statement) -> dict:
    if not can_manage(user):
        raise SalesError("The Accountant emails statements.")
    try:
        to = [recipient(st.customer)]
        return document_email.draft(user, EMAIL_KIND, _values(st), to=to)
    except EmailError as error:
        raise SalesError(str(error)) from None


def send_email(user: User, st: Statement, *, to, subject, body, cc=()) -> SentEmail:
    if not can_manage(user):
        raise SalesError("The Accountant emails statements.")
    try:
        return document_email.send(
            user,
            kind=EMAIL_KIND,
            label=f"Statement {st.customer.code} to {st.end:%d/%m/%Y}",
            to=to,
            cc=cc,
            subject=subject,
            body=body,
            document_id=st.customer.pk,
            attachment=_attachment(st),
        )
    except EmailError as error:
        raise SalesError(str(error)) from None


def emails(customer: Customer) -> list[dict]:
    return [
        {
            "to": row.to,
            "subject": row.subject,
            "status": row.status,
            "error": row.error,
            "sent_at": row.sent_at,
            "by": row.sent_by.full_name if row.sent_by else "",
            "reminder": ReminderSent.objects.filter(email=row).exists(),
        }
        for row in document_email.sent_for(EMAIL_KIND, customer.pk)[:50]
    ]


def set_reminders(user: User, customer: Customer, *, is_on: bool, every_days) -> ReminderPlan:
    if not can_manage(user):
        raise SalesError("The Accountant sets payment reminders.")
    if not isinstance(every_days, int) or isinstance(every_days, bool) or not 1 <= every_days <= 90:
        raise SalesError("Reminders go every 1 to 90 days.")
    if is_on and not recipient(customer):
        raise SalesError(
            f"{customer.name} has no email address: add one to the customer or its main "
            "contact first."
        )
    with audit_context("reminder_plan_changed"), transaction.atomic():
        plan, _ = ReminderPlan.objects.update_or_create(
            customer=customer,
            defaults={
                "is_on": bool(is_on),
                "every_days": every_days,
                "set_by": user,
                "updated_at": timezone.now(),
            },
        )
        return plan


def send_reminders(today: date | None = None) -> int:
    """Daily: email the statement to each customer with reminders on and overdue invoices,
    unless one went within its interval. Returns how many were sent."""
    today = today or timezone.localdate()
    if not MailAccount.get().is_ready:
        log.warning("Payment reminders not sent: document email is not set up.")
        return 0
    sent = 0
    for plan in ReminderPlan.objects.filter(is_on=True).select_related("customer", "set_by"):
        customer = plan.customer
        figures = exposure(customer, today)
        if figures.overdue_lkr <= 0:
            continue  # paid up: reminders stop by themselves
        if ReminderSent.objects.filter(customer=customer, sent_on=today).exists():
            continue
        last = (
            ReminderSent.objects.filter(customer=customer, email__status=SentEmail.Status.SENT)
            .order_by("-sent_on")
            .first()
        )
        if last and (today - last.sent_on).days < plan.every_days:
            continue
        to = recipient(customer)
        if not to or not plan.set_by.is_active:
            log.warning("Payment reminder for %s not sent: no address or sender.", customer.code)
            continue
        first_open = (
            TaxInvoice.objects.filter(customer=customer, status=TaxInvoice.Status.ISSUED)
            .order_by("invoice_date")
            .values_list("invoice_date", flat=True)
            .first()
        )
        start = min(first_open or today, today - timedelta(days=90))
        try:
            with transaction.atomic():
                st = statement(plan.set_by, customer, start, today)
                message = document_email.draft(plan.set_by, EMAIL_KIND, _values(st), to=[to])
                email = document_email.send(
                    plan.set_by,
                    kind=EMAIL_KIND,
                    label=f"Payment reminder {customer.code} {today:%d/%m/%Y}",
                    to=[to],
                    subject=message["subject"],
                    body=message["body"],
                    document_id=customer.pk,
                    attachment=_attachment(st),
                )
                ReminderSent.objects.create(
                    customer=customer,
                    email=email,
                    amount_due_lkr=st.closing,
                    overdue_lkr=figures.overdue_lkr,
                    sent_on=today,
                )
        except (EmailError, SalesError):
            log.exception("Payment reminder for %s could not be made", customer.code)
            continue
        sent += email.status == SentEmail.Status.SENT
    return sent
