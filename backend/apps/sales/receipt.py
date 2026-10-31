"""The printed receipt for a customer advance (backlog P15-09): company letterhead, RECEIPT,
the number and date, who paid, how much in figures and words (and its LKR value for a
foreign-currency receipt), how it was paid, and what it is for.

A receipt not yet approved by the Accountant says "AWAITING APPROVAL"; a rejected one says
"REJECTED – NOT VALID", so neither can pass for a valid receipt.
"""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A5, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from apps.core.models import Company
from apps.core.words import amount_in_words
from apps.vouchers.printing import Table, _logo

from .models import CustomerAdvance

GREY = colors.HexColor("#555555")
LINE = colors.HexColor("#999999")
MARKS = {
    CustomerAdvance.Status.AWAITING_APPROVAL: "AWAITING APPROVAL",
    CustomerAdvance.Status.REJECTED: "REJECTED – NOT VALID",
}


def render(advance: CustomerAdvance) -> bytes:
    page = landscape(A5)
    margin = 12 * mm

    def style(name, size, bold=False, **extra):
        return ParagraphStyle(
            name,
            fontName="Helvetica-Bold" if bold else "Helvetica",
            fontSize=size,
            leading=size * 1.25,
            **extra,
        )

    body, muted = style("body", 9), style("muted", 8, textColor=GREY)
    head, title = style("head", 14, bold=True), style("title", 13, bold=True)
    warn = style("warn", 13, bold=True, textColor=colors.HexColor("#b00020"))

    def p(text, st=body):
        return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), st)

    company = Company.objects.filter(pk=1).first()
    story = []
    lines = []
    if company:
        lines.append(p(company.name, head))
        if company.address:
            lines.append(p(company.address, muted))
        contact = " · ".join(x for x in (company.phone, company.email) if x)
        if contact:
            lines.append(p(contact, muted))
    logo = _logo(company, 14 * mm) if company else None
    story.append(
        Table(
            [[logo or "", lines]],
            colWidths=[26 * mm if logo else 0.1, None],
            style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)],
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(p("RECEIPT", title))
    mark = MARKS.get(advance.status)
    if mark:
        story.append(p(mark, warn))
    story.append(Spacer(1, 2 * mm))

    currency = advance.currency.code
    amount = f"{currency} {advance.amount:,.2f}"
    rows = [
        ["Receipt no.", advance.number, "Date", advance.receipt_date.strftime("%d/%m/%Y")],
        ["Received from", f"{advance.customer.name} ({advance.customer.code})", "", ""],
        ["Amount", amount, "", ""],
        ["In words", amount_in_words(advance.amount, currency), "", ""],
    ]
    if currency != "LKR":
        rows.append(
            [
                "LKR value",
                f"LKR {advance.amount_lkr:,.2f} at {advance.exchange_rate.normalize():f}",
                "",
                "",
            ]
        )
    paid = advance.get_method_display()
    if advance.reference:
        paid += f" {advance.reference}"
    rows.append(["Paid by", paid, "Into", advance.account.name])
    towards = "Advance payment"
    if advance.sales_order_id:
        towards += f" against sales order {advance.sales_order.number}"
        if advance.sales_order.customer_po:
            towards += f" (your PO {advance.sales_order.customer_po})"
    elif advance.proforma_id:
        towards += f" against proforma invoice {advance.proforma.number}"
    elif advance.quotation_id:
        towards += f" against quotation {advance.quotation.label}"
    rows.append(["For", towards, "", ""])
    if advance.notes:
        rows.append(["Notes", advance.notes, "", ""])
    table = [[p(a, muted), p(b), p(c, muted), p(d)] for a, b, c, d in rows]
    story.append(
        Table(
            table,
            colWidths=[28 * mm, 92 * mm, 16 * mm, None],
            style=[
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("SPAN", (1, 1), (3, 1)),
                ("SPAN", (1, 2), (3, 2)),
                ("SPAN", (1, 3), (3, 3)),
            ],
        )
    )
    story.append(Spacer(1, 10 * mm))
    story.append(
        Table(
            [
                [
                    p(f"Received by: {advance.created_by.full_name}", muted),
                    p("Signature: ________________", muted),
                ]
            ],
            colWidths=[None, 70 * mm],
        )
    )

    buffer = BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=page,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=f"Receipt {advance.number}",
    ).build(story)
    return buffer.getvalue()
