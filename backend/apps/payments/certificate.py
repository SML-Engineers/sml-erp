"""The withholding tax certificate given to a payee (backlog P2-12): who kept the tax and who it
was kept from (names and TINs), the payment, the gross amount, the rate, the tax kept and what
was paid. One per payment with WHT, numbered from its own series. A cancelled payment's
certificate says it is not valid.
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

from .models import SupplierPayment

GREY = colors.HexColor("#555555")
LINE = colors.HexColor("#999999")


def rows(payment: SupplierPayment) -> list[list[str]]:
    voucher = payment.voucher
    payee = voucher.payee
    gross = payment.amount
    lines = [line for line in voucher.lines.select_related("wht_component") if line.wht_amount > 0]
    taxes = sorted({f"{line.wht_component.label} {line.wht_rate.normalize():f}%" for line in lines})
    invoices = ", ".join(line.invoice_no for line in lines if line.invoice_no)
    paid_by = " ".join(x for x in (payment.get_method_display(), payment.reference) if x)
    found = [
        [
            "Certificate no.",
            payment.wht_certificate,
            "Date",
            payment.payment_date.strftime("%d/%m/%Y"),
        ],
        [
            "Tax kept from",
            f"{payee.name} ({payee.code})" if payee else "",
            "TIN",
            payee.tin if payee else "",
        ],
        ["Tax", ", ".join(taxes), "", ""],
        ["Payment", f"{payment.number} for voucher {voucher.number}", "", ""],
    ]
    if invoices:
        found.append(["Invoices", invoices, "", ""])
    found += [
        ["Gross amount", f"LKR {gross:,.2f}", "", ""],
        ["Tax kept", f"LKR {payment.wht_amount:,.2f}", "", ""],
        ["In words", amount_in_words(payment.wht_amount, "LKR"), "", ""],
        ["Paid to payee", f"LKR {payment.paid_amount:,.2f} ({paid_by})", "", ""],
    ]
    return found


def render(payment: SupplierPayment) -> bytes:
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
    heading = []
    if company:
        heading.append(p(company.name, head))
        if company.address:
            heading.append(p(company.address, muted))
        if company.tin:
            heading.append(p(f"TIN {company.tin}", muted))
    logo = _logo(company, 14 * mm) if company else None
    story.append(
        Table(
            [[logo or "", heading]],
            colWidths=[26 * mm if logo else 0.1, None],
            style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)],
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(p("WITHHOLDING TAX CERTIFICATE", title))
    if payment.cancelled:
        story.append(p("PAYMENT CANCELLED – NOT VALID", warn))
    story.append(Spacer(1, 2 * mm))
    found = rows(payment)
    story.append(
        Table(
            [[p(a, muted), p(b), p(c, muted), p(d)] for a, b, c, d in found],
            colWidths=[28 * mm, 92 * mm, 16 * mm, None],
            style=[
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
            + [("SPAN", (1, i), (3, i)) for i, row in enumerate(found) if not (row[2] or row[3])],
        )
    )
    story.append(Spacer(1, 10 * mm))
    story.append(
        Table(
            [
                [
                    p(f"Prepared by: {payment.created_by.full_name}", muted),
                    p("Signature: ______", muted),
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
        title=f"WHT certificate {payment.wht_certificate}",
    ).build(story)
    return buffer.getvalue()
