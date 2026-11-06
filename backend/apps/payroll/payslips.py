"""Payslips (backlog P2B-08; owner, question 11: emailed to those with an email address,
printed on request; on the self-service page with P2B-11).

A payslip is made only from an approved payroll. It shows the company, the employee, the pay
month and its period, every earning and deduction as the payroll worked it out (with where
each came from, in short), the company's EPF 12% and ETF 3%, the net pay, the bank account it
is paid into (last four digits only) and the year-to-date figures for the year of assessment
(1 April to 31 March) from the approved payrolls up to this one.

An emailed payslip is a PDF locked with the employee's NIC number as its password, so a
mistyped address or a shared mailbox does not show anyone's pay. Every email is recorded
(SentEmail), with the PDF's fingerprint.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from django.db.models import Sum
from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core import document_email
from apps.core.document_email import EmailError
from apps.core.models import Company, User

from . import employees
from .models import PayrollItem, PayrollLine, PayrollRun

KIND = "payslip"
GREY = colors.HexColor("#555555")
LINE = colors.HexColor("#999999")
ZERO = Decimal("0.00")


class PayslipError(Exception):
    pass


def money(value) -> str:
    return f"{Decimal(value):,.2f}"


def year_start(day: date) -> date:
    """The first day of the year of assessment (1 April) that `day` falls in."""
    return date(day.year if day.month >= 4 else day.year - 1, 4, 1)


@dataclass
class YearToDate:
    gross: Decimal
    epf_employee: Decimal
    apit: Decimal
    net: Decimal
    months: int


def year_to_date(line: PayrollLine) -> YearToDate:
    run = line.run
    lines = PayrollLine.objects.filter(
        employee=line.employee,
        run__status=PayrollRun.Status.APPROVED,
        run__period_end__gte=year_start(run.period_end),
        run__period_end__lte=run.period_end,
    )
    sums = lines.aggregate(
        gross=Sum("gross"), epf=Sum("epf_employee"), apit=Sum("apit"), net=Sum("net")
    )
    out = YearToDate(
        sums["gross"] or ZERO,
        sums["epf"] or ZERO,
        sums["apit"] or ZERO,
        sums["net"] or ZERO,
        lines.count(),
    )
    # The months paid by the old payroll before the takeover (P2B-14).
    from .takeover import opening

    o = opening(line.employee, year_start(run.period_end))
    if o is not None and o.last_month < run.month:
        out.gross += o.gross
        out.epf_employee += o.epf_employee
        out.apit += o.apit
        out.net += o.net
        out.months += o.months
    return out


def _masked(account_number: str) -> str:
    digits = (account_number or "").strip()
    return f"•••• {digits[-4:]}" if digits else "—"


def _styles():
    def style(name, size, bold=False, **extra):
        return ParagraphStyle(
            name,
            fontName="Helvetica-Bold" if bold else "Helvetica",
            fontSize=size,
            leading=size * 1.25,
            **extra,
        )

    return {
        "company": style("company", 11, True),
        "small": style("small", 7, textColor=GREY),
        "title": style("title", 12, True, spaceBefore=4),
        "cell": style("cell", 7.5),
        "bold": style("bold", 7.5, True),
        "basis": style("basis", 6, textColor=GREY),
        "num": style("num", 7.5, alignment=2),
        "numbold": style("numbold", 7.5, True, alignment=2),
        "netnum": style("netnum", 12, True, alignment=2),
    }


def _story(line: PayrollLine, s: dict) -> list:
    run, e, company = line.run, line.employee, Company.get()
    ytd = year_to_date(line)
    story = [
        Paragraph(escape(company.name), s["company"]),
        Paragraph(escape(", ".join(x for x in [company.address, company.phone] if x)), s["small"]),
        Paragraph(f"PAYSLIP – {run.month:%B %Y}", s["title"]),
        Paragraph(
            f"Pay period {run.period_start:%d %B %Y} to {run.period_end:%d %B %Y} · "
            f"Payroll {escape(run.number)}",
            s["small"],
        ),
        Spacer(1, 3 * mm),
    ]
    who = [
        ["Employee", f"{e.number} {e.full_name}", "Division", run.division.code],
        ["Designation", e.designation or "—", "Category", e.get_category_display()],
        ["EPF number", e.epf_no or "—", "Paid into", _masked(e.account_number)],
    ]
    if line.days_employed < line.days_in_period:
        who.append(["Days employed", f"{line.days_employed} of {line.days_in_period}", "", ""])
    table = Table(
        [
            [
                Paragraph(escape(str(c)), s["bold" if i % 2 == 0 else "cell"])
                for i, c in enumerate(r)
            ]
            for r in who
        ],
        colWidths=[22 * mm, 45 * mm, 18 * mm, 43 * mm],
    )
    table.setStyle(
        TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)])
    )
    story += [table, Spacer(1, 3 * mm)]

    def section(title: str, kinds: tuple[str, ...], total_label: str, total) -> list:
        rows = [[Paragraph(title, s["bold"]), "", Paragraph("LKR", s["numbold"])]]
        for item in line.items.all():
            if item.kind not in kinds:
                continue
            rows.append(
                [
                    Paragraph(escape(item.name), s["cell"]),
                    Paragraph(escape(item.basis), s["basis"]),
                    Paragraph(money(item.amount), s["num"]),
                ]
            )
        rows.append([Paragraph(total_label, s["bold"]), "", Paragraph(money(total), s["numbold"])])
        t = Table(rows, colWidths=[40 * mm, 63 * mm, 25 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("SPAN", (0, 0), (1, 0)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.5, LINE),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            )
        )
        return [t, Spacer(1, 2 * mm)]

    earnings = sum((i.amount for i in line.items.all() if i.kind == "earning"), ZERO)
    taken = sum((i.amount for i in line.items.all() if i.kind == "deduction"), ZERO)
    story += section("Earnings", (PayrollItem.Kind.EARNING,), "Total earnings", earnings)
    story += section("Deductions", (PayrollItem.Kind.DEDUCTION,), "Total deductions", taken)
    net = Table(
        [[Paragraph("NET PAY", s["title"]), Paragraph(f"LKR {money(line.net)}", s["netnum"])]],
        colWidths=[70 * mm, 58 * mm],
    )
    net.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
            ]
        )
    )
    story += [net, Spacer(1, 2 * mm)]
    story += section(
        "Paid by the company (not deducted)",
        (PayrollItem.Kind.EMPLOYER,),
        "Total",
        line.epf_employer + line.etf,
    )
    year = year_start(run.period_end)
    ytd_rows = [
        [
            Paragraph(
                f"Year to date ({year:%B %Y} – {run.month:%B %Y}, {ytd.months} month"
                f"{'s' if ytd.months != 1 else ''})",
                s["bold"],
            ),
            "",
        ],
        [Paragraph("Earnings", s["cell"]), Paragraph(money(ytd.gross), s["num"])],
        [Paragraph("EPF 8%", s["cell"]), Paragraph(money(ytd.epf_employee), s["num"])],
        [Paragraph("APIT", s["cell"]), Paragraph(money(ytd.apit), s["num"])],
        [Paragraph("Net pay", s["cell"]), Paragraph(money(ytd.net), s["num"])],
    ]
    t = Table(ytd_rows, colWidths=[103 * mm, 25 * mm])
    t.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("SPAN", (0, 0), (1, 0)),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    story += [
        t,
        Spacer(1, 3 * mm),
        Paragraph(
            "Computer-generated payslip from the approved payroll; no signature needed. "
            "Questions: HR.",
            s["small"],
        ),
    ]
    return story


def render(lines: list[PayrollLine], password: str = "") -> bytes:
    """One PDF with a page per payslip; locked with `password` when given."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A5,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title="Payslip",
        author=Company.get().name,
        encrypt=StandardEncryption(password, canPrint=1, canModify=0, canCopy=0)
        if password
        else None,
    )
    story = []
    for i, line in enumerate(lines):
        if i:
            story.append(PageBreak())
        story += _story(line, _styles())
    doc.build(story)
    return buffer.getvalue()


