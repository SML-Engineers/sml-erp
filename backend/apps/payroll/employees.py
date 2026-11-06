"""Employee master (backlog P2B-01).

- HR (HR and payroll: Enter, the HR and Payroll Officer) adds and keeps employees, one by one
  or from Excel (checked first, all or nothing, every refused row listed). The Director (HR
  and payroll: Approve) sees them too. Others see no personal details.
- Only the employees of the person's divisions are shown and kept.
- The employee number never changes; an employee who leaves gets a leaving date and is
  deactivated, never deleted (database).
- The salary bank account is entered or changed by HR; then someone else with HR and payroll:
  Approve (the Director) checks it, as for suppliers' bank details (spec 4.6). Until it is
  checked, salary is not paid to it (P2B-07).
"""

import io
import re
import zipfile
from datetime import date, datetime

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.masters.models import Section

from .models import Employee

NUMBER = re.compile(r"^[A-Z0-9][A-Z0-9/-]{0,19}$")
NIC = re.compile(r"^(\d{9}[VX]|\d{12})$")  # old (9 digits and V or X) or new (12 digits)
ACCOUNT_NUMBER = re.compile(r"^[A-Z0-9][A-Z0-9 -]{3,33}$")
BANK_FIELDS = ("bank_name", "bank_branch", "account_name", "account_number")
TEXT_FIELDS = (
    "full_name",
    "name_with_initials",
    "address",
    "phone",
    "email",
    "epf_no",
    "etf_no",
    "designation",
    "grade",
    "leaving_reason",
)
MAX_BYTES = 5 * 1024 * 1024
COLUMNS = [
    ("number", "Employee no"),
    ("full_name", "Full name"),
    ("name_with_initials", "Name with initials"),
    ("nic", "NIC"),
    ("date_of_birth", "Date of birth"),
    ("division", "Division"),
    ("section", "Section"),
    ("designation", "Designation"),
    ("grade", "Grade"),
    ("employment_type", "Employment type"),
    ("category", "Category"),
    ("join_date", "Join date"),
    ("confirmation_date", "Confirmation date"),
    ("epf_no", "EPF no"),
    ("etf_no", "ETF no"),
    ("phone", "Phone"),
    ("email", "Email"),
    ("address", "Address"),
    ("bank_name", "Bank"),
    ("bank_branch", "Branch"),
    ("account_name", "Account name"),
    ("account_number", "Account number"),
]


class EmployeeError(Exception):
    pass


def can_view(user: User) -> bool:
    access = effective_access(user)
    return access.has("hr_payroll", "enter") or access.has("hr_payroll", "approve")


def can_edit(user: User) -> bool:
    return effective_access(user).has("hr_payroll", "enter")


def can_check_bank(user: User) -> bool:
    return effective_access(user).has("hr_payroll", "approve")


def can_export(user: User) -> bool:
    """A list of everyone's NIC and bank account leaves the system only with this action."""
    return can_view(user) and effective_access(user).can("export_personal_data")


def visible(user: User) -> QuerySet[Employee]:
    if not can_view(user):
        return Employee.objects.none()
    return Employee.objects.filter(division__in=division_scope(user)).select_related(
        "division", "section", "user"
    )


def search(rows: QuerySet[Employee], text: str) -> QuerySet[Employee]:
    text = (text or "").strip()
    if not text:
        return rows
    return rows.filter(
        Q(number__icontains=text)
        | Q(full_name__icontains=text)
        | Q(nic__icontains=text)
        | Q(epf_no__iexact=text)
        | Q(designation__icontains=text)
    )


# --- Checking what was entered -----------------------------------------------------------------


def _day(value, what: str, *, required=False) -> date | None:
    if value in (None, ""):
        if required:
            raise EmployeeError(f"The {what} is required.")
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise EmployeeError(f"The {what} {text!r} is not a date (for example 2026-04-01).")


def _text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value if value is not None else "").split())


