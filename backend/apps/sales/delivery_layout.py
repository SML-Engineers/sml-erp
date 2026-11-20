"""The delivery note's blocks for the template designer (owner, 13 Nov 2026: the delivery
note comes first). Each block prints one part of the note; the standard layout puts them
where the printed note has always had them (delivery_printing.py)."""

from xml.sax.saxutils import escape

from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer

from apps.core.models import Company
from apps.core.print_layout import ALIGN
from apps.vouchers.printing import Table, _logo

from .document_pdf import GRID, SHADE, SLOGAN, qty
from .models import DeliveryNote

# key, label shown in the designer, may it be hidden?
BLOCKS = [
    ("letterhead", "Letterhead (logo, name, address)", True),
    ("customer", "Customer and delivery address", False),
    ("title", "Title: DELIVERY NOTE", False),
    ("refs", "Our Ref, date, order and your PO", False),
    ("lines", "Items table", False),
    ("transport", "Vehicle, driver and notes", True),
    ("signatures", "Issued by / received by", True),
    ("slogan", "Slogan", True),
]

STANDARD = {
    "blocks": [
        {"key": "letterhead", "x": 0, "y": 0, "w": 182, "h": 24, "size": 9, "align": "center"},
        {"key": "customer", "x": 0, "y": 27, "w": 109, "h": 32, "size": 9, "align": "left"},
        {"key": "title", "x": 110, "y": 27, "w": 72, "h": 9, "size": 15, "align": "right"},
        {"key": "refs", "x": 110, "y": 37, "w": 72, "h": 22, "size": 9, "align": "right"},
        {"key": "lines", "x": 0, "y": 62, "w": 182, "h": 110, "size": 9, "align": "left"},
        {"key": "transport", "x": 0, "y": 176, "w": 182, "h": 15, "size": 9, "align": "left"},
        {"key": "signatures", "x": 0, "y": 195, "w": 182, "h": 40, "size": 9, "align": "left"},
        {"key": "slogan", "x": 0, "y": 241, "w": 182, "h": 8, "size": 9, "align": "center"},
    ]
}


def _style(size: float, align: str, bold: bool = False, name: str = "b") -> ParagraphStyle:
    return ParagraphStyle(
        name,
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size,
        leading=size * 1.25,
        alignment=ALIGN[align],
    )


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def contents(note: DeliveryNote, widths: dict[str, float]) -> dict:
    """What each block shows for this note. `widths` gives each block's width in mm, for the
    tables inside blocks."""
    order = note.order
    customer = order.customer
    company = Company.objects.filter(pk=1).first()

    def letterhead(size, align):
        style = _style(size, "center")
        lines = []
        if company:
            lines.append(_p(company.name.upper(), _style(size + 6, "center", bold=True)))
            if company.address:
                lines.append(_p(company.address, style))
            contact = ", ".join(
                x
                for x in (
                    f"Tel: {company.phone}" if company.phone else "",
                    f"Email: {company.email}" if company.email else "",
                )
                if x
            )
            if contact:
                lines.append(_p(contact, style))
            if company.vat_no:
                lines.append(_p(f"VAT No: {company.vat_no}", style))
        logo = _logo(company, 20 * mm) if company else None
        width = widths["letterhead"] * mm
        return [
            Table(
                [[logo or "", lines]],
                colWidths=[28 * mm, width - 28 * mm],
                style=[
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ],
            )
        ]

    def customer_block(size, align):
        out = [_p("Customer", _style(size - 1, align)), _p(customer.name, _style(size, align, 1))]
        if customer.billing_address:
            out.append(_p(customer.billing_address, _style(size, align)))
        if note.delivery_address:
            out += [
                Spacer(1, 2 * mm),
                _p("Deliver to", _style(size - 1, align)),
                _p(note.delivery_address, _style(size, align)),
            ]
        return out

    def title(size, align):
        return [_p("DELIVERY NOTE", _style(size, align, bold=True))]

    def refs(size, align):
        style = _style(size, align)
        out = [
            _p(f"Our Ref: {note.number or 'not issued yet'}", style),
            _p(f"Date: {note.delivery_date:%d-%b-%Y}", style),
            _p(f"Our order: {order.number}", style),
        ]
        if order.customer_po:
            out.append(_p(f"Your PO: {order.customer_po}", style))
        return out

    def lines(size, align):
        head, body = _style(size, "left", bold=True), _style(size, "left")
        right, right_bold = _style(size, "right"), _style(size, "right", bold=True)
        rows = [
            [
                _p("No.", head),
                _p("Description", head),
                _p("Qty ordered", head),
                _p("Qty delivered", head),
            ]
        ]
        for n, line in enumerate(note.lines.select_related("order_line"), start=1):
            ol = line.order_line
            text = ol.description + (f"\nDrawing {ol.drawing_no}" if ol.drawing_no else "")
            unit = "" if ol.unit == "pcs" else f" {ol.unit}"
            rows.append(
                [
                    _p(str(n), body),
                    _p(text, body),
                    _p(qty(ol.quantity) + unit, right),
                    _p(qty(line.quantity) + unit, right_bold),
                ]
            )
        width = widths["lines"] * mm
        return [
            Table(
                rows,
                colWidths=[width * 0.07, width * 0.59, width * 0.17, width * 0.17],
                repeatRows=1,
                style=[
                    ("BOX", (0, 0), (-1, -1), 0.8, GRID),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.8, GRID),
                    ("LINEBEFORE", (1, 0), (-1, -1), 0.4, GRID),
                    ("BACKGROUND", (0, 0), (-1, 0), SHADE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ],
            )
        ]

    def transport(size, align):
        bold, body = _style(size, "left", bold=True), _style(size, "left")
        rows = [
            [_p("Vehicle no.:", bold), _p(note.vehicle_no or "–", body)],
            [_p("Driver:", bold), _p(note.driver or "–", body)],
        ]
        if note.notes:
            rows.append([_p("Notes:", bold), _p(note.notes, body)])
        width = widths["transport"] * mm
        return [
            Table(
                rows,
                colWidths=[38 * mm, width - 38 * mm],
                style=[("BOX", (0, 0), (-1, -1), 0.6, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP")],
            )
        ]

    def signatures(size, align):
        bold, body = _style(size, "left", bold=True), _style(size, "left")
        issued = note.issued_by.full_name if note.issued_by else "Name and signature"
        width = widths["signatures"] * mm
        return [
            Table(
                [
                    [
                        [
                            _p("Issued by SML Engineers", bold),
                            Spacer(1, 12 * mm),
                            _p("..................................", body),
                            _p(issued, body),
                        ],
                        [
                            _p("Received the above goods in good order and condition", bold),
                            Spacer(1, 6 * mm),
                            _p("Name: .....................................................", body),
                            Spacer(1, 3 * mm),
                            _p("Signature: ..............................................", body),
                            Spacer(1, 3 * mm),
                            _p("Date: ........................   Company stamp", body),
                        ],
                    ]
                ],
                colWidths=[width * 0.42, width * 0.58],
                style=[
                    ("BOX", (0, 0), (-1, -1), 0.6, GRID),
                    ("LINEBEFORE", (1, 0), (1, 0), 0.4, GRID),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ],
            )
        ]

    def slogan(size, align):
        style = _style(size, align, bold=True)
        style.fontName = "Helvetica-BoldOblique"
        return [_p(SLOGAN, style)]

    return {
        "letterhead": letterhead,
        "customer": customer_block,
        "title": title,
        "refs": refs,
        "lines": lines,
        "transport": transport,
        "signatures": signatures,
        "slogan": slogan,
    }
