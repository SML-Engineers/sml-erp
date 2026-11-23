"""Report downloads (apps.core.exports): figures are numbers in Excel (testing T32)."""

import io
from decimal import Decimal

from openpyxl import load_workbook

from apps.core.exports import Column, _text, xlsx

COLUMNS = [
    Column("item", "Item"),
    Column("quantity", "Quantity", "number"),
    Column("value", "Value (LKR)", "money"),
]
ROWS = [
    {"item": "PP-H-25", "quantity": "1403.000", "value": "589260.00"},
    {"item": "M8-INSERT", "quantity": "4800.500", "value": "60000.00"},
    {"item": "Odd", "quantity": "50 kg", "value": ""},
]


def test_quantities_are_numbers_in_excel_so_they_can_be_added_up():
    book = load_workbook(io.BytesIO(xlsx("Stock on hand", "21/11/2026", COLUMNS, ROWS)))
    sheet = book.active
    first, second, odd = (sheet.cell(row=r, column=2) for r in (5, 6, 7))
    assert first.value == 1403 and first.data_type == "n"
    assert second.value == Decimal("4800.5") or second.value == 4800.5
    assert first.number_format == "#,##0.###"
    # Something that is not a figure stays as written rather than being lost.
    assert odd.value == "50 kg"
    assert sheet.cell(row=5, column=3).data_type == "n"


def test_the_pdf_shows_quantities_as_the_screen_does():
    assert _text("1403.000", "number") == "1,403"
    assert _text("4800.500", "number") == "4,800.5"
    assert _text("0.000", "number") == "0"
    assert _text("50 kg", "number") == "50 kg"
    assert _text("", "number") == ""
