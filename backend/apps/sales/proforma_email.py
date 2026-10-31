"""Emailing an issued proforma to the customer with its PDF (backlog P15-08, spec 3B), by its
creator or the Sales Manager. Every email sent or attempted is recorded (P0-19)."""

from apps.core import document_email
from apps.core.document_email import EmailError
from apps.core.models import SentEmail, User

from . import proforma_printing, proformas
from .models import ProformaInvoice
from .services import SalesError

KIND = "proforma"


def _values(proforma: ProformaInvoice) -> dict:
    contact = proforma.contact
    return {
        "document_number": proforma.number,
        "document_date": f"{proforma.issue_date:%d-%b-%Y}",
        "amount": f"{proforma.total_amount:,.2f}",
        "currency": proforma.currency.code,
        "recipient_name": contact.name if contact else proforma.customer.name,
    }


def _refusal(proforma: ProformaInvoice) -> str:
    if proforma.status != ProformaInvoice.Status.ISSUED:
        return "Only an issued proforma is emailed."
    return "The proforma's creator or the Sales Manager emails it."


def draft(user: User, proforma: ProformaInvoice) -> dict:
    if not proformas.can_email(user, proforma):
        raise SalesError(_refusal(proforma))
    contact = proforma.contact
    to = [a for a in (contact.email if contact else "", proforma.customer.email) if a][:1]
    try:
        return document_email.draft(user, KIND, _values(proforma), to=to)
    except EmailError as error:
        raise SalesError(str(error)) from None


def send(user: User, proforma: ProformaInvoice, *, to, subject, body, cc=()) -> SentEmail:
    if not proformas.can_email(user, proforma):
        raise SalesError(_refusal(proforma))
    try:
        return document_email.send(
            user,
            kind=KIND,
            label=f"Proforma invoice {proforma.number}",
            to=to,
            cc=cc,
            subject=subject,
            body=body,
            document_id=proforma.pk,
            attachment=(
                f"Proforma-{proforma.number}.pdf",
                proforma_printing.render(proforma),
                "application/pdf",
            ),
        )
    except EmailError as error:
        raise SalesError(str(error)) from None


def history(proforma: ProformaInvoice) -> list[dict]:
    return [
        {
            "to": row.to,
            "subject": row.subject,
            "status": row.status,
            "error": row.error,
            "sent_at": row.sent_at,
            "by": row.sent_by.full_name if row.sent_by else "",
        }
        for row in document_email.sent_for(KIND, proforma.pk)
    ]
