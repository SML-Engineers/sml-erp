"""The printed quotation (backlog P15-07, spec 5.1), in the layout of SML's own quotation
(sample QL26061501, received 31 Oct 2026), improved:

- letterhead: logo, company name, address, phone, fax and email;
- "Name / Address" of the customer on the left; QUOTATION, Our Ref and the date on the right;
- the lines in a boxed table (description, quantity, unit price and total in the quotation's
  currency), with the drawing number, quantity breaks, minimum order and tooling shown in
  the description;
- the discount (P15-07b), SSCL and its rate, Subtotal, VAT and its rate, Total; the exchange
  rate for an export quotation;
- payment terms, quotation validity in days, delivery term (Incoterm) and lead time;
- "We assure our Best Service at all times", the Managing Director's signature line and the
  slogan "Excellence through expertise". No SVAT line (the scheme ended on 1 Oct 2025).

The customer's copy holds no costing: it is built from the quotation alone. Until the
Director approves it, every page carries a large NOT APPROVED – DRAFT mark (P15-06); a
quotation replaced by a revision, lost or expired says so instead. The layout itself is
shared with the proforma (document_pdf.py).
"""

from . import workflow
from .document_pdf import Document, Line, build, money, qty, taxes_by_component
from .models import Quotation

S = Quotation.Status
MARKS = {
    S.DRAFT: "NOT APPROVED – DRAFT",
    S.AWAITING_APPROVAL: "NOT APPROVED – DRAFT",
    S.REVISED: "REPLACED BY A REVISION",
    S.LOST: "NOT VALID",
    S.EXPIRED: "EXPIRED",
}


def mark_for(quotation: Quotation) -> str:
    """The large mark across the page, or "" for an approved quotation."""
    if workflow.is_final(quotation):
        return ""
    return MARKS.get(quotation.status, "NOT APPROVED – DRAFT")


def tax_summary(quotation: Quotation):
    return taxes_by_component(quotation.lines.select_related("tax_code"), quotation.quote_date)


def document(quotation: Quotation) -> Document:
    currency = quotation.currency.code
    customer = quotation.customer
    reference = quotation.number + (f" Rev {quotation.revision}" if quotation.revision else "")
    lines = []
    for line in quotation.lines.prefetch_related("breaks"):
        text = line.description
        if line.drawing_no:
            text += f"\nDrawing {line.drawing_no}" + (
                f" rev {line.drawing_rev}" if line.drawing_rev else ""
            )
        if line.is_tooling:
            text += "\n(Tooling – charged once)"
        for b in line.breaks.all():
            text += f"\nFor {qty(b.quantity)} {line.unit}: {currency} {money(b.unit_price)} each"
        if line.min_order_qty:
            text += f"\nMinimum order: {qty(line.min_order_qty)} {line.unit}"
        shown = qty(line.quantity) + ("" if line.unit == "pcs" else f" {line.unit}")
        lines.append(Line(text, shown, line.unit_price, line.amount))
    before, after = tax_summary(quotation)
    validity = (quotation.valid_until - quotation.quote_date).days
    terms = [
        ("Payment Terms", quotation.payment_terms),
        ("Quotation Validity", f"{validity:02d} Days (until {quotation.valid_until:%d-%b-%Y})"),
        ("Delivery Term", quotation.incoterm),
    ]
    if quotation.delivery_lead_time:
        terms.append(("Delivery Time", quotation.delivery_lead_time))
    return Document(
        title="QUOTATION",
        reference=reference,
        when=quotation.quote_date,
        customer_name=customer.name,
        customer_address=customer.billing_address,
        customer_vat=customer.vat_no,
        attention=quotation.contact.name if quotation.contact else "",
        other_refs=[f"Your Ref: {quotation.enquiry_ref}"] if quotation.enquiry_ref else [],
        currency=currency,
        lines=lines,
        discount_pct=quotation.discount_pct,
        discount_total=quotation.discount_total,
        net_total=quotation.subtotal,
        taxes_before=before,
        taxes_after=after,
        total=quotation.total_amount,
        exchange_rate=quotation.exchange_rate,
        rate_date=quotation.rate_date,
        terms=terms,
        notes=quotation.notes,
        mark=mark_for(quotation),
        pdf_title=f"Quotation {reference}",
    )


def render(quotation: Quotation, *, compress: bool = True) -> bytes:
    """The PDF. Tests read it uncompressed to check what text it holds."""
    return build(document(quotation), compress=compress)
