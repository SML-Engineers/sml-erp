"""The printed purchase order (backlog P16-05), in the layout of SML's own purchase order
(sample PO26061701, received 31 Oct 2026):

letterhead with PURCHASE ORDER; "To:" the supplier's name and address; P.O. No., Date, Pay
Mode and Pay Terms on the left, Delivery Date and Deliver to on the right; the boxed lines
(Item, Description, UOM, Qty, Rate, Amount) with the Grand Total; the instructions to the
supplier; Subtotal and the taxes in a box; "Yours Faithfully", the company, and the signature
lines for the Managing Director and Checked By. A PO not approved is marked DRAFT – NOT
APPROVED; a cancelled or revised one says so across every page.
"""

from collections import OrderedDict
from decimal import Decimal
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, SimpleDocTemplate, Spacer

from apps.accounting import taxes
from apps.accounting.models import TaxCodeLine
from apps.core.models import Company
from apps.sales.document_pdf import (
    GRID,
    MARGIN,
    MARK_COLOUR,
    SHADE,
    SIGNATORY,
    WIDTH,
    Styles,
    letterhead,
    money,
    qty,
    rate,
)
from apps.vouchers.printing import Table

from .models import PurchaseOrder

St = PurchaseOrder.Status
MARKS = {
    St.DRAFT: "DRAFT – NOT APPROVED",
    St.AWAITING_APPROVAL: "DRAFT – NOT APPROVED",
    St.CANCELLED: "CANCELLED",
    St.REVISED: "REPLACED BY A REVISION",
}
INSTRUCTIONS = (
    "Please indicate our P.O. No in all your invoices, proforma invoices and other relevant "
    "documents, deliver to the above mentioned destination and invoice to the correct party.",
    "Payment will be made strictly up to the quantity and the relevant value of the purchase "
    "order.",
)


def _taxes(order: PurchaseOrder) -> OrderedDict:
    """Each tax component and rate with its amount, worked out line by line as when saved."""
    found = OrderedDict()
    for line in order.lines.select_related("tax_code"):
        if line.tax_code is None:
            continue
        bases = {
            row.component_id: row.base for row in TaxCodeLine.objects.filter(tax_code=line.tax_code)
        }
        for part in taxes.calculate(line.tax_code, line.amount, order.po_date).lines:
            key = (part.component.code, part.rate, bases.get(part.component.pk))
            found[key] = found.get(key, Decimal("0")) + part.amount
    return found


