"""The printed tax invoice (P2-05) in the Inland Revenue's format (Gazette 2481/22, spec 6.1),
laid out like SML's current invoice:

- logo, company name and email; TAX INVOICE in bold;
- boxes: Date of invoice / Tax Invoice No; the supplier's TIN, name, address and telephone
  next to the customer's TIN, name and address; Date of supply / Place of supply; Terms;
- the lines: Product Code, Description, PO No, Rate (Rs), Qty, Amount (Rs);
- Subtotal, the discount if any, each tax on the net amount (SSCL: code, rate, amount),
  Subtotal, each tax on net plus tax (VAT amount), Total amount including VAT;
- the total in words; signature lines for Customer, Prepared By and Checked By.

Dates are MM/DD/YYYY, amounts 115,750.00 (owner's decision). A draft carries a large DRAFT
mark and no number: it is not a tax invoice until issued."""

from decimal import Decimal
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, SimpleDocTemplate, Spacer

from apps.core.models import Company
from apps.vouchers.printing import Table, _logo

from .document_pdf import GRID, MARGIN, MARK_COLOUR, SHADE, WIDTH, Styles, money, qty
from .models import TaxInvoice


def _day(value) -> str:
    return f"{value:%m/%d/%Y}" if value else ""


def _rate(value: Decimal) -> str:
    text = f"{value.normalize():f}"
    return f"{text}%"


