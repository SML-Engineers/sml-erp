"""The printed credit note (P2-06): the supplier's and customer's TIN, name and address as on
the original tax invoice, the credit note's number and date, the invoice it corrects (number
and date) and why; the lines credited (product code, description, quantity returned, amount);
the taxes on them as on the invoice (SSCL, subtotal, VAT) and the total credited, in figures
and words; signature lines. Dates MM/DD/YYYY, as on the tax invoice. A note not yet approved
carries a large DRAFT mark and no number."""

from decimal import Decimal
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, SimpleDocTemplate, Spacer

from apps.vouchers.printing import Table

from .document_pdf import GRID, MARGIN, MARK_COLOUR, SHADE, WIDTH, Styles, letterhead, money, qty
from .models import CreditNote


def _day(value) -> str:
    return f"{value:%m/%d/%Y}" if value else ""


def render(note: CreditNote, *, compress: bool = True) -> bytes:
    s = Styles()
    p = s.p
    invoice = note.invoice
    unit = "Rs" if invoice.currency.code == "LKR" else invoice.currency.code
    approved = note.status == CreditNote.Status.APPROVED
    story = letterhead(s) + [
        p("CREDIT NOTE", s.title.clone("centre_title", alignment=1)),
        Spacer(1, 3 * mm),
    ]
    box = [
        ("BOX", (0, 0), (-1, -1), 0.6, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    half = [WIDTH / 2, WIDTH / 2]
    story += [
        Table(
            [
                [
                    p(f"Credit note No: {note.number or 'DRAFT'}", s.bold),
                    p(f"Date: {_day(note.credit_date)}", s.bold),
                ],
                [
                    p(f"Original tax invoice No: {invoice.number}"),
                    p(f"Invoice date: {_day(invoice.invoice_date)}"),
                ],
            ],
            colWidths=half,
            style=box,
        ),
        Table(
            [
                [
                    [
                        p("Supplier", s.small),
                        p(f"TIN: {invoice.supplier_tin}", s.bold),
                        p(invoice.supplier_name, s.bold),
                        p(invoice.supplier_address),
                    ],
                    [
                        p("Purchaser", s.small),
                        p(f"TIN: {invoice.customer_tin or '–'}", s.bold),
                        p(invoice.customer_name, s.bold),
                        p(invoice.customer_address),
                    ],
                ]
            ],
            colWidths=half,
            style=box,
        ),
        Table(
            [[p(f"Reason: {note.get_kind_display()} – {note.reason}")]],
            colWidths=[WIDTH],
            style=box,
        ),
        Spacer(1, 4 * mm),
    ]
    rows = [
        [
            p("Product Code", s.head),
            p("Description", s.head),
            p("Qty", s.head),
            p(f"Amount ({unit})", s.head),
        ]
    ]
    for line in note.lines.select_related("invoice_line"):
        il = line.invoice_line
        unit = "" if il.unit == "pcs" else f" {il.unit}"
        rows.append(
            [
                p(il.product_code),
                p(il.description),
                p(qty(line.quantity) + unit if line.quantity else "", s.right),
                p(money(line.amount), s.right),
            ]
        )
    first_total = len(rows)

    def total(label, value, strong=False):
        return [
            "",
            p(label, s.bold if strong else s.body),
            "",
            p(value, s.right_bold if strong else s.right),
        ]

    rows.append(total("Subtotal", money(note.subtotal), True))
    taxes = list(note.taxes.all())
    before = [t for t in taxes if not t.on_tax]
    for t in before:
        rows.append(total(f"{t.label} {t.rate.normalize():f}%", money(t.amount)))
    if before:
        rows.append(
            total(
                "Subtotal",
                money(note.subtotal + sum((t.amount for t in before), Decimal("0"))),
                True,
            )
        )
    for t in taxes:
        if t.on_tax:
            rows.append(total(f"{t.label} {t.rate.normalize():f}%", money(t.amount)))
    rows.append(total("Total credited", money(note.total_amount), True))
    story.append(
        Table(
            rows,
            colWidths=[WIDTH * 0.15, WIDTH * 0.55, WIDTH * 0.12, WIDTH * 0.18],
            repeatRows=1,
            style=[
                ("BOX", (0, 0), (-1, -1), 0.8, GRID),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, GRID),
                ("LINEBEFORE", (1, 0), (-1, first_total - 1), 0.4, GRID),
                ("LINEABOVE", (0, first_total), (-1, first_total), 0.8, GRID),
                ("BACKGROUND", (0, 0), (-1, 0), SHADE),
                ("BACKGROUND", (0, len(rows) - 1), (-1, len(rows) - 1), SHADE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ],
        )
    )
    story += [
        Spacer(1, 3 * mm),
        p(f"Amount in words: {note.amount_in_words}", s.bold),
        Spacer(1, 14 * mm),
        KeepTogether(
            [
                Table(
                    [
                        [p(".............................") for _ in range(3)],
                        [p("Customer"), p("Prepared By"), p("Approved By")],
                    ],
                    colWidths=[WIDTH / 3] * 3,
                )
            ]
        ),
    ]

    def on_page(canvas, document):
        if approved:
            return
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 46)
        canvas.setFillColor(MARK_COLOUR)
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(40)
        canvas.drawCentredString(0, 0, "DRAFT – NOT APPROVED")
        canvas.restoreState()

    buffer = BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"Credit note {note.number or 'draft'}",
        author=invoice.supplier_name,
        pageCompression=1 if compress else 0,
    ).build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()
