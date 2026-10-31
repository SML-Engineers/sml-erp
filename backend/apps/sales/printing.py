"""The printed quotation (backlog P15-07, spec 5.1), in the layout of SML's own quotation
(sample QL26061501, received 31 Oct 2026), improved:

- letterhead: logo, company name, address, phone, fax and email;
- "Name / Address" of the customer on the left; QUOTATION, Our Ref and the date on the right;
- the lines in a boxed table (description, quantity, unit price and total in the quotation's
  currency), with the drawing number, quantity breaks, minimum order and tooling shown in
  the description;
- SSCL and its rate, Subtotal, VAT and its rate, Total; the exchange rate for an export
  quotation;
- payment terms, quotation validity in days, delivery term (Incoterm) and lead time;
- "We assure our Best Service at all times", the Managing Director's signature line and the
  slogan "Excellence through expertise". No SVAT line (the scheme ended on 1 Oct 2025).

The customer's copy holds no costing: it is built from the quotation alone. Until the
Director approves it, every page carries a large NOT APPROVED – DRAFT mark (P15-06); a
quotation replaced by a revision, lost or expired says so instead.
"""

from collections import OrderedDict
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from apps.accounting import taxes
from apps.accounting.models import TaxCodeLine
from apps.core.models import Company
from apps.vouchers.printing import Table, _logo

from . import workflow
from .models import Quotation

SLOGAN = "EXCELLENCE THROUGH EXPERTISE"
SIGNATORY = "Managing Director"
GRID = colors.HexColor("#333333")
SHADE = colors.HexColor("#eeeeee")
MARK_COLOUR = colors.Color(0.75, 0.1, 0.1, alpha=0.18)
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


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def _qty(value: Decimal) -> str:
    text = f"{value.normalize():f}"
    if "." in text:
        whole, frac = text.split(".")
        return f"{int(whole):,}.{frac}"
    return f"{int(text):,}"


def tax_summary(quotation: Quotation):
    """The taxes of the quotation by component and rate, worked out line by line at the
    rates of its date (each line rounded, as when it was saved): those on the net amount
    (SSCL) come before the subtotal, those on net plus tax (VAT) after it."""
    before, after = OrderedDict(), OrderedDict()
    for line in quotation.lines.select_related("tax_code"):
        if line.tax_code is None:
            continue
        bases = {
            row.component_id: row.base for row in TaxCodeLine.objects.filter(tax_code=line.tax_code)
        }
        for part in taxes.calculate(line.tax_code, line.amount, quotation.quote_date).lines:
            key = (part.component.code, part.rate)
            group = (
                after if bases.get(part.component.pk) == TaxCodeLine.Base.NET_AND_TAX else before
            )
            group[key] = group.get(key, Decimal("0")) + part.amount
    return before, after


def _rate(rate: Decimal) -> str:
    text = f"{rate.normalize():f}"
    return f"{text}%"


