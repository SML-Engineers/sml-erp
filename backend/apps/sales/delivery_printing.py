"""The printed delivery note (P2-04), in the letterhead of SML's sales documents: the
customer and delivery address, DELIVERY NOTE with our reference, the date, the order and the
customer's PO; each line with its description, drawing number, quantity ordered and
quantity delivered now (no prices); vehicle and driver; and a box for the customer to sign,
print their name, date and stamp. A draft or cancelled note carries a large mark."""

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, SimpleDocTemplate, Spacer

from apps.core.models import Company
from apps.vouchers.printing import Table

from .document_pdf import GRID, MARGIN, MARK_COLOUR, SHADE, SLOGAN, WIDTH, Styles, letterhead, qty
from .models import DeliveryNote

MARKS = {
    DeliveryNote.Status.DRAFT: "DRAFT – NOT ISSUED",
    DeliveryNote.Status.CANCELLED: "CANCELLED",
}


def render(note: DeliveryNote, *, compress: bool = True) -> bytes:
    s = Styles()
    p = s.p
    order = note.order
    customer = order.customer
    address = [p("Customer", s.small), p(customer.name, s.bold)]
    if customer.billing_address:
        address.append(p(customer.billing_address))
    if note.delivery_address:
        address += [Spacer(1, 2 * mm), p("Deliver to", s.small), p(note.delivery_address)]
    right = [
        p("DELIVERY NOTE", s.title),
        Spacer(1, 2 * mm),
        p(f"Our Ref: {note.number}", s.right),
        p(f"Date: {note.delivery_date:%d-%b-%Y}", s.right),
        p(f"Our order: {order.number}", s.right),
    ]
    if order.customer_po:
        right.append(p(f"Your PO: {order.customer_po}", s.right))
    story = letterhead(s) + [
        Table(
            [[address, right]],
            colWidths=[WIDTH * 0.6, WIDTH * 0.4],
            style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)],
        ),
        Spacer(1, 4 * mm),
    ]
    rows = [
        [
            p("No.", s.head),
            p("Description", s.head),
            p("Qty ordered", s.head),
            p("Qty delivered", s.head),
        ]
    ]
    for n, line in enumerate(note.lines.select_related("order_line"), start=1):
        ol = line.order_line
        text = ol.description + (f"\nDrawing {ol.drawing_no}" if ol.drawing_no else "")
        unit = "" if ol.unit == "pcs" else f" {ol.unit}"
        rows.append(
            [
                p(str(n)),
                p(text),
                p(qty(ol.quantity) + unit, s.right),
                p(qty(line.quantity) + unit, s.right_bold),
            ]
        )
    story.append(
        Table(
            rows,
            colWidths=[WIDTH * 0.07, WIDTH * 0.59, WIDTH * 0.17, WIDTH * 0.17],
            repeatRows=1,
            style=[
                ("BOX", (0, 0), (-1, -1), 0.8, GRID),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, GRID),
                ("LINEBEFORE", (1, 0), (-1, -1), 0.4, GRID),
                ("BACKGROUND", (0, 0), (-1, 0), SHADE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ],
        )
    )
    transport = [
        [p("Vehicle no.:", s.bold), p(note.vehicle_no or "–")],
        [p("Driver:", s.bold), p(note.driver or "–")],
    ]
    if note.notes:
        transport.append([p("Notes:", s.bold), p(note.notes)])
    story += [
        Spacer(1, 4 * mm),
        Table(
            transport,
            colWidths=[38 * mm, WIDTH - 38 * mm],
            style=[("BOX", (0, 0), (-1, -1), 0.6, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP")],
        ),
        Spacer(1, 6 * mm),
    ]
    sign = [
        [
            [
                p("Issued by SML Engineers", s.bold),
                Spacer(1, 12 * mm),
                p(".................................."),
                p(note.issued_by.full_name if note.issued_by else "Name and signature"),
            ],
            [
                p("Received the above goods in good order and condition", s.bold),
                Spacer(1, 6 * mm),
                p("Name: ....................................................."),
                Spacer(1, 3 * mm),
                p("Signature: .............................................."),
                Spacer(1, 3 * mm),
                p("Date: ........................   Company stamp"),
            ],
        ]
    ]
    story.append(
        KeepTogether(
            [
                Table(
                    sign,
                    colWidths=[WIDTH * 0.42, WIDTH * 0.58],
                    style=[
                        ("BOX", (0, 0), (-1, -1), 0.6, GRID),
                        ("LINEBEFORE", (1, 0), (1, 0), 0.4, GRID),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ],
                ),
                Spacer(1, 8 * mm),
                p(SLOGAN, s.slogan),
            ]
        )
    )
    mark = MARKS.get(note.status, "")

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

    company = Company.objects.filter(pk=1).first()
    buffer = BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"Delivery note {note.number}",
        author=company.name if company else "",
        pageCompression=1 if compress else 0,
    ).build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()
