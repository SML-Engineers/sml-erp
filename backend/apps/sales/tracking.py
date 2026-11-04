"""Invoice tracking (backlog P2-27, spec 7A; owner, 3 Nov 2026).

- When an issued tax invoice is emailed, the message carries a secret link to a customer page
  (no sign-in) with the invoice, its PDF and the company's bank details for a transfer, with
  the invoice number as the reference. Opening the page or the PDF is recorded as "viewed";
  email "open" tracking is unreliable, so only the link counts.
- SML has no payment gateway: when a customer asks to pay by card, Sales or the Accountant
  makes a OnePay payment link and sends it, then records it here (link, amount, date). The
  money is recorded as a card receipt when it reaches the bank. There is no Pay Now button.
- The invoice's history lists, in date order: issued, emailed, viewed, card link sent, each
  receipt (recorded, post-dated, deposited, returned), credit notes, and where it stands now
  (open, overdue, partly paid, paid).
"""

import secrets
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from apps.core import document_email
from apps.core.audit import audit_context
from apps.core.models import User

from . import invoices
from .models import (
    CardPaymentLink,
    CreditNote,
    CustomerReceipt,
    InvoiceLink,
    InvoiceView,
    ReceiptAllocation,
    TaxInvoice,
)
from .services import SalesError

CENT = Decimal("0.01")
PATH = "/api/v1/public/invoices/{token}/"


def link_for(invoice: TaxInvoice) -> InvoiceLink:
    """The invoice's secret link, made the first time it is needed."""
    if invoice.status != TaxInvoice.Status.ISSUED:
        raise SalesError("Only an issued tax invoice has a customer link.")
    found = InvoiceLink.objects.filter(invoice=invoice).first()
    if found is not None:
        return found
    link, _ = InvoiceLink.objects.get_or_create(
        invoice=invoice, defaults={"token": secrets.token_urlsafe(32)}
    )
    return link


def by_token(token: str) -> TaxInvoice | None:
    link = (
        InvoiceLink.objects.filter(token=token or "")
        .select_related("invoice__currency", "invoice__division", "invoice__customer")
        .first()
    )
    if link is None or link.invoice.status != TaxInvoice.Status.ISSUED:
        return None
    return link.invoice


def record_view(invoice: TaxInvoice, what: str) -> None:
    InvoiceView.objects.create(invoice=invoice, what=what)


def bank_accounts(invoice: TaxInvoice) -> list:
    """The company's bank accounts in the invoice's currency, the invoice's division first."""
    from apps.masters.models import CompanyAccount

    rows = CompanyAccount.objects.filter(
        is_active=True,
        currency=invoice.currency,
        kind__in=[CompanyAccount.Kind.CURRENT, CompanyAccount.Kind.SAVINGS],
    ).exclude(account_number="")
    return sorted(rows, key=lambda a: (a.division_id != invoice.division_id, a.code))


# --- Card payment links (OnePay) ---------------------------------------------------------------


def add_card_link(user: User, invoice: TaxInvoice, *, url: str, amount, sent_on: date, note=""):
    from django.core.exceptions import ValidationError
    from django.core.validators import URLValidator

    if not invoices.can_prepare(user):
        raise SalesError("Sales or the Accountant record card payment links.")
    if invoice.status != TaxInvoice.Status.ISSUED:
        raise SalesError("Card payment links are recorded for issued invoices.")
    url = (url or "").strip()
    try:
        URLValidator(schemes=["https"])(url)
    except ValidationError:
        raise SalesError("Paste the OnePay link, starting with https://.") from None
    if isinstance(amount, float):
        raise SalesError("The amount must be exact.")
    try:
        value = Decimal(str(amount).replace(",", "").strip())
    except InvalidOperation:
        raise SalesError("The amount is not a number.") from None
    if not value.is_finite() or value <= 0 or value != value.quantize(CENT):
        raise SalesError("Give the amount of the link, to the cent.")
    if sent_on > timezone.localdate():
        raise SalesError("The date the link was sent cannot be in the future.")
    with audit_context("card_link_recorded"):
        return CardPaymentLink.objects.create(
            invoice=invoice,
            url=url,
            amount=value,
            sent_on=sent_on,
            note=" ".join((note or "").split())[:300],
            created_by=user,
        )


# --- History -----------------------------------------------------------------------------------


def _day(value: date):
    return timezone.make_aware(datetime.combine(value, time.min))


def history(invoice: TaxInvoice) -> dict:
    from apps.sales import receipts

    events = []
    if invoice.issued_at:
        events.append({"at": invoice.issued_at, "kind": "issued", "text": "Issued"})
    for e in document_email.sent_for("tax_invoice", invoice.pk):
        events.append(
            {
                "at": e.sent_at,
                "kind": "emailed" if e.status == "sent" else "email_failed",
                "text": f"Emailed to {e.to}" if e.status == "sent" else f"Email failed: {e.error}",
            }
        )
    views = list(InvoiceView.objects.filter(invoice=invoice))
    if views:
        events.append(
            {
                "at": views[0].viewed_at,
                "kind": "viewed",
                "text": f"Viewed by the customer ({len(views)} time{'s' * (len(views) > 1)})",
            }
        )
    for c in CardPaymentLink.objects.filter(invoice=invoice).select_related("created_by"):
        events.append(
            {
                "at": _day(c.sent_on),
                "kind": "card_link",
                "text": f"OnePay link for {invoice.currency.code} {c.amount:,.2f} sent "
                f"by {c.created_by.full_name}",
                "url": c.url,
            }
        )
    for a in (
        ReceiptAllocation.objects.filter(invoice=invoice)
        .select_related("receipt__deposit_line__deposit")
        .order_by("receipt__receipt_date", "id")
    ):
        r = a.receipt
        what = f"{r.get_method_display()} {r.number} for {invoice.currency.code} {a.amount:,.2f}"
        when = _day(r.receipt_date)
        status = {
            CustomerReceipt.Status.POSTED: "paid",
            CustomerReceipt.Status.POST_DATED: "post_dated",
            CustomerReceipt.Status.RETURNED: "returned",
        }.get(r.status, "received")
        events.append(
            {"at": when, "kind": status, "text": f"Payment: {what} ({r.get_status_display()})"}
        )
        line = getattr(r, "deposit_line", None)
        if line is not None:
            events.append(
                {
                    "at": _day(line.deposit.deposit_date),
                    "kind": "deposited",
                    "text": f"Cheque deposited ({line.deposit.number})",
                }
            )
    for n in CreditNote.objects.filter(invoice=invoice, status=CreditNote.Status.APPROVED):
        events.append(
            {
                "at": _day(n.credit_date),
                "kind": "credited",
                "text": f"Credit note {n.number} for {invoice.currency.code} {n.total_amount:,.2f}",
            }
        )
    events.sort(key=lambda e: e["at"])
    figures = receipts.settlement([invoice])[invoice.pk]
    left = figures["open"]
    if invoice.status != TaxInvoice.Status.ISSUED:
        state = "draft"
    elif left <= 0:
        state = "paid"
    elif left < invoice.total_amount:
        state = "partly_paid"
    elif invoice.due_date < timezone.localdate():
        state = "overdue"
    else:
        state = "open"
    return {
        "state": state,
        "open": left,
        "viewed": bool(views),
        "events": events,
    }
