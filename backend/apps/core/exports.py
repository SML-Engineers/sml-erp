"""Exporting any list or report to Excel or PDF (spec 4.4, backlog P1-08).

A report is a title, a line saying which filters were used, columns and rows. The same rows
give the screen, the Excel sheet and the PDF, so they always agree. Money columns are real
numbers in Excel (with thousands separators) and are totalled at the foot.
"""

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from xml.sax.saxutils import escape

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

FORMATS = ("xlsx", "pdf")
STRONG = "_strong"  # a row key: print the row in bold
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass(frozen=True)
class Column:
    key: str
    title: str
    kind: str = "text"  # text, money, date, datetime, number
    width: float = 1.0  # relative width in the PDF


def _value(value, kind: str):
    if value in (None, ""):
        return None
    if kind == "money":
        return Decimal(str(value))
    if kind == "datetime" and isinstance(value, datetime):
        return timezone.localtime(value).replace(tzinfo=None)
    return value


def _text(value, kind: str) -> str:
    value = _value(value, kind)
    if value is None:
        return ""
    if kind == "money":
        return f"{value:,.2f}"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _totals(columns: list[Column], rows: list[dict]) -> dict:
    return {
        c.key: sum((_value(r.get(c.key), "money") or Decimal("0") for r in rows), Decimal("0"))
        for c in columns
        if c.kind == "money"
    }


def xlsx(
    title: str, subtitle: str, columns: list[Column], rows: list[dict], totals: bool = True
) -> bytes:
    book = Workbook()
    sheet = book.active
    # Excel refuses some characters in a sheet name (e.g. "Open sales orders: deliveries").
    sheet.title = re.sub(r"[\\/*?:\[\]]", "", title)[:31] or "Report"
    sheet.append([title])
    sheet["A1"].font = Font(bold=True, size=13)
    sheet.append([subtitle])
    sheet.append([])
    sheet.append([c.title for c in columns])
    for cell in sheet[4]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append([_value(row.get(c.key), c.kind) for c in columns])
        if row.get(STRONG):
            for cell in sheet[sheet.max_row]:
                cell.font = Font(bold=True)
    sums = _totals(columns, rows) if totals else {}
    if sums and rows:
        foot = [sums.get(c.key, "Total" if i == 0 else None) for i, c in enumerate(columns)]
        sheet.append(foot)
        for cell in sheet[sheet.max_row]:
            cell.font = Font(bold=True)
    for index, column in enumerate(columns, start=1):
        letter = get_column_letter(index)
        formats = {
            "money": "#,##0.00",
            "date": "dd/mm/yyyy",
            "datetime": "dd/mm/yyyy hh:mm",
        }
        if column.kind in formats:
            for cell in sheet[letter][4:]:
                cell.number_format = formats[column.kind]
        sheet.column_dimensions[letter].width = max(12, min(45, 14 * column.width))
    sheet.freeze_panes = "A5"
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def pdf(
    title: str,
    subtitle: str,
    columns: list[Column],
    rows: list[dict],
    printed_by: str,
    totals: bool = True,
):
    page = landscape(A4)
    margin = 12 * mm
    width = page[0] - 2 * margin
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=7.5, leading=9.5)
    bold = ParagraphStyle("bold", parent=body, fontName="Helvetica-Bold")
    right = ParagraphStyle("right", parent=body, alignment=TA_RIGHT)
    right_bold = ParagraphStyle("right_bold", parent=bold, alignment=TA_RIGHT)
    head = ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=13, leading=16)
    muted = ParagraphStyle("muted", parent=body, textColor=colors.HexColor("#555555"))

    def cell(text, column, strong=False):
        if column.kind == "money":
            style = right_bold if strong else right
        else:
            style = bold if strong else body
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    data = [[cell(c.title, c, strong=True) for c in columns]]
    for row in rows:
        strong = bool(row.get(STRONG))
        data.append([cell(_text(row.get(c.key), c.kind), c, strong) for c in columns])
    sums = _totals(columns, rows) if totals else {}
    if sums and rows:
        data.append(
            [
                cell(
                    f"{sums[c.key]:,.2f}" if c.key in sums else ("Total" if i == 0 else ""),
                    c,
                    True,
                )
                for i, c in enumerate(columns)
            ]
        )
    whole = sum(c.width for c in columns)
    table = Table(
        data,
        colWidths=[width * c.width / whole for c in columns],
        repeatRows=1,
        hAlign="LEFT",
        style=[
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
            ("LINEBELOW", (0, 1), (-1, -1), 0.2, colors.HexColor("#cccccc")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ],
    )
    from .models import Company

    company = Company.objects.filter(pk=1).first()
    story = [
        Paragraph(escape(company.name if company else ""), muted),
        Paragraph(escape(title), head),
        Paragraph(escape(subtitle), muted),
        Spacer(1, 4 * mm),
        table if rows else Paragraph("Nothing to show.", body),
    ]
    stamp = f"Printed by {printed_by} on {timezone.localtime():%d/%m/%Y %H:%M}"

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(margin, margin / 2, stamp)
        canvas.drawRightString(page[0] - margin, margin / 2, f"Page {doc.page}")
        canvas.restoreState()

    out = io.BytesIO()
    SimpleDocTemplate(
        out,
        pagesize=page,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=title,
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()


def response(
    fmt: str, *, title, subtitle, columns, rows, filename, user, totals: bool = True
) -> HttpResponse:
    """The report as a download: fmt is "xlsx" or "pdf". Rows with STRONG set print in bold
    (subtotals); totals=False leaves out the summed foot line (e.g. a balance sheet)."""
    if fmt == "xlsx":
        content, kind = xlsx(title, subtitle, columns, rows, totals), XLSX
    else:
        content = pdf(title, subtitle, columns, rows, user.full_name, totals)
        kind = "application/pdf"
    reply = HttpResponse(content, content_type=kind)
    reply["Content-Disposition"] = f'attachment; filename="{filename}.{fmt}"'
    return reply