def render(invoice: TaxInvoice, *, compress: bool = True) -> bytes:
    s = Styles()
    p = s.p
    draft = invoice.status == TaxInvoice.Status.DRAFT
    unit = "Rs" if invoice.currency.code == "LKR" else invoice.currency.code
    company = Company.objects.filter(pk=1).first()
    supplier = {
        "name": invoice.supplier_name or (company.name if company else ""),
        "tin": invoice.supplier_tin or (company.tin if company else ""),
        "address": invoice.supplier_address or (company.address if company else ""),
        "phone": invoice.supplier_phone or (company.phone if company else ""),
        "email": invoice.supplier_email or (company.email if company else ""),
    }
    customer = invoice.customer
    buyer = {
        "name": invoice.customer_name or customer.name,
        "tin": invoice.customer_tin if not draft else customer.tin,
        "address": invoice.customer_address or customer.billing_address,
    }

    logo = _logo(company, 18 * mm) if company else None
    top = [p(supplier["name"].upper(), s.company)]
    if supplier["email"]:
        top.append(p(supplier["email"], s.centre))
    story = [
        Table(
            [[logo or "", top]],
            colWidths=[26 * mm, WIDTH - 26 * mm],
            style=[("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)],
        ),
        Spacer(1, 3 * mm),
        p("TAX INVOICE", s.title.clone("centre_title", alignment=1)),
        Spacer(1, 3 * mm),
    ]
    box = [("BOX", (0, 0), (-1, -1), 0.6, GRID), ("INNERGRID", (0, 0), (-1, -1), 0.4, GRID)]
    box += [("VALIGN", (0, 0), (-1, -1), "TOP")]
    half = [WIDTH / 2, WIDTH / 2]
    story += [
        Table(
            [
                [
                    p(f"Date of invoice: {_day(invoice.invoice_date)}", s.bold),
                    p(f"Tax Invoice No: {invoice.number or 'DRAFT'}", s.bold),
                ]
            ],
            colWidths=half,
            style=box,
        ),
        Table(
            [
                [
                    [
                        p("Supplier", s.small),
                        p(f"TIN: {supplier['tin']}", s.bold),
                        p(supplier["name"], s.bold),
                        p(supplier["address"]),
                        p(f"Telephone: {supplier['phone']}" if supplier["phone"] else ""),
                    ],
                    [
                        p("Purchaser", s.small),
                        p(f"TIN: {buyer['tin']}" if buyer["tin"] else "TIN: –", s.bold),
                        p(buyer["name"], s.bold),
                        p(buyer["address"]),
                    ],
                ]
            ],
            colWidths=half,
            style=box,
        ),
        Table(
            [
                [
                    p(f"Date of supply: {_day(invoice.supply_date)}"),
                    p(f"Place of supply: {invoice.place_of_supply}"),
                ],
                [p(f"Terms: {invoice.terms}"), p(f"Due date: {_day(invoice.due_date)}")],
            ],
            colWidths=half,
            style=box,
        ),
        Spacer(1, 4 * mm),
    ]

    widths = [0.13, 0.37, 0.13, 0.13, 0.09, 0.15]
    rows = [
        [
            p("Product Code", s.head),
            p("Description", s.head),
            p("PO No", s.head),
            p(f"Rate ({unit})", s.head),
            p("Qty", s.head),
            p(f"Amount ({unit})", s.head),
        ]
    ]
    for line in invoice.lines.all():
        unit = "" if line.unit == "pcs" else f" {line.unit}"
        rows.append(
            [
                p(line.product_code),
                p(line.description),
                p(line.po_no),
                p(money(line.rate), s.right),
                p(qty(line.quantity) + unit, s.right),
                p(money(line.amount), s.right),
            ]
        )

    def total_row(label, value, strong=False, code="", rate=""):
        style = s.right_bold if strong else s.right
        text = p(label, s.bold if strong else s.body)
        return [p(code), text, "", p(rate, s.right), "", p(value, style)]

    net = invoice.subtotal - invoice.discount_total
    rows.append(total_row("Subtotal", money(invoice.subtotal), strong=True))
    if invoice.discount_total:
        rows.append(total_row("Discount", f"-{money(invoice.discount_total)}"))
        rows.append(total_row("Subtotal after discount", money(net), strong=True))
    taxes = list(invoice.taxes.all())
    before = [t for t in taxes if not t.on_tax]
    after = [t for t in taxes if t.on_tax]
    for t in before:
        rows.append(total_row(t.label, money(t.amount), code=t.label, rate=_rate(t.rate)))
    if before:
        with_levy = net + sum((t.amount for t in before), Decimal("0"))
        rows.append(total_row("Subtotal", money(with_levy), strong=True))
    for t in after:
        rows.append(
            total_row(f"{t.label} amount", money(t.amount), code=t.label, rate=_rate(t.rate))
        )
    rows.append(total_row("Total amount including VAT", money(invoice.total_amount), strong=True))
    first_total = len(invoice.lines.all()) + 1
    story.append(
        Table(
            rows,
            colWidths=[WIDTH * w for w in widths],
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
    words = invoice.amount_in_words
    story += [Spacer(1, 3 * mm), p(f"Amount in words: {words}", s.bold)]
    if unit != "Rs":
        # An export invoice also shows its LKR value at the rate used (P2-09).
        when = f" of {invoice.rate_date:%d/%m/%Y}" if invoice.rate_date else ""
        story.append(
            p(
                f"Exchange rate{when}: 1 {unit} = LKR {invoice.exchange_rate.normalize():f}. "
                f"Total in LKR: {money(invoice.total_lkr)}",
                s.small,
            )
        )
    if invoice.notes:
        story += [Spacer(1, 2 * mm), p("Additional information", s.small), p(invoice.notes)]
    story += [Spacer(1, 14 * mm)]
    signature = [
        [p(".............................") for _ in range(3)],
        [p("Customer"), p("Prepared By"), p("Checked By")],
    ]
    story.append(KeepTogether([Table(signature, colWidths=[WIDTH / 3] * 3)]))

    def on_page(canvas, document):
        if not draft:
            return
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 46)
        canvas.setFillColor(MARK_COLOUR)
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(40)
        canvas.drawCentredString(0, 0, "DRAFT – NOT A TAX INVOICE")
        canvas.restoreState()

    buffer = BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"Tax invoice {invoice.number or 'draft'}",
        author=supplier["name"],
        pageCompression=1 if compress else 0,
    ).build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buffer.getvalue()
