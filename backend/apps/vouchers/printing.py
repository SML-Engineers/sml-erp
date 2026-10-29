"""The printed payment voucher (spec 4.4): company letterhead, payee and bank details,
invoice lines with account and division, tax, total in figures and words, payment details,
and who prepared, checked and approved it with dates and times from the approval log.

A4 by default, A5 on request. Reprints say "COPY"; a voucher not yet approved by the Director
says "NOT APPROVED" and a deleted one "DELETED", so neither can pass for an approved one.
"""

from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer
from reportlab.platypus import Table as _Table

from apps.core import approvals
from apps.core.models import ApprovalLog, Company
from apps.core.words import amount_in_words

from .models import Voucher, VoucherPrint


def Table(*args, **kwargs):  # noqa: N802 - reportlab's name, always aligned left here
    return _Table(*args, hAlign="LEFT", **kwargs)


APPROVED = (Voucher.Status.DIRECTOR_APPROVED, Voucher.Status.PARTLY_PAID, Voucher.Status.PAID)
GREY = colors.HexColor("#555555")
LINE = colors.HexColor("#999999")


def _when(value) -> str:
    return timezone.localtime(value).strftime("%d/%m/%Y %H:%M") if value else ""


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def signatures(voucher: Voucher) -> dict:
    """Prepared, checked and approved: the latest round of the approval log. A change sent
    back by the Director cancels the approvals before it."""
    prepared = checked = approved = None
    for row in approvals.history("voucher", voucher.pk):
        if row.action == ApprovalLog.Action.SUBMIT:
            prepared, checked, approved = row, None, None
        elif row.action == ApprovalLog.Action.SEND_DOWN:
            checked = approved = None
        elif row.action == ApprovalLog.Action.APPROVE:
            if row.level == 2:
                checked = row
            else:
                approved = row
    return {"prepared": prepared, "checked": checked, "approved": approved}


def _logo(company: Company, height: float):
    if not company.logo:
        return None
    try:
        with company.logo.open("rb") as handle:
            data = BytesIO(handle.read())
        image = Image(data)
        ratio = image.imageWidth / image.imageHeight
        image.drawHeight, image.drawWidth = height, height * ratio
        return image
    except Exception:  # noqa: BLE001 - a missing or broken logo must not stop the print
        return None