def clean(user: User, values: dict, current: Employee | None = None) -> dict:
    """Check the fields given (all of them for a new employee)."""
    out: dict = {}
    if current is None or "number" in values:
        number = _text(values.get("number")).upper()
        if current is not None and number != current.number:
            raise EmployeeError("The employee number never changes.")
        if not NUMBER.match(number):
            raise EmployeeError("The employee number is 1 to 20 letters, digits, / or -.")
        out["number"] = number
    for field in TEXT_FIELDS + BANK_FIELDS:
        if field in values:
            out[field] = _text(values[field])
    if current is None and not out.get("full_name"):
        raise EmployeeError("The full name is required.")
    if "full_name" in out and not out["full_name"]:
        raise EmployeeError("The full name is required.")
    if current is None or "nic" in values:
        nic = _text(values.get("nic")).upper().replace(" ", "")
        if not NIC.match(nic):
            raise EmployeeError("The NIC is 9 digits and V or X, or 12 digits.")
        out["nic"] = nic
    if out.get("email") and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", out["email"]):
        raise EmployeeError("The email address is not valid.")
    if out.get("epf_no") and not re.match(r"^[0-9A-Z/-]{1,20}$", out["epf_no"].upper()):
        raise EmployeeError("The EPF number is digits (and / or -).")
    if out.get("account_number"):
        out["account_number"] = out["account_number"].upper()
        if not ACCOUNT_NUMBER.match(out["account_number"]):
            raise EmployeeError("The account number is 4 to 34 letters, digits, spaces or dashes.")
    for field, what in (
        ("date_of_birth", "date of birth"),
        ("join_date", "join date"),
        ("confirmation_date", "confirmation date"),
    ):
        if current is None or field in values:
            out[field] = _day(values.get(field), what, required=field == "join_date")
    if current is None or "employment_type" in values:
        kind = _text(values.get("employment_type")).lower()
        labels = {label.lower(): code for code, label in Employee.Type.choices}
        kind = labels.get(kind, kind)
        if kind not in Employee.Type.values:
            raise EmployeeError(
                "The employment type is one of: "
                + ", ".join(label for _, label in Employee.Type.choices)
                + "."
            )
        out["employment_type"] = kind
    category = _text(values.get("category")).lower()
    if current is None or category:
        # P2B-16: Shop and Office or Wages Board. Blank: Shop and Office for a new employee,
        # unchanged for an existing one (an older sheet without the column changes nothing).
        category = category or Employee.Category.SHOP_OFFICE
        labels = {label.lower(): code for code, label in Employee.Category.choices}
        category = labels.get(category, category)
        if category not in Employee.Category.values:
            raise EmployeeError("The category is Shop and Office or Wages Board.")
        out["category"] = category
    clock = _text(values.get("phone_clock")).lower()
    if clock:
        # P2B-12: whether and where the employee may clock in from the phone.
        labels = {label.lower(): code for code, label in Employee.PhoneClock.choices}
        clock = labels.get(clock, clock)
        if clock not in Employee.PhoneClock.values:
            raise EmployeeError(
                "The phone clock is one of: "
                + ", ".join(label for _, label in Employee.PhoneClock.choices)
                + "."
            )
        out["phone_clock"] = clock
    if current is None or "division" in values:
        code = _text(values.get("division")).upper()
        division = division_scope(user).filter(code=code, is_active=True).first()
        if division is None:
            raise EmployeeError("Choose one of your active divisions.")
        out["division"] = division
    division = out.get("division") or (current.division if current else None)
    if "section" in values or "division" in out:
        name = _text(values.get("section"))
        if not name and current is not None and "section" not in values:
            section = current.section
            if section is not None and section.division_id != division.pk:
                section = None
        elif not name:
            section = None
        else:
            section = (
                Section.objects.filter(division=division)
                .filter(Q(code__iexact=name) | Q(name__iexact=name))
                .first()
            )
            if section is None:
                raise EmployeeError(f"Division {division.code} has no section {name}.")
        out["section"] = section
    if "user" in values:
        out["user"] = None
        if values["user"]:
            found = User.objects.filter(pk=values["user"]).first()
            if found is None:
                raise EmployeeError("Unknown user.")
            out["user"] = found
    if "user_email" in values:
        # Self-service (P2B-11): HR links the employee to their sign-in by its email address;
        # blank removes the link.
        email = _text(values.get("user_email")).lower()
        out["user"] = None
        if email:
            found = User.objects.filter(email__iexact=email, is_active=True).first()
            if found is None:
                raise EmployeeError(f"There is no active sign-in with the email {email}.")
            out["user"] = found
    join = out.get("join_date") or (current.join_date if current else None)
    confirmed = out.get("confirmation_date", current.confirmation_date if current else None)
    if confirmed and join and confirmed < join:
        raise EmployeeError("The confirmation date is before the join date.")
    born = out.get("date_of_birth", current.date_of_birth if current else None)
    if born and join and (join.year - born.year) < 14:
        raise EmployeeError("The date of birth and join date make the employee younger than 14.")
    return out


