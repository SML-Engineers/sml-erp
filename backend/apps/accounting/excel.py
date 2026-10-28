"""Excel export and import of the chart of accounts (spec 3, backlog P0-15).

One sheet, "Accounts", in the same layout both ways, so the Accountant can export, edit in
Excel and import again, or load an existing chart in one step. Parent is the parent's full
name, written as in QuickBooks: Repairs and maintenance:Machine repairs.

A row is matched to an existing account by its number, or else by its full name; other rows
add accounts. A detail type not yet on the list is added. The import goes through the same
rules as the page and is all or nothing: if any row is refused, nothing is saved.
"""

import io
import zipfile

from django.db import transaction
from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from apps.core.models import Division
from apps.masters.excel import ImportRefused, _rows, _sheet, _text, _yes_no
from apps.masters.services import MastersError

from . import services
from .catalogue import TYPES
from .models import Account, DetailType

MAX_BYTES = 5 * 1024 * 1024
SHEET = "Accounts"
COLUMNS = [
    "Number",
    "Name",
    "Parent",
    "Type",
    "Detail type",
    "Description",
    "Default division",
    "Active",
]

__all__ = ["ImportRefused", "export_workbook", "import_workbook"]


def export_workbook() -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    rows = []
    for account, _depth, name in services.chart(include_inactive=True):
        if account.merged_into_id:
            continue  # history only; its entries are reported under the remaining account
        parent = name.rsplit(":", 1)[0] if ":" in name else ""
        rows.append(
            [
                account.number,
                account.name,
                parent,
                TYPES[account.account_type][0],
                account.detail_type.name,
                account.description,
                account.default_division.code if account.default_division else "",
                "Yes" if account.is_active else "No",
            ]
        )
    sheet = _sheet(workbook, SHEET, COLUMNS, rows)
    sheet.column_dimensions["B"].width = 40
    sheet.column_dimensions["C"].width = 40
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _account_type(value) -> str:
    text = _text(value).lower()
    for code, (label, _, _) in TYPES.items():
        if text in (code, label.lower()):
            return code
    names = ", ".join(label for label, _, _ in TYPES.values())
    raise services.AccountingError(f"Type must be one of: {names}.")


class _Import:
    def __init__(self, user, reason):
        self.user, self.reason = user, reason
        self.counts = {"created": 0, "updated": 0, "unchanged": 0, "detail_types_created": 0}
        self.by_name = {
            name.lower(): account
            for account, _, name in services.chart(include_inactive=True)
            if not account.merged_into_id
        }

    def detail(self, account_type, value) -> DetailType:
        name = " ".join(_text(value).split())
        if not name:
            raise services.AccountingError("Detail type is required.")
        found = DetailType.objects.filter(account_type=account_type, name__iexact=name).first()
        if found:
            return found
        self.counts["detail_types_created"] += 1
        return services.create_detail_type(
            self.user, account_type=account_type, name=name, reason=self.reason
        )

    def row(self, row: dict) -> None:
        number = services._number(_text(row["Number"]))
        name = services._name(_text(row["Name"]))
        parent_name = ":".join(p.strip() for p in _text(row["Parent"]).split(":") if p.strip())
        parent = None
        if parent_name:
            parent = self.by_name.get(parent_name.lower())
            if parent is None:
                raise services.AccountingError(f"Unknown parent account {parent_name}.")
            parent.refresh_from_db()
        account_type = _account_type(row["Type"])
        division_code = _text(row["Default division"]).upper()
        division = None
        if division_code:
            division = Division.objects.filter(code=division_code).first()
            if division is None:
                raise services.AccountingError(f"Unknown division {division_code}.")
        values = {
            "name": name,
            "number": number,
            "parent": parent,
            "account_type": account_type,
            "detail_type": self.detail(account_type, row["Detail type"]),
            "description": _text(row["Description"]),
            "default_division": division,
        }
        active = _yes_no(row["Active"])
        full = f"{parent_name}:{name}" if parent_name else name
        existing = None
        if number:
            existing = Account.objects.filter(number=number, merged_into__isnull=True).first()
        existing = existing or self.by_name.get(full.lower())
        if existing is None:
            account = services.create_account(self.user, reason=self.reason, **values)
            if not active:
                services.update_account(self.user, account, {"is_active": False}, self.reason)
            self.counts["created"] += 1
        else:
            existing.refresh_from_db()
            before = self._snapshot(existing)
            if existing.is_active != active:
                values["is_active"] = active
            account = services.update_account(self.user, existing, values, self.reason)
            self.counts["updated" if self._snapshot(account) != before else "unchanged"] += 1
        self.by_name[full.lower()] = account

    @staticmethod
    def _snapshot(a: Account):
        return (
            a.number,
            a.name,
            a.parent_id,
            a.account_type,
            a.detail_type_id,
            a.description,
            a.default_division_id,
            a.is_active,
        )


def _depth(row: dict) -> int:
    parent = _text(row.get("Parent"))
    return 0 if not parent else parent.count(":") + 1


def import_workbook(content: bytes, *, reason: str, user, dry_run: bool) -> dict:
    """Apply a workbook. Returns counts; raises ImportRefused listing every refused row."""
    services._manage(user)
    if not (reason or "").strip():
        raise ImportRefused(["Give a reason for the import."])
    if len(content) > MAX_BYTES:
        raise ImportRefused(["The file must be 5 MB or smaller."])
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, OSError, KeyError, ValueError):
        raise ImportRefused(["The file is not an Excel workbook (.xlsx)."]) from None
    rows = _rows(workbook, SHEET, COLUMNS)
    if not rows:
        raise ImportRefused([f"The workbook has no {SHEET} sheet, or it has no rows."])
    # Parents before their sub-accounts, whatever the order in the sheet.
    rows.sort(key=lambda item: (_depth(item[1]), item[0]))
    errors = []
    with transaction.atomic():
        job = _Import(user, reason)
        for number, row in rows:
            try:
                with transaction.atomic():
                    job.row(row)
            except (services.AccountingError, MastersError) as error:
                errors.append(f"Row {number}: {error}")
        if errors or dry_run:
            transaction.set_rollback(True)
    if errors:
        errors.sort(key=lambda e: int(e.split(":")[0].split()[1]))
        raise ImportRefused(errors)
    return job.counts
