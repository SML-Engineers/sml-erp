"""Emailing an approved purchase order to the supplier with its PDF (backlog P16-05, spec 3B),
by the Purchasing Officer. A PO not yet approved, cancelled or replaced is never emailed.
Every email sent or attempted is recorded (P0-19)."""

from apps.core import document_email
from apps.core.document_email import EmailError
from apps.core.models import SentEmail, User

from . import orders, printing
from .models import PurchaseOrder
from .orders import PurchasingError

KIND = "purchase_order"
SENDABLE = (
    PurchaseOrder.Status.APPROVED,
    PurchaseOrder.Status.PARTLY_RECEIVED,
)


def can_email(user: User, order: PurchaseOrder) -> bool:
    return order.status in SENDABLE and orders.can_enter(user)


def _refusal(order: PurchaseOrder) -> str:
    if order.status not in SENDABLE:
        return "Only an approved purchase order is emailed to the supplier."
    return "The Purchasing Officer emails purchase orders."


def _values(order: PurchaseOrder) -> dict:
    return {
        "document_number": order.label,
        "document_date": f"{order.po_date:%d-%b-%Y}",
        "delivery_date": f"{order.delivery_date:%d-%b-%Y}" if order.delivery_date else "",
        "amount": f"{order.total_amount:,.2f}",
        "currency": order.currency.code,
        "recipient_name": order.supplier.contact_person or order.supplier.name,
    }


def draft(user: User, order: PurchaseOrder) -> dict:
    if not can_email(user, order):
        raise PurchasingError(_refusal(order))
    to = [order.supplier.email] if order.supplier.email else []
    try:
        return document_email.draft(user, KIND, _values(order), to=to)
    except EmailError as error:
        raise PurchasingError(str(error)) from None


def send(user: User, order: PurchaseOrder, *, to, subject, body, cc=()) -> SentEmail:
    if not can_email(user, order):
        raise PurchasingError(_refusal(order))
    try:
        return document_email.send(
            user,
            kind=KIND,
            label=f"Purchase order {order.label}",
            to=to,
            cc=cc,
            subject=subject,
            body=body,
            document_id=order.pk,
            attachment=(
                f"PO-{order.label.replace(' ', '-')}.pdf",
                printing.render(order),
                "application/pdf",
            ),
        )
    except EmailError as error:
        raise PurchasingError(str(error)) from None


def history(order: PurchaseOrder) -> list[dict]:
    return [
        {
            "to": row.to,
            "subject": row.subject,
            "status": row.status,
            "error": row.error,
            "sent_at": row.sent_at,
            "by": row.sent_by.full_name if row.sent_by else "",
        }
        for row in document_email.sent_for(KIND, order.pk)
    ]
