"""Printing a document from a saved layout (owner, 13 Nov 2026: the template designer).

A layout is a list of blocks on an A4 page, each with its place and size in millimetres,
measured from the top-left corner of the printable area (inside the 14 mm margins):

    {"key": "customer", "x": 0, "y": 34, "w": 109, "h": 34, "size": 9, "align": "left"}

One block is the items table. Blocks placed above it print on the first page where they
are put; the table starts where it is put and runs onto as many pages as it needs, with its
heading row repeated; blocks placed below it print after the end of the table, keeping
their distance from it and from each other, on a new page if they no longer fit. A block
keeps to its box: what does not fit is not printed, so the designer shows the box to size.

Blocks with a key starting "text-" hold the user's own text (e.g. "Thank you"). A document
module supplies what each of its blocks shows (`contents`).
"""

from collections.abc import Callable
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Frame, Paragraph

MARGIN_MM = 14
PAGE_W_MM = 210 - 2 * MARGIN_MM  # 182
PAGE_H_MM = 297 - 2 * MARGIN_MM  # 269
MARK_COLOUR = colors.Color(0.75, 0.1, 0.1, alpha=0.18)
ALIGN = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}

# What a block's contents function gets: the font size and alignment chosen for the block.
Contents = Callable[[float, str], list]


def text_block(text: str, size: float, align: str) -> list:
    """The user's own text: each line as typed."""
    style = ParagraphStyle(
        "own", fontName="Helvetica", fontSize=size, leading=size * 1.25, alignment=ALIGN[align]
    )
    from xml.sax.saxutils import escape

    return [Paragraph(escape(line) or "&nbsp;", style) for line in text.splitlines() or [""]]


def _frame(x_mm: float, top_mm: float, w_mm: float, h_mm: float) -> Frame:
    """A frame whose top-left corner is (x, top) in printable-area millimetres."""
    bottom = A4[1] - (MARGIN_MM + top_mm + h_mm) * mm
    return Frame(
        (MARGIN_MM + x_mm) * mm,
        bottom,
        w_mm * mm,
        h_mm * mm,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
        showBoundary=0,
    )


def _fill(frame: Frame, flows: list, canvas) -> None:
    """Put as much as fits into the frame, splitting a table between its rows; what is left
    stays in `flows` for the next page."""
    while flows:
        if frame.add(flows[0], canvas, trySplit=0):
            flows.pop(0)
            continue
        parts = frame.split(flows[0], canvas)
        if len(parts) < 2 or not frame.add(parts[0], canvas, trySplit=0):
            return
        flows[0:1] = parts[1:]


def _flowables(block: dict, contents: dict[str, Contents]) -> list:
    size = float(block.get("size") or 9)
    align = block.get("align") or "left"
    if block["key"].startswith("text-"):
        return text_block(block.get("text", ""), size, align)
    return contents[block["key"]](size, align)


def render(
    layout: dict,
    contents: dict[str, Contents],
    *,
    table: str,
    mark: str = "",
    title: str = "",
    author: str = "",
    compress: bool = True,
) -> bytes:
    blocks = [b for b in layout["blocks"] if not b.get("hidden")]
    items = next(b for b in blocks if b["key"] == table)
    before = [b for b in blocks if b is not items and b["y"] < items["y"]]
    after = sorted(
        (b for b in blocks if b is not items and b["y"] >= items["y"]), key=lambda b: b["y"]
    )
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4, pageCompression=1 if compress else 0)
    canvas.setTitle(title)
    canvas.setAuthor(author)

    def finish_page():
        if mark:
            canvas.saveState()
            canvas.setFont("Helvetica-Bold", 46)
            canvas.setFillColor(MARK_COLOUR)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(40)
            canvas.drawCentredString(0, 0, mark)
            canvas.restoreState()
        canvas.showPage()

    for block in before:
        _frame(block["x"], block["y"], block["w"], block["h"]).addFromList(
            _flowables(block, contents), canvas
        )

    # The items table: from its place on the first page, then whole pages as needed.
    rows = _flowables(items, contents)
    frame = _frame(items["x"], items["y"], items["w"], PAGE_H_MM - items["y"])
    _fill(frame, rows, canvas)
    while rows:
        finish_page()
        frame = _frame(items["x"], 0, items["w"], PAGE_H_MM)
        stuck = rows[0]
        _fill(frame, rows, canvas)
        if rows and rows[0] is stuck:  # nothing went onto a whole page: leave it out
            rows.pop(0)
    # Where the table ended, in printable-area millimetres from the top.
    end = PAGE_H_MM - (frame._y / mm - MARGIN_MM)

    if after:
        design_end = items["y"] + items["h"]
        first = min(b["y"] for b in after)
        gap = max(first - design_end, 0)
        span = max(b["y"] + b["h"] for b in after) - first
        top = end + gap
        if top + span > PAGE_H_MM:  # they keep together on a new page
            finish_page()
            top = 0
        for block in after:
            _frame(block["x"], top + block["y"] - first, block["w"], block["h"]).addFromList(
                _flowables(block, contents), canvas
            )
    finish_page()
    canvas.save()
    return buffer.getvalue()
