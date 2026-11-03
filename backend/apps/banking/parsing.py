"""Reading bank statement files (backlog P2-15). Pure functions: no database.

A template says how a bank's file is laid out. For a spreadsheet (Excel or CSV) it names the
column headings: the date, the description, a reference, money out and money in (or one
signed amount), and the balance. For a PDF whose text can be read (such as the Commercial
Bank statement, made by JasperReports) each line starting with a date is a transaction: the
amounts at its end are money out and money in (or one amount) and the balance, with "Cr" or
"Dr"; lines without a date continue the description above.

When the file gives only one amount and the balance, the direction is worked out from the
balance: up is money in, down is money out. Every line's balance is then checked against the
one before, so a misread file is refused instead of imported wrongly.
"""

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

ZERO = Decimal("0")
CENT = Decimal("0.01")
MAX_BYTES = 10 * 1024 * 1024
MAX_LINES = 5000
MONEY = r"\(?-?[\d,]+\.\d{2}\)?"
SIDE = r"(?:\s*(?:Cr|Dr|CR|DR|cr|dr))?"
TAIL = re.compile(rf"((?:\s+{MONEY}{SIDE}){{1,3}})\s*$")
TOKEN = re.compile(rf"({MONEY})\s*(Cr|Dr|CR|DR|cr|dr)?")
OPENING = re.compile(
    r"(opening\s+balance|balance\s+b/?f|brought\s+forward|balance\s+brought)", re.IGNORECASE
)


class StatementFileError(Exception):
    pass


@dataclass
class Layout:
    """What a template says about the file (see banking.models.StatementTemplate)."""

    file_kind: str = "excel"  # excel, csv or pdf
    date_format: str = "%d/%m/%Y"
    date_column: str = "Date"
    description_column: str = "Description"
    reference_column: str = ""
    out_column: str = "Debit"
    in_column: str = "Credit"
    amount_column: str = ""  # one signed amount instead of money out and in
    negative_is_out: bool = True
    balance_column: str = "Balance"


@dataclass
class Line:
    date: date
    description: str
    reference: str = ""
    money_out: Decimal = ZERO
    money_in: Decimal = ZERO
    balance: Decimal | None = None
    amount: Decimal | None = None  # one amount whose direction is not yet known


@dataclass
class Parsed:
    lines: list[Line] = field(default_factory=list)
    opening: Decimal | None = None
    problems: list[str] = field(default_factory=list)


