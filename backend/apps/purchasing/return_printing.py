"""The printed goods return note (backlog P16-12/P16-13): sent with the goods to the
supplier, signed by the stores person and by whoever takes the goods. A draft or a return
still waiting for the Director prints marked NOT YET APPROVED."""

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer

from apps.sales.document_pdf import GRID, MARGIN, MARK_COLOUR, SHADE, WIDTH, Styles, letterhead, qty
from apps.vouchers.printing import Table

from .models import SupplierReturn


def render(ret: SupplierReturn) -> bytes:
    s = Styles()
    p = s.p
    supplier = ret.supplier
    head = Table(
        [[p("GOODS RETURN NOTE", s.title)]],
        colWidths=[WIDTH],
        style=[("LEFTPADDING", (0, 0), (-1, -1), 0)],
    )
    to = [p("To:", s.small), p(supplier.name, s.bold)]
    if supplier.address:
        to.append(p(supplier.address))
    facts = Table(
        [
            [p("Return No.", s.bold), p(ret.number)],
            [p("Date", s.bold), p(f"{ret.return_date:%d-%b-%Y}")],
            [p("Our GRN", s.bold), p(ret.receipt.number)],
            [p("Your PO", s.bold), p(ret.receipt.purchase_order.label)],
            [p("Your delivery note", s.bold), p(ret.receipt.delivery_note_no or "–")],
            [p("Vehicle", s.bold), p(ret.vehicle_no or "–")],
        ],
        colWidths=[34 * mm, 50 * mm],
        style=[("LEFTPADDING", (0, 0), (-1, -1), 0)],
    )
    top = Table(
        [[to, facts]],
        colWidths=[WIDTH * 0.5, WIDTH * 0.5],
        style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)],
    )
    rows = [
        [
            p("Lot", s.head),
            p("Item", s.head),
            p("Description", s.head),
            p("Qty", s.head),
            p("UOM", s.head),
        ]
    ]
    for line in ret.lines.select_related("grn_line__item", "grn_line__po_line"):
        rows.append(
            [
                p(line.lot_no),
                p(line.grn_line.item.code),
                p(line.grn_line.po_line.description),
                p(qty(line.quantity), s.right),
                p(line.grn_line.item.unit),
            ]
        )
    lines = Table(
        rows,
        colWidths=[WIDTH * 0.24, WIDTH * 0.16, WIDTH * 0.38, WIDTH * 0.12, WIDTH * 0.10],
        repeatRows=1,
        style=[
            ("BOX", (0, 0), (-1, -1), 0.8, GRID),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, GRID),
            ("BACKGROUND", (0, 0), (-1, 0), SHADE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ],
    )
    signatures = Table(
        [
            [
                p(".............................."),
                p(".............................."),
                p(".............................."),
            ],
            [
                p("Returned by (Stores)"),
                p("Goods taken by (name, NIC)"),
                p("Received by the supplier"),
            ],
        ],
        colWidths=[WIDTH / 3] * 3,
        style=[("LEFTPADDING", (0, 0), (-1, -1), 0)],
    )
    story = letterhead(s) + [
        head,
        top,
        Spacer(1, 4 * mm),
        p(f"Reason: {ret.reason}"),
        Spacer(1, 3 * mm),
        lines,
        Spacer(1, 18 * mm),
        signatures,
    ]
    mark = "" if ret.status == SupplierReturn.Status.CONFIRMED else "NOT YET APPROVED"

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
        title=f"Goods return note {ret.number}",
    ).build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()
