"""Emailing a quotation to the customer (backlog P15-07, spec 3B).

Only a quotation approved by the Director is emailed (owner, 31 Oct 2026), by its creator or
the Sales Manager, from the company's document mailbox, with the PDF attached. Every email
sent or attempted is recorded as sent (P0-19). The first email that goes out marks an
approved quotation Sent.
"""

from apps.core import document_email
from apps.core.document_email import EmailError
from apps.core.models import SentEmail, User

from . import printing, workflow
from .models import Quotation
from .services import SalesError

KIND = "quotation"


def can_email(user: User, quotation: Quotation) -> bool:
    return quotation.status in (
        Quotation.Status.APPROVED,
        Quotation.Status.SENT,
    ) and workflow._owner_or_manager(user, quotation)


def _values(quotation: Quotation) -> dict:
    contact = quotation.contact
    return {
        "document_number": quotation.label if quotation.revision else quotation.number,
        "document_date": f"{quotation.quote_date:%d-%b-%Y}",
        "valid_until": f"{quotation.valid_until:%d-%b-%Y}",
        "amount": f"{quotation.total_amount:,.2f}",
        "currency": quotation.currency.code,
        "recipient_name": contact.name if contact else quotation.customer.name,
    }


def recipients(quotation: Quotation) -> list[str]:
    contact = quotation.contact
    found = [contact.email if contact else "", quotation.customer.email]
    return [address for address in found if address][:1]


def draft(user: User, quotation: Quotation) -> dict:
    if not can_email(user, quotation):
        raise SalesError(_refusal(quotation))
    try:
        return document_email.draft(user, KIND, _values(quotation), to=recipients(quotation))
    except EmailError as error:
        raise SalesError(str(error)) from None


def _refusal(quotation: Quotation) -> str:
    if not workflow.is_final(quotation) or quotation.status == Quotation.Status.ACCEPTED:
        if quotation.status in (Quotation.Status.DRAFT, Quotation.Status.AWAITING_APPROVAL):
            return "Only a quotation approved by the Director can be emailed."
    if quotation.status not in (Quotation.Status.APPROVED, Quotation.Status.SENT):
        return f"A quotation that is {quotation.get_status_display().lower()} is not emailed."
    return "The quotation's creator or the Sales Manager emails it."


def send(user: User, quotation: Quotation, *, to, subject: str, body: str, cc=()) -> SentEmail:
    """Send the quotation with its PDF. Returns the record; a failed send is recorded too
    and leaves the quotation as it was."""
    if not can_email(user, quotation):
        raise SalesError(_refusal(quotation))
    name = (quotation.label if quotation.revision else quotation.number).replace(" ", "-")
    try:
        record = document_email.send(
            user,
            kind=KIND,
            label=f"Quotation {quotation.label}",
            to=to,
            cc=cc,
            subject=subject,
            body=body,
            document_id=quotation.pk,
            attachment=(f"Quotation-{name}.pdf", printing.render(quotation), "application/pdf"),
        )
    except EmailError as error:
        raise SalesError(str(error)) from None
    if record.status == SentEmail.Status.SENT and quotation.status == Quotation.Status.APPROVED:
        workflow.mark_sent(user, quotation, when=record.sent_at)
    return record


def history(quotation: Quotation) -> list[dict]:
    return [
        {
            "to": row.to,
            "cc": row.cc,
            "subject": row.subject,
            "status": row.status,
            "error": row.error,
            "sent_at": row.sent_at,
            "by": row.sent_by.full_name if row.sent_by else "",
        }
        for row in document_email.sent_for(KIND, quotation.pk)
    ]