def _approved(run: PayrollRun) -> None:
    if run.status != PayrollRun.Status.APPROVED:
        raise PayslipError("Payslips are made once the Director has approved the payroll.")


def lines_of(user: User, run: PayrollRun):
    """The lines of the payroll the user may see payslips for (HR and the Director)."""
    if not employees.can_view(user):
        raise PayslipError("Only HR and the Director see payslips.")
    _approved(run)
    return (
        run.lines.filter(employee__in=employees.visible(user))
        .select_related("employee", "run__division")
        .prefetch_related("items")
    )


def filename(line: PayrollLine) -> str:
    return f"payslip-{line.run.month:%Y-%m}-{line.employee.number}.pdf"


def email(user: User, run: PayrollRun, employee_ids=None) -> dict:
    """Email the payslips of an approved payroll to every employee with an email address (or
    to the employees given), each locked with the employee's NIC number."""
    if not employees.can_edit(user):
        raise PayslipError("Only HR emails payslips.")
    lines = lines_of(user, run)
    if employee_ids:
        lines = lines.filter(employee_id__in=employee_ids)
    sent, failed, skipped = [], [], []
    for line in lines:
        e = line.employee
        if not e.email:
            skipped.append(e.number)
            continue
        values = {
            "recipient_name": e.full_name,
            "pay_month": f"{run.month:%B %Y}",
            "period": f"{run.period_start:%d %B} to {run.period_end:%d %B %Y}",
            "net_pay": money(line.net),
        }
        try:
            message = document_email.draft(user, KIND, values, to=[e.email])
            record = document_email.send(
                user,
                kind=KIND,
                label=f"Payslip {run.month:%B %Y} {e.number}",
                to=message["to"],
                subject=message["subject"],
                body=message["body"],
                document_id=line.pk,
                attachment=(filename(line), render([line], e.nic), "application/pdf"),
                keep_copy=False,
            )
        except EmailError as error:
            raise PayslipError(str(error)) from None
        (sent if record.status == record.Status.SENT else failed).append(e.number)
    return {"sent": sent, "failed": failed, "no_email": skipped}
