"""The printed receipt for a customer advance (backlog P15-09) or for money received against
tax invoices (P2-07): company letterhead, RECEIPT, the number and date, who paid, how much in
figures and words (and its LKR value for a foreign-currency receipt), how it was paid, and
what it is for.

A receipt not yet approved by the Accountant says "AWAITING APPROVAL"; a rejected one says
"REJECTED – NOT VALID", so neither can pass for a valid receipt. A post-dated cheque says so.
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

from .models import CustomerAdvance, CustomerReceipt

GREY = colors.HexColor("#555555")
LINE = colors.HexColor("#999999")
MARKS = {
    CustomerAdvance.Status.AWAITING_APPROVAL: "AWAITING APPROVAL",
    CustomerAdvance.Status.REJECTED: "REJECTED – NOT VALID",
}
RECEIPT_MARKS = {
    CustomerReceipt.Status.AWAITING_APPROVAL: "AWAITING APPROVAL",
    CustomerReceipt.Status.REJECTED: "REJECTED – NOT VALID",
    CustomerReceipt.Status.POST_DATED: "POST-DATED CHEQUE – SUBJECT TO REALISATION",
    CustomerReceipt.Status.RETURNED: "CHEQUE RETURNED – NOT PAID",
}


def render(advance: CustomerAdvance) -> bytes:
    currency = advance.currency.code
    rows = [
        ["Receipt no.", advance.number, "Date", advance.receipt_date.strftime("%d/%m/%Y")],
        ["Received from", f"{advance.customer.name} ({advance.customer.code})", "", ""],
        ["Amount", f"{currency} {advance.amount:,.2f}", "", ""],
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
    return _build(advance.number, MARKS.get(advance.status), rows, advance.created_by.full_name)


def render_receipt(receipt: CustomerReceipt) -> bytes:
    """Money received for tax invoices (P2-07), in LKR, with the invoices it pays."""
    rows = [
        ["Receipt no.", receipt.number, "Date", receipt.receipt_date.strftime("%d/%m/%Y")],
        ["Received from", f"{receipt.customer.name} ({receipt.customer.code})", "", ""],
        ["Amount", f"LKR {receipt.amount:,.2f}", "", ""],
        ["In words", amount_in_words(receipt.amount, "LKR"), "", ""],
    ]
    paid = receipt.get_method_display()
    if receipt.reference:
        paid += f" {receipt.reference}"
    if receipt.method == CustomerReceipt.Method.CHEQUE:
        if receipt.cheque_bank:
            paid += f", {receipt.cheque_bank}"
        rows.append(["Paid by", paid, "Dated", receipt.cheque_date.strftime("%d/%m/%Y")])
    else:
        rows.append(["Paid by", paid, "Into", receipt.account.name])
    paying = [
        f"Tax invoice {a.invoice.number}: LKR {a.amount:,.2f}"
        for a in receipt.allocations.select_related("invoice").order_by("id")
    ]
    rows.append(["For", "\n".join(paying), "", ""])
    if receipt.notes:
        rows.append(["Notes", receipt.notes, "", ""])
    return _build(
        receipt.number, RECEIPT_MARKS.get(receipt.status), rows, receipt.created_by.full_name
    )


def _build(number: str, mark: str | None, rows: list[list[str]], received_by: str) -> bytes:
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
    if mark:
        story.append(p(mark, warn))
    story.append(Spacer(1, 2 * mm))

    table = [[p(a, muted), p(b), p(c, muted), p(d)] for a, b, c, d in rows]
    story.append(
        Table(
            table,
            colWidths=[28 * mm, 92 * mm, 16 * mm, None],
            style=[
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
            # A row with nothing on its right uses the whole width.
            + [("SPAN", (1, i), (3, i)) for i, row in enumerate(rows) if not (row[2] or row[3])],
        )
    )
    story.append(Spacer(1, 10 * mm))
    story.append(
        Table(
            [
                [
                    p(f"Received by: {received_by}", muted),
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
        title=f"Receipt {number}",
    ).build(story)
    return buffer.getvalue()