def render(order: PurchaseOrder, *, compress: bool = True) -> bytes:
    s = Styles()
    p = s.p
    currency = order.currency.code
    supplier = order.supplier

    to = [p("To:", s.small), p(supplier.name, s.bold)]
    if supplier.address:
        to.append(p(supplier.address))
    if supplier.vat_no:
        to.append(p(f"VAT No: {supplier.vat_no}", s.small))
    facts = Table(
        [
            [p("P.O. No.", s.bold), p(order.label)],
            [p("Date", s.bold), p(f"{order.po_date:%d-%b-%Y}")],
            [p("Pay Mode", s.bold), p(order.get_pay_mode_display())],
            [p("Pay Terms", s.bold), p(order.payment_terms or "–")],
        ],
        colWidths=[26 * mm, 50 * mm],
        style=[("LEFTPADDING", (0, 0), (-1, -1), 0)],
    )
    delivery = [
        p(f"Delivery Date: {order.delivery_date:%d-%b-%Y}" if order.delivery_date else ""),
        Spacer(1, 2 * mm),
        p("Deliver to:", s.small),
        p(order.deliver_to),
    ]
    head = Table(
        [[p("PURCHASE ORDER", s.title)]],
        colWidths=[WIDTH],
        style=[("LEFTPADDING", (0, 0), (-1, -1), 0)],
    )
    top = Table(
        [[to + [Spacer(1, 4 * mm), facts], delivery]],
        colWidths=[WIDTH * 0.55, WIDTH * 0.45],
        style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)],
    )

    rows = [
        [
            p("Item", s.head),
            p("Description", s.head),
            p("UOM", s.head),
            p("Qty", s.head),
            p(f"Rate\n{currency}", s.head),
            p(f"Amount\n{currency}", s.head),
        ]
    ]
    for line in order.lines.select_related("item"):
        rows.append(
            [
                p(line.item.code),
                p(line.description),
                p(line.unit, s.right),
                p(qty(line.quantity), s.right),
                p(money(line.unit_price), s.right),
                p(money(line.amount), s.right),
            ]
        )
    rows.append(
        [
            p("Grand Total", s.total),
            "",
            "",
            "",
            p(f"{currency} {money(order.total_amount)}", s.right_bold),
            "",
        ]
    )
    end = len(rows) - 1
    lines = Table(
        rows,
        colWidths=[
            WIDTH * 0.14,
            WIDTH * 0.38,
            WIDTH * 0.08,
            WIDTH * 0.11,
            WIDTH * 0.13,
            WIDTH * 0.16,
        ],
        repeatRows=1,
        style=[
            ("BOX", (0, 0), (-1, -1), 0.8, GRID),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, GRID),
            ("LINEBEFORE", (1, 0), (-1, end - 1), 0.4, GRID),
            ("BACKGROUND", (0, 0), (-1, 0), SHADE),
            ("LINEABOVE", (0, end), (-1, end), 0.8, GRID),
            ("SPAN", (0, end), (3, end)),
            ("SPAN", (4, end), (5, end)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ],
    )

    totals = [[p("Subtotal", s.bold), p(f"{currency} {money(order.subtotal)}", s.right)]]
    for (code, tax_rate, _base), amount in _taxes(order).items():
        totals.append(
            [
                p(f"{code} Total ({rate(tax_rate)})", s.bold),
                p(f"{currency} {money(amount)}", s.right),
            ]
        )
    totals_box = Table(
        totals,
        colWidths=[38 * mm, 40 * mm],
        style=[("BOX", (0, 0), (-1, -1), 0.8, GRID), ("LINEBELOW", (0, 0), (-1, -2), 0.4, GRID)],
    )
    company = Company.objects.filter(pk=1).first()
    company_name = company.name if company else ""
    words = [p(text) for text in INSTRUCTIONS]
    if order.notes:
        words += [Spacer(1, 2 * mm), p("Notes", s.bold), p(order.notes)]
    words += [Spacer(1, 4 * mm), p("Yours Faithfully,"), p(company_name.upper())]
    close = Table(
        [[words, totals_box]],
        colWidths=[WIDTH - 82 * mm, 82 * mm],
        style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)],
    )
    signatures = Table(
        [
            [p(".................................."), p(".................................."), ""],
            [p(SIGNATORY), p("Checked By"), p(f"Date {order.po_date:%d-%b-%Y}", s.right)],
        ],
        colWidths=[WIDTH / 3] * 3,
        style=[("LEFTPADDING", (0, 0), (-1, -1), 0)],
    )
    story = letterhead(s) + [
        head,
        top,
        Spacer(1, 5 * mm),
        lines,
    ]
    if currency != "LKR":
        text = f"Exchange rate: 1 {currency} = LKR {order.exchange_rate.normalize():f}"
        story.append(p(text, s.small))
    story += [Spacer(1, 4 * mm), KeepTogether([close, Spacer(1, 14 * mm), signatures])]

    mark = MARKS.get(order.status, "")

    def on_page(canvas, document):
        if not mark:
            return
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 46)
        canvas.setFillColor(MARK_COLOUR)
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(40)
        canvas.drawCentredString(0, 0, mark)
        canvas.restoreState()

    buffer = BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"Purchase order {order.label}",
        author=company_name,
        pageCompression=1 if compress else 0,
    ).build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()
