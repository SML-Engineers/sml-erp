"""Statutory returns from the approved payrolls (backlog P2B-09).

Each return is a table built from the **approved** payrolls only, for the whole company (the
EPF and ETF employer numbers are the company's), shown on the page and downloaded as Excel or
PDF for the paper or online form:

- **EPF monthly return (C form)**, per pay month: each member's name, NIC, EPF number, total
  earnings, the employee's 8%, the employer's 12% and the total. Paid by the last working day
  of the following month (late payment carries a surcharge).
- **ETF monthly contributions**, per pay month: each member's earnings and the employer's 3%.
- **ETF half-year return**: each member's ETF for each month of January–June or July–December
  and the total.
- **APIT monthly schedule**, per pay month: each employee's taxable earnings and APIT
  deducted, and the IRD table used.
- **APIT for the year of assessment** (1 April – 31 March): each employee's taxable earnings
  and APIT deducted, the figures for the year-end certificate; the certificates themselves as
  one PDF (a page each).

A pay month is named by the month it ends in (P2B-15): October 2026 = 21 September – 20
October, paid on 31 October. A division whose payroll for the month is not yet approved is
named in the return's notes, so a return is never filed short without anyone knowing.

The electronic upload files (the EPF e-return text file, the ETF file) need the official
layouts from the EPF and ETF departments; they come when those are in hand.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core.models import Company, User

from . import employees, periods
from .models import PayrollItem, PayrollLine, PayrollRun

ZERO = Decimal("0.00")
KINDS = ("epf", "etf", "apit")


class ReturnError(Exception):
    pass


@dataclass
class Report:
    title: str
    lines: list[str]  # under the title: employer numbers, period
    columns: list[str]
    rows: list[list] = field(default_factory=list)
    totals: list = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    money_from: int = 0  # the first column holding money

    def as_dict(self) -> dict:
        def cell(v):
            return f"{v:.2f}" if isinstance(v, Decimal) else v

        return {
            "title": self.title,
            "lines": self.lines,
            "columns": self.columns,
            "rows": [[cell(v) for v in r] for r in self.rows],
            "totals": [cell(v) for v in self.totals],
            "notes": self.notes,
            "money_from": self.money_from,
        }


def _check(user: User) -> None:
    if not employees.can_view(user):
        raise ReturnError("Only HR and the Director see the statutory returns.")


def _month(value) -> date:
    try:
        return date.fromisoformat(f"{str(value or '')[:7]}-01")
    except ValueError:
        raise ReturnError("Choose a pay month, for example 2026-10.") from None


def _lines(user: User, months: list[date]) -> tuple[list[PayrollLine], list[str]]:
    """The lines of the approved payrolls for these pay months, and notes on divisions whose
    payroll is not approved."""
    runs = PayrollRun.objects.filter(month__in=months, status=PayrollRun.Status.APPROVED)
    notes = []
    for month in months:
        done = set(runs.filter(month=month).values_list("division_id", flat=True))
        employed = (
            PayrollRun.objects.filter(month=month)
            .exclude(status=PayrollRun.Status.REJECTED)
            .values_list("division__code", "division_id", "status")
        )
        waiting = sorted({code for code, pk, status in employed if pk not in done})
        if waiting:
            notes.append(
                f"Pay month {month:%B %Y}: the payroll of {', '.join(waiting)} is not approved "
                "yet, so it is not included."
            )
        if not done and not waiting:
            notes.append(f"Pay month {month:%B %Y}: no approved payroll.")
    lines = list(
        PayrollLine.objects.filter(run__in=runs, employee__in=employees.visible(user))
        .select_related("employee", "run")
        .order_by("employee__number", "run__month")
    )
    return lines, notes


def _name(e) -> str:
    return e.name_with_initials or e.full_name


def _company_lines(*numbers: str) -> list[str]:
    company = Company.get()
    out = [company.name]
    for label, value in numbers:
        out.append(f"{label}: {value or 'not entered (Settings → Company)'}")
    return out


def epf(user: User, month) -> Report:
    _check(user)
    month = _month(month)
    start, end = periods.pay_period(month)
    lines, notes = _lines(user, [month])
    company = Company.get()
    r = Report(
        title=f"EPF monthly return (C form) – {month:%B %Y}",
        lines=_company_lines(("EPF employer no.", company.epf_employer_no))
        + [f"Pay period {start:%d %B} – {end:%d %B %Y}"],
        columns=[
            "Employee no.",
            "Name",
            "NIC",
            "EPF member no.",
            "Total earnings",
            "Employee 8%",
            "Employer 12%",
            "Total",
        ],
        money_from=4,
        notes=notes,
    )
    sums = [ZERO] * 4
    for x in lines:
        if not x.epf_earnings:
            continue
        values = [x.epf_earnings, x.epf_employee, x.epf_employer, x.epf_employee + x.epf_employer]
        r.rows.append(
            [x.employee.number, _name(x.employee), x.employee.nic, x.employee.epf_no] + values
        )
        sums = [a + b for a, b in zip(sums, values, strict=True)]
        if not x.employee.epf_no:
            r.notes.append(f"{x.employee.number} has no EPF member number.")
    r.totals = ["", f"{len(r.rows)} members", "", ""] + sums
    r.notes.append(
        "Pay the total by the last working day of the following month; late payment carries "
        "a surcharge."
    )
    return r


def etf(user: User, month) -> Report:
    _check(user)
    month = _month(month)
    start, end = periods.pay_period(month)
    lines, notes = _lines(user, [month])
    company = Company.get()
    r = Report(
        title=f"ETF monthly contributions – {month:%B %Y}",
        lines=_company_lines(("ETF employer no.", company.etf_employer_no))
        + [f"Pay period {start:%d %B} – {end:%d %B %Y}"],
        columns=["Employee no.", "Name", "NIC", "Member no.", "Total earnings", "ETF 3%"],
        money_from=4,
        notes=notes,
    )
    sums = [ZERO, ZERO]
    for x in lines:
        if not x.etf:
            continue
        r.rows.append(
            [
                x.employee.number,
                _name(x.employee),
                x.employee.nic,
                x.employee.epf_no,
                x.epf_earnings,
                x.etf,
            ]
        )
        sums = [sums[0] + x.epf_earnings, sums[1] + x.etf]
    r.totals = ["", f"{len(r.rows)} members", "", ""] + sums
    return r


def etf_half_year(user: User, year, half) -> Report:
    _check(user)
    try:
        year, half = int(year), int(half)
    except (TypeError, ValueError):
        raise ReturnError(
            "Choose the year and the half (1: January–June, 2: July–December)."
        ) from None
    if half not in (1, 2):
        raise ReturnError("Choose the half: 1 (January–June) or 2 (July–December).")
    months = [date(year, m, 1) for m in range(1 if half == 1 else 7, 7 if half == 1 else 13)]
    lines, notes = _lines(user, months)
    company = Company.get()
    r = Report(
        title=f"ETF half-year return – {months[0]:%B} to {months[-1]:%B %Y}",
        lines=_company_lines(("ETF employer no.", company.etf_employer_no)),
        columns=["Employee no.", "Name", "NIC", "Member no."]
        + [f"{m:%b}" for m in months]
        + ["Total"],
        money_from=4,
        notes=notes,
    )
    people: dict[int, list] = {}
    for x in lines:
        row = people.setdefault(
            x.employee_id,
            [x.employee.number, _name(x.employee), x.employee.nic, x.employee.epf_no] + [ZERO] * 7,
        )
        row[4 + months.index(x.run.month)] += x.etf
        row[-1] += x.etf
    r.rows = [row for row in people.values() if row[-1]]
    r.totals = ["", f"{len(r.rows)} members", "", ""] + [
        sum((row[i] for row in r.rows), ZERO) for i in range(4, 11)
    ]
    return r


def _apit_table(line: PayrollLine) -> str:
    item = PayrollItem.objects.filter(line=line, code="APIT").first()
    return item.basis.split("(", 1)[-1].rstrip(")") if item and "(" in item.basis else ""


def apit(user: User, month) -> Report:
    _check(user)
    month = _month(month)
    start, end = periods.pay_period(month)
    lines, notes = _lines(user, [month])
    company = Company.get()
    r = Report(
        title=f"APIT monthly schedule – {month:%B %Y}",
        lines=_company_lines(("TIN", company.tin)) + [f"Pay period {start:%d %B} – {end:%d %B %Y}"],
        columns=["Employee no.", "Name", "NIC", "Table", "Taxable earnings", "APIT deducted"],
        money_from=4,
        notes=notes,
    )
    sums = [ZERO, ZERO]
    for x in lines:
        r.rows.append(
            [
                x.employee.number,
                _name(x.employee),
                x.employee.nic,
                _apit_table(x),
                x.apit_earnings,
                x.apit,
            ]
        )
        sums = [sums[0] + x.apit_earnings, sums[1] + x.apit]
    r.totals = ["", f"{len(r.rows)} employees", "", ""] + sums
    r.notes.append("APIT deducted is paid to the IRD by the 15th of the following month.")
    return r


def _year_months(year) -> list[date]:
    try:
        year = int(year)
    except (TypeError, ValueError):
        raise ReturnError("Choose the year of assessment, for example 2026 for 2026/27.") from None
    return [date(year, m, 1) for m in range(4, 13)] + [date(year + 1, m, 1) for m in range(1, 4)]


def apit_year(user: User, year) -> Report:
    """The year of assessment from 1 April: by pay month (April to March)."""
    _check(user)
    months = _year_months(year)
    lines, notes = _lines(user, months)
    company = Company.get()
    first, last = months[0], months[-1]
    r = Report(
        title=f"APIT for the year of assessment {first.year}/{str(last.year)[2:]}",
        lines=_company_lines(("TIN", company.tin)) + [f"Pay months {first:%B %Y} – {last:%B %Y}"],
        columns=["Employee no.", "Name", "NIC", "Months", "Taxable earnings", "APIT deducted"],
        money_from=4,
        notes=[n for n in notes if "no approved payroll" not in n],
    )
    people: dict[int, list] = {}
    for x in lines:
        row = people.setdefault(
            x.employee_id, [x.employee.number, _name(x.employee), x.employee.nic, 0, ZERO, ZERO]
        )
        row[3] += 1
        row[4] += x.apit_earnings
        row[5] += x.apit
    r.rows = list(people.values())
    r.totals = ["", f"{len(r.rows)} employees", "", ""] + [
        sum((row[i] for row in r.rows), ZERO) for i in (4, 5)
    ]
    return r


# --- Files --------------------------------------------------------------------------------------


def xlsx(report: Report) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Return"
    sheet.append([report.title])
    sheet["A1"].font = Font(bold=True, size=13)
    for line in report.lines:
        sheet.append([line])
    sheet.append([])
    sheet.append(report.columns)
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)
    for row in report.rows:
        sheet.append(row)
    sheet.append(report.totals)
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)
    for row in sheet.iter_rows(min_row=1, max_row=sheet.max_row):
        for cell in row[report.money_from :]:
            if isinstance(cell.value, Decimal):
                cell.number_format = "#,##0.00"
    for note in report.notes:
        sheet.append([note])
    for column in "ABCDEFGHIJKL":
        sheet.column_dimensions[column].width = 16
    sheet.column_dimensions["B"].width = 30
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def _style(name, size, bold=False, **extra):
    return ParagraphStyle(
        name,
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size,
        leading=size * 1.25,
        **extra,
    )


def _report_story(report: Report) -> list:
    title, small, cell = _style("t", 12, True), _style("s", 8), _style("c", 7)
    num, bold_num = _style("n", 7, alignment=2), _style("bn", 7, True, alignment=2)
    head = _style("h", 7, True)

    def show(v, total=False):
        if isinstance(v, Decimal):
            return Paragraph(f"{v:,.2f}", bold_num if total else num)
        return Paragraph(escape(str(v)), head if total else cell)

    story = [Paragraph(escape(report.title), title)]
    story += [Paragraph(escape(line), small) for line in report.lines]
    story.append(Spacer(1, 3 * mm))
    data = [[Paragraph(escape(c), head) for c in report.columns]]
    data += [[show(v) for v in row] for row in report.rows]
    data.append([show(v, True) for v in report.totals])
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
                ("LINEABOVE", (0, -1), (-1, -1), 0.6, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F2F2F2")]),
            ]
        )
    )
    story += [table, Spacer(1, 3 * mm)]
    story += [Paragraph(escape(n), small) for n in report.notes]
    return story


def pdf(report: Report) -> bytes:
    out = BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=report.title,
    )
    doc.build(_report_story(report))
    return out.getvalue()


def certificates(user: User, year, number=None) -> bytes:
    """The year-end APIT certificates (one page per employee) from the year's figures."""
    report = apit_year(user, year)
    if number:
        report.rows = [r for r in report.rows if str(r[0]) == str(number).upper()]
    if not report.rows:
        raise ReturnError("There is nobody with an approved payroll in that year.")
    company = Company.get()
    title, small, cell = _style("t", 13, True), _style("s", 8), _style("c", 9)
    story = []
    for i, row in enumerate(report.rows):
        if i:
            story.append(PageBreak())
        number, name, nic, months, earnings, tax = row
        story += [
            Paragraph(escape(company.name), _style("co", 11, True)),
            Paragraph(escape(company.address or ""), small),
            Paragraph(f"Employer TIN: {escape(company.tin or 'not entered')}", small),
            Spacer(1, 4 * mm),
            Paragraph("Certificate of income tax deducted from employment income (APIT)", title),
            Paragraph(escape(report.title.replace("APIT for the ", "For the ")), cell),
            Spacer(1, 4 * mm),
        ]
        t = Table(
            [
                [Paragraph("Employee", cell), Paragraph(escape(f"{number} {name}"), cell)],
                [Paragraph("NIC", cell), Paragraph(escape(nic), cell)],
                [Paragraph("Months paid", cell), Paragraph(str(months), cell)],
                [Paragraph("Employment income", cell), Paragraph(f"LKR {earnings:,.2f}", cell)],
                [Paragraph("Tax deducted (APIT)", cell), Paragraph(f"LKR {tax:,.2f}", cell)],
            ],
            colWidths=[55 * mm, 110 * mm],
        )
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey)]))
        story += [
            t,
            Spacer(1, 6 * mm),
            Paragraph(
                "The figures are from the approved payrolls of the year. Check them against "
                "the IRD's current certificate form before issuing.",
                small,
            ),
            Spacer(1, 14 * mm),
            Paragraph("..............................................  Signature and date", cell),
        ]
    out = BytesIO()
    SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="APIT certificates",
    ).build(story)
    return out.getvalue()
