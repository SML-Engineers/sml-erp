"""Excel export and import of sections and machines (spec 3A.1).

The export and the import use the same layout, so the Admin can export, edit in Excel and
import again. An import goes through the same rules as the page (services.py), and is all
or nothing: if any row is refused, nothing is saved and every refusal is listed.
"""

import io
import zipfile
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils.exceptions import InvalidFileException

from apps.core.models import Division, User

from . import services
from .models import Machine, Section

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000

SECTION_COLUMNS = ["Code", "Name", "Division", "Type", "Category", "Supervisors", "Active"]
MACHINE_COLUMNS = [
    "Code",
    "Name",
    "Section",
    "Make",
    "Model",
    "Serial no.",
    "Year",
    "Status",
    "Clamping force (t)",
    "Maximum shot weight (g)",
    "Screw diameter (mm)",
    "Tie-bar spacing, horizontal (mm)",
    "Tie-bar spacing, vertical (mm)",
    "Maximum mould height (mm)",
    "Maximum mould thickness (mm)",
    "Notes",
    "Hourly rate (LKR)",
    "Rate from",
]
MEASURES = dict(zip(MACHINE_COLUMNS[8:15], services.MOULDING_FIELDS, strict=True))
TEXTS = {"Make": "make", "Model": "model", "Serial no.": "serial_no", "Notes": "notes"}


class ImportRefused(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# --- Export -----------------------------------------------------------------------------


def _sheet(workbook, title, columns, rows):
    sheet = workbook.create_sheet(title)
    sheet.append(columns)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(row)
    for index, column in enumerate(columns, start=1):
        sheet.column_dimensions[sheet.cell(1, index).column_letter].width = max(12, len(column) + 2)
    sheet.freeze_panes = "A2"
    return sheet


def export_workbook() -> bytes:
    today = timezone.localdate()
    workbook = Workbook()
    workbook.remove(workbook.active)
    sections = Section.objects.select_related("division").prefetch_related("supervisors")
    _sheet(
        workbook,
        "Sections",
        SECTION_COLUMNS,
        [
            [
                s.code,
                s.name,
                s.division.code,
                s.get_section_type_display(),
                s.get_category_display() if s.category else "",
                ", ".join(sorted(u.email for u in s.supervisors.all())),
                "Yes" if s.is_active else "No",
            ]
            for s in sections
        ],
    )
    machines = Machine.objects.select_related("section")
    rows = []
    for m in machines:
        current = m.rates.filter(effective_from__lte=today).order_by("-effective_from").first()
        rows.append(
            [
                m.code,
                m.name,
                m.section.code,
                m.make,
                m.model,
                m.serial_no,
                m.year,
                m.get_status_display(),
                *[getattr(m, field) for field in services.MOULDING_FIELDS],
                m.notes,
                current.rate if current else None,
                current.effective_from if current else None,
            ]
        )
    sheet = _sheet(workbook, "Machines", MACHINE_COLUMNS, rows)
    for row in sheet.iter_rows(min_row=2):
        row[16].number_format = "#,##0.00"
        row[17].number_format = "yyyy-mm-dd"
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


# --- Import -----------------------------------------------------------------------------


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _choice(value, choices, what) -> str:
    text = _text(value).lower()
    for code, label in choices:
        if text in (code.lower(), str(label).lower()):
            return code
    names = ", ".join(str(label) for _, label in choices)
    raise services.MastersError(f"{what} must be one of: {names}.")


def _yes_no(value) -> bool:
    text = _text(value).lower()
    if text in ("", "yes", "y", "true", "1", "active"):
        return True
    if text in ("no", "n", "false", "0", "inactive"):
        return False
    raise services.MastersError("Active must be Yes or No.")


def _date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(_text(value))
    except ValueError:
        raise services.MastersError("Rate from must be a date, for example 2026-11-01.") from None


def _number(value):
    """Excel stores numbers as floating point; read them back through their text so that
    1500.5 stays exactly 1500.5 (rule 1)."""
    if value in (None, ""):
        return None
    if isinstance(value, float):
        return Decimal(repr(value))
    return _text(value)


def _rows(workbook, title, columns):
    if title not in workbook.sheetnames:
        return []
    sheet = workbook[title]
    header = [_text(c) for c in next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), [])]
    missing = [c for c in columns if c not in header]
    if missing:
        raise ImportRefused([f"Sheet {title}: missing columns {', '.join(missing)}."])
    rows = []
    for number, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        if values is None or all(v in (None, "") for v in values):
            continue
        if len(rows) >= MAX_ROWS:
            raise ImportRefused([f"Sheet {title}: more than {MAX_ROWS} rows."])
        values = list(values)
        values += [None] * (len(header) - len(values))
        rows.append((number, {h: values[i] for i, h in enumerate(header) if h}))
    return rows