def _bank_changed(employee: Employee, values: dict) -> bool:
    return any(f in values and values[f] != getattr(employee, f) for f in BANK_FIELDS)


def _save(employee: Employee) -> None:
    try:
        with transaction.atomic():
            employee.save()
    except IntegrityError as error:
        text = str(error)
        if "nic" in text:
            raise EmployeeError(f"Another employee has the NIC {employee.nic}.") from None
        if "number" in text:
            raise EmployeeError(f"Employee number {employee.number} is taken.") from None
        if "user" in text:
            raise EmployeeError("That user is linked to another employee.") from None
        raise


# --- Keeping employees -------------------------------------------------------------------------


def create(user: User, values: dict) -> Employee:
    if not can_edit(user):
        raise EmployeeError("Only HR adds employees.")
    cleaned = clean(user, values)
    with audit_context("employee_added"), transaction.atomic():
        employee = Employee(created_by=user, **cleaned)
        if any(cleaned.get(f) for f in BANK_FIELDS):
            employee.bank_changed_at = timezone.now()
            employee.bank_changed_by = user
        _save(employee)
        return employee


def update(user: User, employee: Employee, values: dict, reason: str = "") -> Employee:
    if not can_edit(user):
        raise EmployeeError("Only HR changes employees.")
    if not employee.is_active:
        raise EmployeeError("This employee has left; their record is kept as it was.")
    cleaned = clean(user, values, employee)
    bank = _bank_changed(employee, cleaned)
    if bank and not (reason or "").strip():
        raise EmployeeError("Give a reason for changing the bank account.")
    with audit_context("employee_changed", reason), transaction.atomic():
        employee = Employee.objects.select_for_update().get(pk=employee.pk)
        for key, value in cleaned.items():
            setattr(employee, key, value)
        if bank:
            employee.bank_changed_at = timezone.now()
            employee.bank_changed_by = user
        _save(employee)
        return employee


def check_bank(user: User, employee: Employee) -> Employee:
    """A second person confirms the new salary bank account (spec 4.6)."""
    if not can_check_bank(user):
        raise EmployeeError("Only the Director checks salary bank accounts.")
    with audit_context("employee_bank_checked"), transaction.atomic():
        employee = Employee.objects.select_for_update().get(pk=employee.pk)
        if not employee.bank_check_pending:
            raise EmployeeError("There is no bank account change to check.")
        if employee.bank_changed_by_id == user.pk:
            raise EmployeeError("The person who changed the bank account cannot check it.")
        employee.bank_checked_at = timezone.now()
        employee.bank_checked_by = user
        employee.save(update_fields=["bank_checked_at", "bank_checked_by"])
        return employee


def leave(user: User, employee: Employee, on: date, reason: str) -> Employee:
    if not can_edit(user):
        raise EmployeeError("Only HR records leavers.")
    reason = " ".join((reason or "").split())
    if not reason:
        raise EmployeeError("Give the reason for leaving.")
    if on < employee.join_date:
        raise EmployeeError("The leaving date is before the join date.")
    with audit_context("employee_left", reason), transaction.atomic():
        employee = Employee.objects.select_for_update().get(pk=employee.pk)
        employee.leaving_date = on
        employee.leaving_reason = reason[:200]
        employee.is_active = False
        employee.save(update_fields=["leaving_date", "leaving_reason", "is_active"])
        return employee