def render(voucher: Voucher, record: VoucherPrint) -> bytes:
    small = record.paper == VoucherPrint.Paper.A5
    page = A5 if small else A4
    scale = 0.78 if small else 1.0
    margin = (10 if small else 15) * mm

    def style(name, size, bold=False, **extra):
        return ParagraphStyle(
            name,
            fontName="Helvetica-Bold" if bold else "Helvetica",
            fontSize=size * scale,
            leading=size * scale * 1.25,
            **extra,
        )

    body = style("body", 9)
    muted = style("muted", 8, textColor=GREY)
    head = style("head", 15, bold=True)
    title = style("title", 13, bold=True)
    right = style("right", 9, alignment=TA_RIGHT)
    right_bold = style("right_bold", 9, bold=True, alignment=TA_RIGHT)
    bold = style("bold", 9, bold=True)

    def p(text, st=body):
        return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), st)

    company = Company.objects.filter(pk=1).first()
    story = []
    width = page[0] - 2 * margin

    # Letterhead
    lines = []
    if company:
        lines.append(p(company.name, head))
        if company.address:
            lines.append(p(company.address, muted))
        contact = " · ".join(x for x in (company.phone, company.email, company.website) if x)
        if contact:
            lines.append(p(contact, muted))
        numbers = " · ".join(
            x
            for x in (
                f"Reg. no. {company.registration_no}" if company.registration_no else "",
                f"VAT no. {company.vat_no}" if company.vat_no else "",
            )
            if x
        )
        if numbers:
            lines.append(p(numbers, muted))
    logo = _logo(company, 16 * mm * scale) if company else None
    story.append(
        Table(
            [[logo or "", lines]],
            colWidths=[(30 * mm * scale) if logo else 0.1, None],
            style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)],
        )
    )
    story.append(Spacer(1, 4 * mm * scale))

    # Title block
    vt = voucher.voucher_type
    story.append(
        Table(
            [
                [p("PAYMENT VOUCHER", title), p(f"No. {voucher.number}", right_bold)],
                [p(vt.name, bold), p(f"Date: {voucher.voucher_date:%d/%m/%Y}", right)],
                [
                    p(f"Division: {voucher.division.code} {voucher.division.name}", body),
                    p(f"Status: {voucher.get_status_display()}", right),
                ],
            ],
            colWidths=[width * 0.6, width * 0.4],
            style=[
                ("LINEBELOW", (0, -1), (-1, -1), 0.8, colors.black),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ],
        )
    )
    story.append(Spacer(1, 3 * mm * scale))

    # Payee
    rows = []
    if voucher.payee:
        rows.append([p("Pay to", bold), p(f"{voucher.payee.code} {voucher.payee.name}")])
        account = voucher.payee.bank_accounts.filter(is_active=True).order_by("-is_default").first()
        if account:
            bank = ", ".join(x for x in (account.bank_name, account.branch) if x)
            rows.append(
                [
                    p("Bank details", bold),
                    p(f"{bank} · {account.account_name} · A/C {account.account_number}"),
                ]
            )
    elif voucher.transfer_to:
        rows.append(
            [
                p("Transfer to", bold),
                p(f"{voucher.transfer_to.code} {voucher.transfer_to.name}"),
            ]
        )
    if voucher.description:
        rows.append([p("Description", bold), p(voucher.description)])
    if rows:
        story.append(
            Table(
                rows,
                colWidths=[28 * mm * scale, None],
                style=[("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")],
            )
        )
        story.append(Spacer(1, 3 * mm * scale))

    # Lines
    header = ["#", "Invoice", "Account", "Division", "Amount", "Tax", "Total"]
    table = [[p(h, bold) if i < 4 else p(h, right_bold) for i, h in enumerate(header)]]
    lines_qs = voucher.lines.select_related("account", "division").prefetch_related(
        "splits__division"
    )
    tax_total = Decimal("0")
    for line in lines_qs:
        invoice = line.invoice_no or "—"
        if line.invoice_date:
            invoice += f"\n{line.invoice_date:%d/%m/%Y}"
        if line.description:
            invoice += f"\n{line.description}"
        account = f"{line.account.number} {line.account.name}" if line.account else ""
        splits = list(line.splits.all())
        division = (
            "\n".join(f"{s.division.code} {_money(s.amount)}" for s in splits)
            if splits
            else (line.division.code if line.division else "")
        )
        tax_total += line.tax_amount
        table.append(
            [
                p(line.line_no),
                p(invoice),
                p(account),
                p(division),
                p(_money(line.amount), right),
                p(_money(line.tax_amount), right),
                p(_money(line.total), right),
            ]
        )
    table.append(
        [
            "",
            p("Total (LKR)", bold),
            "",
            "",
            "",
            p(_money(tax_total), right_bold),
            p(_money(voucher.total_amount), right_bold),
        ]
    )
    widths = [0.05, 0.21, 0.22, 0.16, 0.13, 0.10, 0.13]
    story.append(
        Table(
            table,
            colWidths=[width * w for w in widths],
            repeatRows=1,
            style=[
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
                ("LINEBELOW", (0, 1), (-1, -2), 0.25, LINE),
                ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ],
        )
    )
    story.append(Spacer(1, 2 * mm * scale))
    story.append(p(f"Amount in words: {amount_in_words(voucher.total_amount)}", bold))
    story.append(Spacer(1, 4 * mm * scale))

    # Payment details (filled in by the Cashier, P1-07)
    story.append(p("Payment details", bold))
    story.append(
        Table(
            [
                [p("Paid from (bank / cash account)"), p("Cheque no. / transfer reference")],
                [p("Cheque / payment date"), p("Amount paid")],
            ],
            colWidths=[width / 2, width / 2],
            rowHeights=[9 * mm * scale] * 2,
            style=[
                ("GRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TEXTCOLOR", (0, 0), (-1, -1), GREY),
            ],
        )
    )
    story.append(Spacer(1, 5 * mm * scale))

    # Signatures
    signed = signatures(voucher)

    def box(label, row):
        who = row.user.full_name if row else ""
        return [
            p(label, bold),
            Spacer(1, 7 * mm * scale),
            p(who),
            p(_when(row.acted_at) if row else "", muted),
        ]

    story.append(
        Table(
            [
                [
                    box("Prepared by", signed["prepared"]),
                    box("Checked by (Accountant)", signed["checked"]),
                    box("Approved by (Director)", signed["approved"]),
                    [
                        p("Received by (payee)", bold),
                        Spacer(1, 7 * mm * scale),
                        p("Name:"),
                        p("Date:", muted),
                    ],
                ]
            ],
            colWidths=[width / 4] * 4,
            style=[
                ("BOX", (0, 0), (-1, -1), 0.4, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ],
        )
    )

    marks = []
    if voucher.status == Voucher.Status.DELETED:
        marks.append("DELETED")
    elif voucher.status not in APPROVED:
        marks.append("NOT APPROVED")
    if record.is_copy:
        marks.append("COPY")
    printed = f"Printed by {record.printed_by.full_name} on {_when(record.printed_at)}"
    if record.is_copy:
        printed += " · Copy"

    def decorate(canvas, doc):
        canvas.saveState()
        if marks:
            canvas.setFont("Helvetica-Bold", 54 * scale)
            canvas.setFillColor(colors.Color(0.6, 0.6, 0.6, alpha=0.25))
            canvas.translate(page[0] / 2, page[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, " · ".join(marks))
            canvas.rotate(-35)
            canvas.translate(-page[0] / 2, -page[1] / 2)
        canvas.setFont("Helvetica", 7 * scale)
        canvas.setFillColor(GREY)
        canvas.drawString(margin, margin / 2, printed)
        canvas.drawRightString(page[0] - margin, margin / 2, f"Page {doc.page}")
        canvas.restoreState()

    out = BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=page,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=f"Payment voucher {voucher.number}",
        author=company.name if company else "",
    )
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return out.getvalue()