def money(text, *, where: str = "") -> Decimal | None:
    """An amount as banks print it: 1,234.56, -1234.56, (1,234.56), 1,234.56 Dr."""
    if text is None:
        return None
    if isinstance(text, float):
        text = repr(text)
    if isinstance(text, (int, Decimal)):
        return Decimal(text).quantize(CENT)
    raw = str(text).strip()
    if not raw or raw in ("-", "--"):
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    side = re.search(r"(cr|dr)\s*$", raw, re.IGNORECASE)
    cleaned = re.sub(r"(cr|dr)\s*$", "", raw, flags=re.IGNORECASE)
    cleaned = cleaned.strip("() ").replace(",", "").replace(" ", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise StatementFileError(f"{where}{raw!r} is not an amount.") from None
    if not value.is_finite():
        raise StatementFileError(f"{where}{raw!r} is not an amount.")
    if negative:
        value = -value
    if side and side.group(1).lower() == "dr":
        value = -abs(value)  # the bank's "Dr" balance: the account is overdrawn
    return value.quantize(CENT)


def day(value, fmt: str, *, where: str = "") -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for candidate in (fmt, "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, candidate).date()
        except ValueError:
            continue
    return None


# --- Spreadsheets ----------------------------------------------------------------------------


def _rows(content: bytes, kind: str) -> list[list]:
    if kind == "csv":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
        return [list(r) for r in csv.reader(io.StringIO(text))]
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, OSError, KeyError, ValueError):
        raise StatementFileError("The file is not an Excel workbook (.xlsx).") from None
    return [list(r) for r in book.worksheets[0].iter_rows(values_only=True)]


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def _table(content: bytes, layout: Layout) -> Parsed:
    rows = _rows(content, layout.file_kind)
    wanted = {
        "date": layout.date_column,
        "description": layout.description_column,
        "reference": layout.reference_column,
        "out": layout.out_column,
        "in": layout.in_column,
        "amount": layout.amount_column,
        "balance": layout.balance_column,
    }
    wanted = {k: _norm(v) for k, v in wanted.items() if v}
    one_amount = "amount" in wanted
    header_at, where = None, {}
    for index, row in enumerate(rows[:50]):
        names = [_norm(c) for c in row]
        if wanted["date"] in names:
            where = {k: names.index(v) for k, v in wanted.items() if v in names}
            header_at = index
            break
    if header_at is None:
        raise StatementFileError(
            f"No heading row with a {layout.date_column!r} column was found; check the template."
        )
    needed = ["date", "description"] + (["amount"] if one_amount else ["out", "in"])
    missing = [wanted[k] for k in needed if k not in where]
    if missing:
        raise StatementFileError(
            "The file has no column "
            + ", ".join(repr(m) for m in missing)
            + "; check the template."
        )
    parsed = Parsed()

    def cell(row, key):
        i = where.get(key)
        return row[i] if i is not None and i < len(row) else None

    for n, row in enumerate(rows[header_at + 1 :], start=header_at + 2):
        here = f"Row {n}: "
        when = day(cell(row, "date"), layout.date_format, where=here)
        text = str(cell(row, "description") or "").strip()
        if when is None:
            words = " ".join(str(c) for c in row if c is not None)
            if OPENING.search(words) and "balance" in where:
                parsed.opening = money(cell(row, "balance"), where=here)
            continue
        line = Line(
            date=when,
            description=text[:500],
            reference=str(cell(row, "reference") or "").strip()[:60],
            balance=money(cell(row, "balance"), where=here) if "balance" in where else None,
        )
        if one_amount:
            amount = money(cell(row, "amount"), where=here) or ZERO
            out = amount < 0 if layout.negative_is_out else amount > 0
            line.money_out, line.money_in = (abs(amount), ZERO) if out else (ZERO, abs(amount))
        else:
            line.money_out = abs(money(cell(row, "out"), where=here) or ZERO)
            line.money_in = abs(money(cell(row, "in"), where=here) or ZERO)
        if OPENING.search(text) and not (line.money_out or line.money_in):
            parsed.opening = line.balance
            continue
        parsed.lines.append(line)
    return parsed


# --- PDF -------------------------------------------------------------------------------------


def pdf_text(content: bytes) -> list[str]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise StatementFileError("The PDF is locked with a password; save it unlocked.")
        text = "\n".join(
            (page.extract_text(extraction_mode="layout") or "") for page in reader.pages
        )
    except (PdfReadError, ValueError, KeyError, TypeError) as error:
        raise StatementFileError(f"The PDF cannot be read ({error}).") from None
    lines = [line.rstrip() for line in text.splitlines()]
    if not any(line.strip() for line in lines):
        raise StatementFileError(
            "The PDF has no text (it is a scan); ask the bank for an Excel or CSV export."
        )
    return lines


DATE_START = re.compile(
    r"^\s*(\d{1,2}[/.\-](?:\d{1,2}|[A-Za-z]{3})[/.\-](?:\d{4}|\d{2}))(?!\d)\s*(.*)$"
)


def _text_lines(lines: list[str], layout: Layout) -> Parsed:
    parsed = Parsed()
    current: Line | None = None
    for raw in lines:
        if not raw.strip():
            continue
        start = DATE_START.match(raw)
        when = day(start.group(1), layout.date_format) if start else None
        if when is None:
            if OPENING.search(raw):
                found = TAIL.search(raw)
                if found:
                    tokens = TOKEN.findall(found.group(1))
                    parsed.opening = money(" ".join(tokens[-1]).strip())
                current = None
            elif current is not None and not TAIL.search(raw):
                # The description goes on to the next line.
                more = " ".join(raw.split())
                if len(current.description) + len(more) < 490:
                    current.description = f"{current.description} {more}".strip()
            else:
                current = None  # a heading, a page footer or a total
            continue
        rest = start.group(2)
        found = TAIL.search(rest)
        if not found:
            current = None
            continue
        tokens = TOKEN.findall(found.group(1))
        description = " ".join(rest[: found.start()].split())
        amounts = [money(f"{value} {side}".strip()) for value, side in tokens]
        if OPENING.search(description):
            parsed.opening = amounts[-1]
            current = None
            continue
        line = Line(date=when, description=description[:500])
        if len(amounts) == 3:
            line.money_out, line.money_in, line.balance = (
                abs(amounts[0]),
                abs(amounts[1]),
                amounts[2],
            )
        elif len(amounts) == 2:
            line.amount, line.balance = abs(amounts[0]), amounts[1]
        else:
            current = None
            continue  # one amount alone is a total or a balance line
        parsed.lines.append(line)
        current = line
    return parsed


# --- Checking ------------------------------------------------------------------------------


def settle(parsed: Parsed, opening: Decimal | None) -> Parsed:
    """Give each one-amount line its direction from the balance, and check every balance
    against the one before. Problems are listed; the caller refuses the file if any."""
    previous = parsed.opening if parsed.opening is not None else opening
    for n, line in enumerate(parsed.lines, start=1):
        if line.amount is not None:
            if line.balance is None or previous is None:
                parsed.problems.append(
                    f"Line {n} ({line.date:%d/%m/%Y}): the direction of {line.amount:,.2f} "
                    "cannot be worked out without the balance before it; give the opening "
                    "balance."
                )
                previous = line.balance
                continue
            change = line.balance - previous
            if change == line.amount:
                line.money_in = line.amount
            elif change == -line.amount:
                line.money_out = line.amount
            else:
                parsed.problems.append(
                    f"Line {n} ({line.date:%d/%m/%Y}): {line.amount:,.2f} does not explain the "
                    f"balance going from {previous:,.2f} to {line.balance:,.2f}."
                )
            line.amount = None
        elif line.balance is not None and previous is not None:
            expected = previous + line.money_in - line.money_out
            if expected != line.balance:
                parsed.problems.append(
                    f"Line {n} ({line.date:%d/%m/%Y}): the balance should be {expected:,.2f} "
                    f"but the file says {line.balance:,.2f}."
                )
        if line.money_in and line.money_out:
            parsed.problems.append(f"Line {n}: money in and out on the same line.")
        if line.balance is not None:
            previous = line.balance
    if not parsed.lines:
        parsed.problems.append("No transactions were found in the file; check the template.")
    if len(parsed.lines) > MAX_LINES:
        parsed.problems.append(f"A statement can have at most {MAX_LINES} lines.")
    return parsed


def read(content: bytes, layout: Layout, opening: Decimal | None = None) -> Parsed:
    if len(content) > MAX_BYTES:
        raise StatementFileError("The file must be 10 MB or smaller.")
    if layout.file_kind == "pdf":
        if not content.startswith(b"%PDF"):
            raise StatementFileError("The file is not a PDF.")
        parsed = _text_lines(pdf_text(content), layout)
    else:
        parsed = _table(content, layout)
    return settle(parsed, opening)