# --- Excel ------------------------------------------------------------------------------------


def _as_entered(cleaned: dict) -> dict:
    """Checked values back in the form a person enters them (codes, not records)."""
    values = dict(cleaned)
    if "division" in values:
        values["division"] = values["division"].code
    if "section" in values:
        values["section"] = values["section"].code if values["section"] else ""
    return values


def export_workbook(rows) -> bytes:
    """The employees in the import layout (an empty sheet is the template)."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Employees"
    sheet.append([label for _, label in COLUMNS])
    for e in rows:
        sheet.append(
            [
                e.number,
                e.full_name,
                e.name_with_initials,
                e.nic,
                e.date_of_birth,
                e.division.code,
                e.section.code if e.section else "",
                e.designation,
                e.grade,
                e.get_employment_type_display(),
                e.get_category_display(),
                e.join_date,
                e.confirmation_date,
                e.epf_no,
                e.etf_no,
                e.phone,
                e.email,
                e.address,
                e.bank_name,
                e.bank_branch,
                e.account_name,
                e.account_number,
            ]
        )
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def import_workbook(user: User, content: bytes, *, dry_run: bool, reason: str = "") -> dict:
    """Add or update employees from Excel, matched by employee number. All or nothing."""
    if not can_edit(user):
        raise EmployeeError("Only HR imports employees.")
    if len(content) > MAX_BYTES:
        raise EmployeeError("The file is larger than 5 MB.")
    try:
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, OSError, KeyError, ValueError):
        raise EmployeeError("The file is not an Excel workbook (.xlsx).") from None
    rows = [list(r) for r in book.worksheets[0].iter_rows(values_only=True)]
    if not rows:
        raise EmployeeError("The file is empty.")
    head = [_text(c).lower() for c in rows[0]]
    index = {}
    for key, label in COLUMNS:
        if label.lower() in head:
            index[key] = head.index(label.lower())
    required = ("number", "full_name", "nic", "division", "employment_type", "join_date")
    if any(key not in index for key in required):
        raise EmployeeError(
            "The first row must hold the column names of the template (at least Employee no, "
            "Full name, NIC, Division, Employment type and Join date)."
        )
    errors, plan = [], []
    existing = {e.number: e for e in Employee.objects.all()}
    seen = set()
    for n, row in enumerate(rows[1:], start=2):
        values = {key: (row[i] if i < len(row) else None) for key, i in index.items()}
        if not any(_text(v) for v in values.values()):
            continue
        number = _text(values.get("number")).upper()
        if number in seen:
            errors.append(f"Row {n}: employee number {number} appears twice.")
            continue
        seen.add(number)
        current = existing.get(number)
        try:
            if current is not None:
                if not division_scope(user).filter(pk=current.division_id).exists():
                    raise EmployeeError("this employee is not in one of your divisions.")
                if not current.is_active:
                    raise EmployeeError("this employee has left; the record is not changed.")
                cleaned = clean(user, values, current)
            else:
                cleaned = clean(user, values)
        except EmployeeError as error:
            errors.append(f"Row {n} ({number or 'no number'}): {error}")
            continue
        plan.append((current, cleaned))
    if errors:
        return {"errors": errors[:50], "added": 0, "updated": 0, "saved": False}
    added = sum(1 for c, _ in plan if c is None)
    updated = len(plan) - added
    if dry_run:
        return {"errors": [], "added": added, "updated": updated, "saved": False}
    try:
        with transaction.atomic():
            for current, cleaned in plan:
                values = _as_entered(cleaned)
                if current is None:
                    create(user, values)
                else:
                    update(user, current, values, reason or "Excel import")
    except EmployeeError as error:
        return {"errors": [str(error)], "added": 0, "updated": 0, "saved": False}
    return {"errors": [], "added": added, "updated": updated, "saved": True}
