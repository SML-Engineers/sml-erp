"""The kinds of documents and reports that can be emailed, the placeholders each allows,
and the starting messages (spec 3B). The Admin edits the messages; this file only gives
the first version, loaded by migration 0013 (frozen: later defaults are a new constant)."""

COMMON = {
    "company_name": "The company's name",
    "company_phone": "The company's phone number",
    "company_email": "The company's email address",
    "sender_name": "The name of the person sending",
    "recipient_name": "The customer's or supplier's name",
}

KINDS = {
    "quotation": (
        "Quotation",
        {
            "document_number": "Quotation number",
            "document_date": "Quotation date",
            "valid_until": "Valid until",
            "amount": "Total amount",
            "currency": "Currency",
        },
    ),
    "proforma": (
        "Proforma invoice",
        {
            "document_number": "Proforma invoice number",
            "document_date": "Date",
            "amount": "Total amount",
            "currency": "Currency",
        },
    ),
    "tax_invoice": (
        "Tax invoice",
        {
            "document_number": "Invoice number",
            "document_date": "Invoice date",
            "due_date": "Due date",
            "amount": "Invoice total",
            "currency": "Currency",
        },
    ),
    "customer_statement": (
        "Customer statement / outstanding",
        {
            "statement_date": "Statement date",
            "amount_due": "Total outstanding",
            "overdue_amount": "Overdue amount",
            "currency": "Currency",
        },
    ),
    "purchase_order": (
        "Purchase order",
        {
            "document_number": "Purchase order number",
            "document_date": "Date",
            "delivery_date": "Delivery date",
            "amount": "Total amount",
            "currency": "Currency",
        },
    ),
    "payment_advice": (
        "Payment advice to a supplier",
        {
            "document_number": "Payment number",
            "payment_date": "Payment date",
            "amount": "Amount paid",
            "currency": "Currency",
            "reference": "Cheque number or transfer reference",
            "invoices": "Invoices paid",
        },
    ),
    "report": (
        "Report (outstanding, aging, profit and loss…)",
        {
            "report_name": "Report name",
            "period": "Period or date of the report",
        },
    ),
}

SIGN_OFF = "Thank you.\n\nKind regards,\n{sender_name}\n{company_name}\n{company_phone}"

DEFAULT_TEMPLATES_V1 = {
    "quotation": (
        "Quotation {document_number} from {company_name}",
        "Dear {recipient_name},\n\nPlease find attached our quotation {document_number} dated "
        "{document_date} for {currency} {amount}, valid until {valid_until}.\n\nPlease let us "
        "know if you have any questions.\n\n" + SIGN_OFF,
    ),
    "proforma": (
        "Proforma invoice {document_number} from {company_name}",
        "Dear {recipient_name},\n\nPlease find attached proforma invoice {document_number} dated "
        "{document_date} for {currency} {amount}.\n\n" + SIGN_OFF,
    ),
    "tax_invoice": (
        "Tax invoice {document_number} from {company_name}",
        "Dear {recipient_name},\n\nPlease find attached tax invoice {document_number} dated "
        "{document_date} for {currency} {amount}, due on {due_date}.\n\n" + SIGN_OFF,
    ),
    "customer_statement": (
        "Statement of account from {company_name} as at {statement_date}",
        "Dear {recipient_name},\n\nPlease find attached your statement of account as at "
        "{statement_date}. The total outstanding is {currency} {amount_due}, of which "
        "{currency} {overdue_amount} is overdue.\n\nWe would be grateful for your payment at "
        "your earliest convenience. If you have already paid, please ignore this message.\n\n"
        + SIGN_OFF,
    ),
    "purchase_order": (
        "Purchase order {document_number} from {company_name}",
        "Dear {recipient_name},\n\nPlease find attached our purchase order {document_number} "
        "dated {document_date}, for delivery by {delivery_date}.\n\nPlease confirm receipt and "
        "the delivery date.\n\n" + SIGN_OFF,
    ),
    "payment_advice": (
        "Payment advice {document_number} from {company_name}",
        "Dear {recipient_name},\n\nWe have paid {currency} {amount} on {payment_date} "
        "(reference {reference}) for: {invoices}.\n\nThe payment advice is attached.\n\n"
        + SIGN_OFF,
    ),
    "report": (
        "{report_name} – {period}",
        "Dear {recipient_name},\n\nPlease find attached the {report_name} for {period}.\n\n"
        + SIGN_OFF,
    ),
}


def allowed(kind: str) -> dict[str, str]:
    return {**COMMON, **KINDS[kind][1]}