def _section_row(row: dict, reason: str):
    code = services.normalise_code(_text(row["Code"]), "section")
    division = Division.objects.filter(code=_text(row["Division"]).upper()).first()
    if division is None:
        raise services.MastersError(f"Unknown division {_text(row['Division'])!r}.")
    emails = [e.strip().lower() for e in _text(row["Supervisors"]).split(",") if e.strip()]
    users = list(User.objects.filter(email__in=emails))
    if len(users) != len(set(emails)):
        known = {u.email for u in users}
        unknown = ", ".join(e for e in emails if e not in known)
        raise services.MastersError(f"Unknown supervisor {unknown}.")
    data = {
        "name": _text(row["Name"]),
        "division": division,
        "section_type": _choice(row["Type"], Section.Type.choices, "Type"),
        "category": _choice(row["Category"], [("", ""), *Section.Category.choices], "Category"),
        "supervisors": [u.pk for u in users],
        "is_active": _yes_no(row["Active"]),
    }
    existing = Section.objects.filter(code=code).first()
    if existing:
        services.update_section(existing, data, reason=reason)
        return "updated"
    services.create_section(code=code, reason=reason, **data)
    return "created"


def _machine_row(row: dict, reason: str, user):
    code = services.normalise_code(_text(row["Code"]), "machine")
    section = Section.objects.filter(code=_text(row["Section"]).upper()).first()
    if section is None:
        raise services.MastersError(f"Unknown section {_text(row['Section'])!r}.")
    data = {
        "name": _text(row["Name"]),
        "section": section,
        "year": _number(row["Year"]),
        "status": _choice(row["Status"] or "Active", Machine.Status.choices, "Status"),
        **{field: _text(row[column]) for column, field in TEXTS.items()},
        **{field: _number(row[column]) for column, field in MEASURES.items()},
    }
    existing = Machine.objects.filter(code=code).first()
    if existing:
        machine = services.update_machine(existing, data, reason=reason)
        outcome = "updated"
    else:
        machine = services.create_machine(code=code, reason=reason, **data)
        outcome = "created"

    rate = _number(row["Hourly rate (LKR)"])
    if rate is not None:
        starts = _date(row["Rate from"]) or timezone.localdate()
        if services.rate_on(machine, starts) != services._money(rate):
            services.add_rate(machine, effective_from=starts, rate=rate, reason=reason, user=user)
    return outcome


def import_workbook(content: bytes, *, reason: str, user, dry_run: bool) -> dict:
    """Apply a workbook. Returns counts; raises ImportRefused listing every refused row."""
    if not (reason or "").strip():
        raise ImportRefused(["Give a reason for the import."])
    if len(content) > MAX_BYTES:
        raise ImportRefused(["The file must be 5 MB or smaller."])
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, OSError, KeyError, ValueError):
        raise ImportRefused(["The file is not an Excel workbook (.xlsx)."]) from None
    sections = _rows(workbook, "Sections", SECTION_COLUMNS)
    machines = _rows(workbook, "Machines", MACHINE_COLUMNS)
    if not sections and not machines:
        raise ImportRefused(["The workbook has no Sections or Machines rows."])

    counts = {"sections_created": 0, "sections_updated": 0}
    counts |= {"machines_created": 0, "machines_updated": 0}
    errors = []
    with transaction.atomic():
        for title, rows, apply in (
            ("Sections", sections, lambda r: _section_row(r, reason)),
            ("Machines", machines, lambda r: _machine_row(r, reason, user)),
        ):
            for number, row in rows:
                try:
                    with transaction.atomic():
                        outcome = apply(row)
                except services.MastersError as error:
                    errors.append(f"{title} row {number}: {error}")
                    continue
                counts[f"{title.lower()}_{outcome}"] += 1
        if errors or dry_run:
            transaction.set_rollback(True)
    if errors:
        raise ImportRefused(errors)
    return counts
