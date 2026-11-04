"""Emailing an issued tax invoice to the customer with its PDF (P2-05, spec 3B), by Sales or
the Accountant. Every email sent or attempted is recorded (P0-19)."""

from apps.core import document_email
from apps.core.document_email import EmailError
from apps.core.models import SentEmail, User

from . import invoice_printing, invoices, tracking
from .models import TaxInvoice
from .services import SalesError

KIND = "tax_invoice"


def can_email(user: User, invoice: TaxInvoice) -> bool:
    # One brought over from QuickBooks (P2-28) was sent from QuickBooks: no PDF here.
    return (
        invoice.status == TaxInvoice.Status.ISSUED
        and not invoice.opening
        and invoices.can_prepare(user)
    )


def _values(invoice: TaxInvoice) -> dict:
    contact = invoice.order.contact
    return {
        "document_number": invoice.number,
        "document_date": f"{invoice.invoice_date:%d-%b-%Y}",
        "due_date": f"{invoice.due_date:%d-%b-%Y}",
        "amount": f"{invoice.total_amount:,.2f}",
        "currency": invoice.currency.code,
        "recipient_name": contact.name if contact else invoice.customer_name,
    }


def _check(user: User, invoice: TaxInvoice) -> None:
    if invoice.status != TaxInvoice.Status.ISSUED:
        raise SalesError("Only an issued tax invoice is emailed.")
    if not can_email(user, invoice):
        raise SalesError("Sales or the Accountant email tax invoices.")


def draft(user: User, invoice: TaxInvoice, site: str = "") -> dict:
    """The default message, with the invoice's secret link added at the end (P2-27). `site` is
    the address the system is reached at, e.g. https://erp.smlengineers.lk."""
    _check(user, invoice)
    contact = invoice.order.contact
    to = [a for a in (contact.email if contact else "", invoice.customer.email) if a][:1]
    try:
        message = document_email.draft(user, KIND, _values(invoice), to=to)
    except EmailError as error:
        raise SalesError(str(error)) from None
    link = tracking.link_for(invoice)
    url = site.rstrip("/") + tracking.PATH.format(token=link.token)
    message["body"] = f"{message['body'].rstrip()}\n\nView or download this invoice online:\n{url}"
    message["link"] = url
    return message


def send(user: User, invoice: TaxInvoice, *, to, subject, body, cc=()) -> SentEmail:
    _check(user, invoice)
    try:
        return document_email.send(
            user,
            kind=KIND,
            label=f"Tax invoice {invoice.number}",
            to=to,
            cc=cc,
            subject=subject,
            body=body,
            document_id=invoice.pk,
            attachment=(
                f"Tax-invoice-{invoice.number}.pdf",
                invoice_printing.render(invoice),
                "application/pdf",
            ),
        )
    except EmailError as error:
        raise SalesError(str(error)) from None


def history(invoice: TaxInvoice) -> list[dict]:
    return [
        {
            "to": row.to,
            "subject": row.subject,
            "status": row.status,
            "error": row.error,
            "sent_at": row.sent_at,
            "by": row.sent_by.full_name if row.sent_by else "",
        }
        for row in document_email.sent_for(KIND, invoice.pk)
    ]