def render(quotation: Quotation, *, compress: bool = True) -> bytes:
    """The PDF. Tests read it uncompressed to check what text it holds."""
    margin = 14 * mm
    page = A4
    width = page[0] - 2 * margin

    def style(name, size, bold=False, **extra):
        font = extra.pop("fontName", "Helvetica-Bold" if bold else "Helvetica")
        return ParagraphStyle(
            name,
            fontName=font,
            fontSize=size,
            leading=size * 1.25,
            **extra,
        )

    body = style("body", 9)
    small = style("small", 8)
    company_name = style("company", 15, bold=True, alignment=TA_CENTER)
    centre = style("centre", 8.5, alignment=TA_CENTER)
    title = style("title", 18, bold=True, alignment=TA_RIGHT)
    right = style("right", 9, alignment=TA_RIGHT)
    right_bold = style("right_bold", 10, bold=True, alignment=TA_RIGHT)
    bold = style("bold", 9, bold=True)
    head = style("head", 8.5, bold=True, alignment=TA_CENTER)
    slogan = style("slogan", 11, bold=True, alignment=TA_CENTER, fontName="Helvetica-BoldOblique")

    def p(text, st=body):
        return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), st)

    company = Company.objects.filter(pk=1).first()
    currency = quotation.currency.code
    story = []

    # Letterhead
    lines = []
    if company:
        lines.append(p(company.name.upper(), company_name))
        if company.address:
            lines.append(p(company.address, centre))
        contact = ", ".join(
            x
            for x in (
                f"Tel: {company.phone}" if company.phone else "",
                f"Email: {company.email}" if company.email else "",
            )
            if x
        )
        if contact:
            lines.append(p(contact, centre))
        if company.vat_no:
            lines.append(p(f"VAT No: {company.vat_no}", centre))
    logo = _logo(company, 20 * mm) if company else None
    story.append(
        Table(
            [[logo or "", lines]],
            colWidths=[28 * mm, width - 28 * mm],
            style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)],
        )
    )
    story.append(Spacer(1, 5 * mm))

    # Customer on the left; QUOTATION, Our Ref and the date on the right
    customer = quotation.customer
    address = [p("Name / Address", small), p(customer.name, bold)]
    if customer.billing_address:
        address.append(p(customer.billing_address))
    if quotation.contact:
        address.append(p(f"Attention: {quotation.contact.name}", small))
    if customer.vat_no:
        address.append(p(f"VAT No: {customer.vat_no}", small))
    reference = quotation.number + (f" Rev {quotation.revision}" if quotation.revision else "")
    heading = [
        p("QUOTATION", title),
        Spacer(1, 2 * mm),
        p(f"Our Ref: {reference}", right),
        p(f"Date: {quotation.quote_date:%d-%b-%Y}", right),
    ]
    if quotation.enquiry_ref:
        heading.append(p(f"Your Ref: {quotation.enquiry_ref}", right))
    story.append(
        Table(
            [[address, heading]],
            colWidths=[width * 0.6, width * 0.4],
            style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)],
        )
    )
    story.append(Spacer(1, 4 * mm))

    # The lines
    rows = [
        [
            p("Description", head),
            p("Qty", head),
            p(f"Unit Price\n{currency}", head),
            p(f"Total\n{currency}", head),
        ]
    ]
    for line in quotation.lines.prefetch_related("breaks"):
        text = line.description
        if line.drawing_no:
            text += f"\nDrawing {line.drawing_no}" + (
                f" rev {line.drawing_rev}" if line.drawing_rev else ""
            )
        if line.is_tooling:
            text += "\n(Tooling – charged once)"
        for b in line.breaks.all():
            text += f"\nFor {_qty(b.quantity)} {line.unit}: {currency} {_money(b.unit_price)} each"
        if line.min_order_qty:
            text += f"\nMinimum order: {_qty(line.min_order_qty)} {line.unit}"
        rows.append(
            [
                p(text),
                p(
                    f"{_qty(line.quantity)}" + ("" if line.unit == "pcs" else f" {line.unit}"),
                    right,
                ),
                p(_money(line.unit_price), right),
                p(_money(line.amount), right),
            ]
        )
    before, after = tax_summary(quotation)
    subtotal = quotation.subtotal + sum(before.values(), Decimal("0"))
    for (code, rate), amount in before.items():
        rows.append([p(code), "", p(_rate(rate), right), p(_money(amount), right)])
    rows.append([p("Subtotal", bold), "", "", p(_money(subtotal), right_bold)])
    for (code, rate), amount in after.items():
        rows.append(
            [p(f"{code} ({_rate(rate)})"), "", "", p(f"{currency} {_money(amount)}", right)]
        )
    rows.append(
        [
            p("Total", style("total", 12, bold=True)),
            "",
            "",
            p(f"{currency} {_money(quotation.total_amount)}", right_bold),
        ]
    )
    lines_end = len(rows) - 1
    story.append(
        Table(
            rows,
            colWidths=[width * 0.55, width * 0.1, width * 0.17, width * 0.18],
            repeatRows=1,
            style=[
                ("BOX", (0, 0), (-1, -1), 0.8, GRID),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, GRID),
                ("LINEBEFORE", (1, 0), (-1, -1), 0.4, GRID),
                ("BACKGROUND", (0, 0), (-1, 0), SHADE),
                ("LINEABOVE", (0, lines_end), (-1, lines_end), 0.8, GRID),
                ("BACKGROUND", (0, lines_end), (-1, lines_end), SHADE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ],
        )
    )
    if currency != "LKR":
        rate = f"{quotation.exchange_rate.normalize():f}"
        story.append(
            p(
                f"Exchange rate used: 1 {currency} = LKR {rate}"
                + (f" ({quotation.rate_date:%d-%b-%Y})" if quotation.rate_date else ""),
                small,
            )
        )
    story.append(Spacer(1, 4 * mm))

    # Terms
    validity = (quotation.valid_until - quotation.quote_date).days
    delivery = quotation.incoterm or "–"
    terms = [
        [p("Payment Terms:", bold), p(quotation.payment_terms or "–")],
        [
            p("Quotation Validity:", bold),
            p(f"{validity:02d} Days (until {quotation.valid_until:%d-%b-%Y})"),
        ],
        [p("Delivery Term:", bold), p(delivery)],
    ]
    if quotation.delivery_lead_time:
        terms.append([p("Delivery Time:", bold), p(quotation.delivery_lead_time)])
    story.append(
        Table(
            terms,
            colWidths=[38 * mm, width - 38 * mm],
            style=[("BOX", (0, 0), (-1, -1), 0.6, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP")],
        )
    )
    if quotation.notes:
        story.append(Spacer(1, 3 * mm))
        story.append(p("Notes", bold))
        story.append(p(quotation.notes))
    story.append(Spacer(1, 6 * mm))
    story.append(
        KeepTogether(
            [
                p("We assure our Best Service at all times."),
                Spacer(1, 3 * mm),
                p("Thanking you,"),
                p("Yours Sincerely,"),
                Spacer(1, 12 * mm),
                p(".................................."),
                p(SIGNATORY),
                Spacer(1, 8 * mm),
                p(SLOGAN, slogan),
            ]
        )
    )

    mark = mark_for(quotation)

    def on_page(canvas, document):
        if not mark:
            return
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 46)
        canvas.setFillColor(MARK_COLOUR)
        canvas.translate(page[0] / 2, page[1] / 2)
        canvas.rotate(40)
        canvas.drawCentredString(0, 0, mark)
        canvas.restoreState()

    buffer = BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=page,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=f"Quotation {reference}",
        author=company.name if company else "",
        pageCompression=1 if compress else 0,
    ).build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()
