"""The layout shared by SML's printed sales documents (quotation P15-07, proforma P15-08),
copied from the owner's own forms (samples QL26061501 and PI191120-02, 31 Oct 2026):

letterhead; "Name / Address" on the left and the title, Our Ref and date on the right; the
boxed lines with discount, SSCL, subtotal, VAT and total; terms; notes; "We assure our Best
Service at all times", the Managing Director's line and the slogan. A document that is not
final carries a large mark across every page. Extra pages (the packing list) follow.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer

from apps.accounting import taxes
from apps.accounting.models import TaxCodeLine
from apps.core.models import Company
from apps.vouchers.printing import Table, _logo

SLOGAN = "EXCELLENCE THROUGH EXPERTISE"
SIGNATORY = "Managing Director"
GRID = colors.HexColor("#333333")
SHADE = colors.HexColor("#eeeeee")
MARK_COLOUR = colors.Color(0.75, 0.1, 0.1, alpha=0.18)
MARGIN = 14 * mm
WIDTH = A4[0] - 2 * MARGIN


def money(value: Decimal) -> str:
    return f"{value:,.2f}"


def qty(value: Decimal) -> str:
    text = f"{value.normalize():f}"
    if "." in text:
        whole, frac = text.split(".")
        return f"{int(whole):,}.{frac}"
    return f"{int(text):,}"


def rate(value: Decimal) -> str:
    return f"{value.normalize():f}%"


def taxes_by_component(lines, on_date: date):
    """The taxes of the lines by component and rate, worked out line by line at the rates
    of `on_date` on each line's net (after discount), each line rounded as when saved:
    those on the net amount (SSCL) come before the subtotal, those on net plus tax (VAT)
    after it."""
    before, after = OrderedDict(), OrderedDict()
    for line in lines:
        if line.tax_code is None:
            continue
        bases = {
            row.component_id: row.base for row in TaxCodeLine.objects.filter(tax_code=line.tax_code)
        }
        for part in taxes.calculate(line.tax_code, line.net, on_date).lines:
            key = (part.component.label, part.rate)
            on_tax = bases.get(part.component.pk) == TaxCodeLine.Base.NET_AND_TAX
            group = after if on_tax else before
            group[key] = group.get(key, Decimal("0")) + part.amount
    return before, after


@dataclass
class Line:
    text: str
    quantity: str
    unit_price: Decimal
    amount: Decimal


@dataclass
class Document:
    title: str
    reference: str
    when: date
    customer_name: str
    customer_address: str = ""
    customer_vat: str = ""
    attention: str = ""
    other_refs: list[str] = field(default_factory=list)  # e.g. "Your PO: 4512"
    currency: str = "LKR"
    lines: list[Line] = field(default_factory=list)
    discount_pct: Decimal = Decimal("0")
    discount_total: Decimal = Decimal("0")
    net_total: Decimal = Decimal("0")  # after discount, before tax
    taxes_before: dict = field(default_factory=dict)
    taxes_after: dict = field(default_factory=dict)
    total: Decimal = Decimal("0")
    exchange_rate: Decimal = Decimal("1")
    rate_date: date | None = None
    after_totals: list[str] = field(default_factory=list)  # e.g. advance and balance
    terms: list[tuple[str, str]] = field(default_factory=list)
    boxes: list[tuple[str, list[str]]] = field(default_factory=list)  # e.g. bank details
    notes: str = ""
    mark: str = ""
    pdf_title: str = ""
    extra_pages: list = field(default_factory=list)  # functions (styles) -> flowables


class Styles:
    def __init__(self):
        def style(name, size, bold=False, **extra):
            font = extra.pop("fontName", "Helvetica-Bold" if bold else "Helvetica")
            return ParagraphStyle(name, fontName=font, fontSize=size, leading=size * 1.25, **extra)

        self.body = style("body", 9)
        self.small = style("small", 8)
        self.company = style("company", 15, bold=True, alignment=TA_CENTER)
        self.centre = style("centre", 8.5, alignment=TA_CENTER)
        self.title = style("title", 18, bold=True, alignment=TA_RIGHT)
        self.right = style("right", 9, alignment=TA_RIGHT)
        self.right_bold = style("right_bold", 10, bold=True, alignment=TA_RIGHT)
        self.bold = style("bold", 9, bold=True)
        self.head = style("head", 8.5, bold=True, alignment=TA_CENTER)
        self.total = style("total", 12, bold=True)
        self.slogan = style(
            "slogan", 11, bold=True, alignment=TA_CENTER, fontName="Helvetica-BoldOblique"
        )

    def p(self, text, st=None):
        return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), st or self.body)


def letterhead(s: Styles) -> list:
    company = Company.objects.filter(pk=1).first()
    lines = []
    if company:
        lines.append(s.p(company.name.upper(), s.company))
        if company.address:
            lines.append(s.p(company.address, s.centre))
        contact = ", ".join(
            x
            for x in (
                f"Tel: {company.phone}" if company.phone else "",
                f"Email: {company.email}" if company.email else "",
            )
            if x
        )
        if contact:
            lines.append(s.p(contact, s.centre))
        if company.vat_no:
            lines.append(s.p(f"VAT No: {company.vat_no}", s.centre))
    logo = _logo(company, 20 * mm) if company else None
    return [
        Table(
            [[logo or "", lines]],
            colWidths=[28 * mm, WIDTH - 28 * mm],
            style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)],
        ),
        Spacer(1, 5 * mm),
    ]


def heading(doc: Document, s: Styles, title: str | None = None) -> list:
    address = [s.p("Name / Address", s.small), s.p(doc.customer_name, s.bold)]
    if doc.customer_address:
        address.append(s.p(doc.customer_address))
    if doc.attention:
        address.append(s.p(f"Attention: {doc.attention}", s.small))
    if doc.customer_vat:
        address.append(s.p(f"VAT No: {doc.customer_vat}", s.small))
    right = [
        s.p(title or doc.title, s.title),
        Spacer(1, 2 * mm),
        s.p(f"Our Ref: {doc.reference}", s.right),
        s.p(f"Date: {doc.when:%d-%b-%Y}", s.right),
    ]
    right += [s.p(ref, s.right) for ref in doc.other_refs]
    return [
        Table(
            [[address, right]],
            colWidths=[WIDTH * 0.6, WIDTH * 0.4],
            style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)],
        ),
        Spacer(1, 4 * mm),
    ]


def lines_table(doc: Document, s: Styles) -> list:
    currency = doc.currency
    p = s.p
    rows = [
        [
            p("Description", s.head),
            p("Qty", s.head),
            p(f"Unit Price\n{currency}", s.head),
            p(f"Total\n{currency}", s.head),
        ]
    ]
    for line in doc.lines:
        rows.append(
            [
                p(line.text),
                p(line.quantity, s.right),
                p(money(line.unit_price), s.right),
                p(money(line.amount), s.right),
            ]
        )
    if doc.discount_total:
        rows.append(
            [
                p(f"Discount – {rate(doc.discount_pct)}"),
                "",
                p(f"-{rate(doc.discount_pct)}", s.right),
                p(f"-{money(doc.discount_total)}", s.right),
            ]
        )
    subtotal = doc.net_total + sum(doc.taxes_before.values(), Decimal("0"))
    for (code, tax_rate), amount in doc.taxes_before.items():
        rows.append([p(code), "", p(rate(tax_rate), s.right), p(money(amount), s.right)])
    rows.append([p("Subtotal", s.bold), "", "", p(money(subtotal), s.right_bold)])
    for (code, tax_rate), amount in doc.taxes_after.items():
        rows.append(
            [p(f"{code} ({rate(tax_rate)})"), "", "", p(f"{currency} {money(amount)}", s.right)]
        )
    rows.append([p("Total", s.total), "", "", p(f"{currency} {money(doc.total)}", s.right_bold)])
    end = len(rows) - 1
    story = [
        Table(
            rows,
            colWidths=[WIDTH * 0.55, WIDTH * 0.1, WIDTH * 0.17, WIDTH * 0.18],
            repeatRows=1,
            style=[
                ("BOX", (0, 0), (-1, -1), 0.8, GRID),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, GRID),
                ("LINEBEFORE", (1, 0), (-1, -1), 0.4, GRID),
                ("BACKGROUND", (0, 0), (-1, 0), SHADE),
                ("LINEABOVE", (0, end), (-1, end), 0.8, GRID),
                ("BACKGROUND", (0, end), (-1, end), SHADE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ],
        )
    ]
    if currency != "LKR":
        text = f"Exchange rate used: 1 {currency} = LKR {doc.exchange_rate.normalize():f}"
        if doc.rate_date:
            text += f" ({doc.rate_date:%d-%b-%Y})"
        story.append(p(text, s.small))
    if doc.after_totals:
        story.append(Spacer(1, 2 * mm))
    for text in doc.after_totals:
        story.append(p(text, s.bold))
    return story


def terms_and_close(doc: Document, s: Styles) -> list:
    p = s.p
    story = [Spacer(1, 4 * mm)]
    if doc.terms:
        story.append(
            Table(
                [[p(f"{label}:", s.bold), p(value or "–")] for label, value in doc.terms],
                colWidths=[38 * mm, WIDTH - 38 * mm],
                style=[("BOX", (0, 0), (-1, -1), 0.6, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP")],
            )
        )
    for label, rows in doc.boxes:
        story.append(Spacer(1, 3 * mm))
        story.append(
            Table(
                [[p(label, s.bold)]] + [[p(row)] for row in rows],
                colWidths=[WIDTH],
                style=[("BOX", (0, 0), (-1, -1), 0.6, GRID)],
            )
        )
    if doc.notes:
        story += [Spacer(1, 3 * mm), p("Notes", s.bold), p(doc.notes)]
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
                p(SLOGAN, s.slogan),
            ]
        )
    )
    return story


def build(doc: Document, *, compress: bool = True) -> bytes:
    """The PDF. Tests read it uncompressed to check what text it holds."""
    s = Styles()
    story = letterhead(s) + heading(doc, s) + lines_table(doc, s) + terms_and_close(doc, s)
    for page in doc.extra_pages:
        story.append(PageBreak())
        story += letterhead(s)
        story += page(s)

    def on_page(canvas, document):
        if not doc.mark:
            return
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 46)
        canvas.setFillColor(MARK_COLOUR)
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(40)
        canvas.drawCentredString(0, 0, doc.mark)
        canvas.restoreState()

    company = Company.objects.filter(pk=1).first()
    buffer = BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=doc.pdf_title or f"{doc.title.title()} {doc.reference}",
        author=company.name if company else "",
        pageCompression=1 if compress else 0,
    ).build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()
