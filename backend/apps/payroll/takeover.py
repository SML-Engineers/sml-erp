"""Taking over from the old payroll (backlog P2B-14; owner, question 2: payroll is in Excel
today).

The old payroll's figures are typed or pasted into the ERP's own Excel templates by HR and
uploaded into the ERP; they never go into the repository or anywhere else.

1. **Employees**: the employee import (P2B-01) as before.
2. **Pay**: one row per employee (employee number, the pay month it applies from, an amount
   under each pay component's code). Each row becomes the employee's first pay settings, sent
   to the Director like any new employee's (P2B-17); nothing takes effect until approved.
   All or nothing, after a preview.
3. **The year's figures to date** (the year of assessment from 1 April) up to the last pay
   month paid by the old payroll: months, gross, APIT taxable earnings and APIT, EPF 8% and
   12%, ETF, net, and the gratuity provided for each employee so far. The Director approves
   the upload (approval engine, "payroll_opening"). Once approved they count in the payslips'
   year to date, the APIT year return and certificates, and as the gratuity already provided
   (so the first payroll here provides only the change). They never change (database). An
   employee already paid here for those months, or with approved figures for the year, is
   refused.
4. **Parallel run**: one pay month run in both. HR uploads the old payroll's figures for
   it (gross, EPF 8% and 12%, ETF, APIT, net per employee); the ERP compares them with its
   payroll employee by employee and lists every difference and anyone missing on either
   side. The comparison is kept as made; the Director signs it off (never the person who
   uploaded it), with a note when there are differences. The old payroll stops after
   sign-off.
"""

import io
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils.exceptions import InvalidFileException

from apps.core import approvals
from apps.core.access import division_scope
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User

from . import changes, employees, pay, payslips
from .changes import ChangeError
from .models import (
    Employee,
    OpeningBatch,
    OpeningFigures,
    ParallelCheck,
    PayComponent,
    PayrollLine,
    PayrollRun,
)

DOC = "payroll_opening"
MAX_BYTES = 5 * 1024 * 1024
ZERO = Decimal("0.00")
CENT = Decimal("0.01")

OPENING_COLUMNS = [
    ("number", "Employee no"),
    ("last_month", "Last pay month paid"),
    ("months", "Months paid"),
    ("gross", "Gross pay"),
    ("apit_earnings", "APIT taxable earnings"),
    ("apit", "APIT"),
    ("epf_employee", "EPF 8%"),
    ("epf_employer", "EPF 12%"),
    ("etf", "ETF 3%"),
    ("net", "Net pay"),
    ("gratuity_provision", "Gratuity provided"),
]
OPENING_MONEY = [k for k, _ in OPENING_COLUMNS[3:]]

COMPARED = [
    ("gross", "Gross pay"),
    ("epf_employee", "EPF 8%"),
    ("epf_employer", "EPF 12%"),
    ("etf", "ETF 3%"),
    ("apit", "APIT"),
    ("net", "Net pay"),
]


class TakeoverError(Exception):
    pass


class _Rollback(Exception):
    pass


# --- Excel ---------------------------------------------------------------------------------------


def _text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value if value is not None else "").split())


def _read(content: bytes) -> list[list]:
    if len(content) > MAX_BYTES:
        raise TakeoverError("The file is larger than 5 MB.")
    try:
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, OSError, KeyError, ValueError):
        raise TakeoverError("The file is not an Excel workbook (.xlsx).") from None
    rows = [list(r) for r in book.worksheets[0].iter_rows(values_only=True)]
    if not rows:
        raise TakeoverError("The file is empty.")
    return rows


def _index(head_row: list, columns: list[tuple[str, str]], required: list[str]) -> dict:
    head = [_text(c).lower() for c in head_row]
    index = {key: head.index(label.lower()) for key, label in columns if label.lower() in head}
    missing = [label for key, label in columns if key in required and key not in index]
    if missing:
        raise TakeoverError(
            "The first row must hold the column names of the template; missing: "
            + ", ".join(missing)
            + "."
        )
    return index


def _book(columns: list[str], rows: list[list], widths=None) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.append(columns)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(row)
    for i, column in enumerate(sheet.columns):
        sheet.column_dimensions[column[0].column_letter].width = (widths or {}).get(i, 16)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _money(value, label: str) -> Decimal:
    if value in (None, ""):
        return ZERO
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise TakeoverError(f"{label} is an amount, for example 45000.00.") from None
    if not number.is_finite() or number < 0:
        raise TakeoverError(f"{label} is 0 or more.")
    return number.quantize(CENT)


def _month(value, label: str) -> date:
    if isinstance(value, datetime):
        value = value.date()
    try:
        return pay.month_of(value)
    except pay.PayError:
        raise TakeoverError(f"{label} is a pay month, for example 2026-10.") from None


def _employee(user: User, number: str) -> Employee:
    found = employees.visible(user).filter(number=number.upper()).first()
    if found is None:
        raise TakeoverError(f"there is no employee {number} in your divisions.")
    return found


def _check_hr(user: User) -> None:
    if not employees.can_edit(user):
        raise TakeoverError("Only HR brings over the old payroll.")


# --- 2. Pay --------------------------------------------------------------------------------------


def _components() -> list[PayComponent]:
    return list(PayComponent.objects.filter(is_active=True).order_by("sort_order", "code"))


def pay_template(user: User) -> bytes:
    _check_hr(user)
    codes = [c.code for c in _components()]
    waiting = employees.visible(user).filter(is_active=True).exclude(pay_changes__status="approved")
    rows = [[e.number, "", *([""] * len(codes))] for e in waiting.order_by("number")]
    return _book(["Employee no", "From pay month", *codes], rows)


def import_pay(user: User, content: bytes, *, dry_run: bool) -> dict:
    _check_hr(user)
    rows = _read(content)
    codes = {c.code for c in _components()}
    head = [_text(c) for c in rows[0]]
    index = _index(rows[0], [("number", "Employee no"), ("month", "From pay month")], ["number"])
    columns = {i: h.upper() for i, h in enumerate(head) if h.upper() in codes}
    unknown = [h for i, h in enumerate(head) if h and i not in columns and i not in index.values()]
    if unknown:
        raise TakeoverError(
            "These columns are not pay components in use: " + ", ".join(unknown) + "."
        )
    errors: list[str] = []
    done = 0
    try:
        with transaction.atomic():
            for n, row in enumerate(rows[1:], start=2):
                number = _text(row[index["number"]] if index["number"] < len(row) else "")
                amounts = [
                    {"component": code, "amount": row[i]}
                    for i, code in columns.items()
                    if i < len(row) and _text(row[i])
                ]
                if not number and not amounts:
                    continue
                try:
                    employee = _employee(user, number)
                    month = _month(
                        row[index["month"]] if "month" in index else None, "From pay month"
                    )
                    if not amounts:
                        raise TakeoverError("no amounts.")
                    with transaction.atomic():
                        change = changes.prepare(
                            user,
                            employee,
                            {
                                "effective_from": month.isoformat(),
                                "reason": "Brought over from the old payroll",
                                "lines": amounts,
                            },
                        )
                        changes.submit(user, change, "Brought over from the old payroll")
                    done += 1
                except (TakeoverError, ChangeError) as error:
                    errors.append(f"Row {n} ({number or 'no number'}): {error}")
            if errors or dry_run:
                raise _Rollback
    except _Rollback:
        pass
    return {"errors": errors[:50], "rows": done, "saved": not errors and not dry_run}


# --- 3. The year's figures to date ---------------------------------------------------------------


def tax_year_of(month: date) -> date:
    """The year of assessment a pay month belongs to (by the day it ends)."""
    return payslips.year_start(month.replace(day=20))


def opening_template(user: User) -> bytes:
    _check_hr(user)
    rows = [
        [e.number] + [""] * (len(OPENING_COLUMNS) - 1)
        for e in employees.visible(user).filter(is_active=True).order_by("number")
    ]
    return _book([label for _, label in OPENING_COLUMNS], rows)


def import_opening(user: User, content: bytes, file_name: str, *, dry_run: bool) -> dict:
    _check_hr(user)
    rows = _read(content)
    index = _index(rows[0], OPENING_COLUMNS, [k for k, _ in OPENING_COLUMNS])
    errors, plan, seen, years = [], [], set(), set()
    for n, row in enumerate(rows[1:], start=2):
        values = {k: (row[i] if i < len(row) else None) for k, i in index.items()}
        number = _text(values["number"]).upper()
        if not number and not any(_text(values[k]) for k in OPENING_MONEY):
            continue
        try:
            if number in seen:
                raise TakeoverError("the employee appears twice.")
            seen.add(number)
            employee = _employee(user, number)
            last = _month(values["last_month"], "Last pay month paid")
            year = tax_year_of(last)
            try:
                months = int(_text(values["months"]) or "0")
            except ValueError:
                raise TakeoverError("Months paid is a whole number.") from None
            if not 1 <= months <= 12:
                raise TakeoverError("Months paid is 1 to 12.")
            figures = {k: _money(values[k], label) for k, label in OPENING_COLUMNS[3:]}
            here = (
                PayrollLine.objects.filter(
                    employee=employee,
                    run__month__gte=year,
                    run__month__lte=last,
                )
                .exclude(run__status=PayrollRun.Status.REJECTED)
                .first()
            )
            if here is not None:
                raise TakeoverError(
                    f"already in this payroll for pay month {here.run.month:%B %Y}."
                )
            if OpeningFigures.objects.filter(
                employee=employee,
                batch__tax_year=year,
                batch__status__in=[OpeningBatch.Status.APPROVED, OpeningBatch.Status.AWAITING],
            ).exists():
                raise TakeoverError("already has opening figures for that year.")
            years.add(year)
            plan.append((employee, last, months, figures))
        except TakeoverError as error:
            errors.append(f"Row {n} ({number or 'no number'}): {error}")
    if len(years) > 1:
        errors.append("All rows are for one year of assessment (from 1 April).")
    if not plan and not errors:
        errors.append("There are no figures in the file.")
    totals = {k: sum((f[k] for *_, f in plan), ZERO) for k in OPENING_MONEY}
    result = {
        "errors": errors[:50],
        "employees": len(plan),
        "tax_year": f"{min(years):%Y}" if years else "",
        "totals": {k: f"{v:.2f}" for k, v in totals.items()},
        "saved": False,
    }
    if errors or dry_run:
        return result
    year = years.pop()
    with audit_context("payroll_opening_uploaded", file_name), transaction.atomic():
        batch = OpeningBatch.objects.create(
            file_name=(file_name or "opening.xlsx")[:200], tax_year=year, created_by=user
        )
        OpeningFigures.objects.bulk_create(
            OpeningFigures(batch=batch, employee=e, last_month=last, months=months, **f)
            for e, last, months, f in plan
        )
        try:
            approvals.submit(
                user,
                DOC,
                batch.pk,
                created_by=user,
                title=f"Opening payroll figures {year:%Y}/{(year.year + 1) % 100:02d}: "
                f"{len(plan)} employees, gross LKR {totals['gross']:,.2f}",
                link="/payroll-takeover",
            )
        except ApprovalError as error:
            raise TakeoverError(str(error)) from None
    return result | {"saved": True}


def decide_opening(user: User, batch_id, approve: bool, reason: str = "") -> OpeningBatch:
    with transaction.atomic():
        batch = OpeningBatch.objects.select_for_update().filter(pk=batch_id).first()
        if batch is None or batch.status != OpeningBatch.Status.AWAITING:
            raise TakeoverError("These figures are not waiting for approval.")
        try:
            if approve:
                state = approvals.approve(user, DOC, batch.pk, reason)
                if state.status != ApprovalState.Status.APPROVED:
                    return batch
                status = OpeningBatch.Status.APPROVED
            else:
                approvals.reject(user, DOC, batch.pk, reason)
                status = OpeningBatch.Status.REJECTED
        except ApprovalError as error:
            raise TakeoverError(str(error)) from None
        with audit_context(f"payroll_opening_{status}", reason):
            batch.status = status
            batch.decided_at = timezone.now()
            batch.save(update_fields=["status", "decided_at"])
        return batch


def opening(employee: Employee, tax_year: date) -> OpeningFigures | None:
    """The employee's approved figures brought over for a year of assessment."""
    return (
        OpeningFigures.objects.filter(
            employee=employee, batch__tax_year=tax_year, batch__status=OpeningBatch.Status.APPROVED
        )
        .order_by("-batch__decided_at")
        .first()
    )


def opening_gratuity(employee: Employee, before: date) -> Decimal | None:
    """The gratuity provided by the old payroll, if brought over for a month before `before`."""
    found = (
        OpeningFigures.objects.filter(
            employee=employee,
            batch__status=OpeningBatch.Status.APPROVED,
            last_month__lt=before,
        )
        .order_by("-last_month", "-batch__decided_at")
        .first()
    )
    return found.gratuity_provision if found else None


def batches(user: User) -> list[dict]:
    out = []
    for b in OpeningBatch.objects.select_related("created_by")[:20]:
        sums = b.figures.aggregate(
            gross=Sum("gross"), apit=Sum("apit"), gratuity=Sum("gratuity_provision")
        )
        state = approvals.state_of(DOC, b.pk)
        out.append(
            {
                "id": b.pk,
                "file_name": b.file_name,
                "tax_year": f"{b.tax_year:%Y}",
                "employees": b.figures.count(),
                "gross": f"{sums['gross'] or 0:.2f}",
                "apit": f"{sums['apit'] or 0:.2f}",
                "gratuity": f"{sums['gratuity'] or 0:.2f}",
                "status": b.status,
                "status_label": b.get_status_display(),
                "created_by": b.created_by.full_name,
                "created_at": b.created_at,
                "can_decide": b.status == OpeningBatch.Status.AWAITING
                and state is not None
                and approvals.why_not(user, state) is None,
            }
        )
    return out


# --- 4. The parallel run -------------------------------------------------------------------------


def _run(user: User, run_id) -> PayrollRun:
    run = (
        PayrollRun.objects.filter(pk=run_id, division__in=division_scope(user))
        .exclude(status=PayrollRun.Status.REJECTED)
        .select_related("division")
        .first()
    )
    if run is None:
        raise TakeoverError("There is no such payroll.")
    return run


def compare_template(user: User, run_id) -> bytes:
    _check_hr(user)
    run = _run(user, run_id)
    rows = [
        [x.employee.number, x.employee.full_name] + [""] * len(COMPARED)
        for x in run.lines.select_related("employee")
    ]
    return _book(["Employee no", "Name"] + [label for _, label in COMPARED], rows, {1: 28})


def compare(user: User, run_id, content: bytes, file_name: str, *, save: bool) -> dict:
    _check_hr(user)
    run = _run(user, run_id)
    rows = _read(content)
    index = _index(rows[0], [("number", "Employee no"), *COMPARED], ["number", *dict(COMPARED)])
    old: dict[str, dict] = {}
    errors = []
    for n, row in enumerate(rows[1:], start=2):
        values = {k: (row[i] if i < len(row) else None) for k, i in index.items()}
        number = _text(values["number"]).upper()
        if not number:
            continue
        try:
            if number in old:
                raise TakeoverError("the employee appears twice.")
            old[number] = {k: _money(values[k], label) for k, label in COMPARED}
        except TakeoverError as error:
            errors.append(f"Row {n} ({number}): {error}")
    if errors:
        return {"errors": errors[:50], "saved": False}
    lines = {x.employee.number: x for x in run.lines.select_related("employee")}
    people, differences = [], 0
    for number in sorted(set(lines) | set(old)):
        line, theirs = lines.get(number), old.get(number)
        row = {
            "number": number,
            "name": line.employee.full_name if line else "",
            "missing": "here" if line is None else ("old" if theirs is None else ""),
            "figures": [],
        }
        if line is not None and theirs is not None:
            for key, label in COMPARED:
                here, was = getattr(line, key), theirs[key]
                row["figures"].append(
                    {
                        "field": label,
                        "here": f"{here:.2f}",
                        "old": f"{was:.2f}",
                        "difference": f"{here - was:.2f}",
                    }
                )
            row["differs"] = any(f["difference"] != "0.00" for f in row["figures"])
        else:
            row["differs"] = True
        differences += row["differs"]
        people.append(row)
    result = {
        "run": run.pk,
        "title": f"{run.division.code} {run.month:%B %Y}",
        "employees": len(people),
        "differences": differences,
        "people": people,
    }
    if not save:
        return {"errors": [], "saved": False, **result}
    with audit_context("parallel_check_saved", file_name), transaction.atomic():
        check = ParallelCheck.objects.create(
            run=run,
            file_name=(file_name or "old-payroll.xlsx")[:200],
            result=result,
            differences=differences,
            created_by=user,
        )
    return {"errors": [], "saved": True, "id": check.pk, **result}


def sign_off(user: User, check_id, note: str = "") -> ParallelCheck:
    note = " ".join((note or "").split())
    if not changes.is_director(user):
        raise TakeoverError("The Director signs off the parallel run.")
    with transaction.atomic():
        check = ParallelCheck.objects.select_for_update().filter(pk=check_id).first()
        if check is None:
            raise TakeoverError("There is no such comparison.")
        if check.signed_off_at is not None:
            raise TakeoverError("This comparison is already signed off.")
        if check.created_by_id == user.pk:
            raise TakeoverError("The person who uploaded the old figures does not sign them off.")
        if check.differences and not note:
            raise TakeoverError(
                f"There are {check.differences} differences: say why they are accepted."
            )
        with audit_context("parallel_run_signed_off", note):
            check.signed_off_by, check.signed_off_at, check.note = user, timezone.now(), note[:300]
            check.save(update_fields=["signed_off_by", "signed_off_at", "note"])
        return check


def checks(user: User) -> list[dict]:
    return [
        {
            "id": c.pk,
            "run": c.run_id,
            "title": c.result.get("title", ""),
            "file_name": c.file_name,
            "employees": c.result.get("employees", 0),
            "differences": c.differences,
            "people": c.result.get("people", []),
            "created_by": c.created_by.full_name,
            "created_at": c.created_at,
            "signed_off_by": c.signed_off_by.full_name if c.signed_off_by_id else "",
            "signed_off_at": c.signed_off_at,
            "note": c.note,
            "can_sign_off": c.signed_off_at is None
            and changes.is_director(user)
            and c.created_by_id != user.pk,
        }
        for c in ParallelCheck.objects.select_related("created_by", "signed_off_by")[:20]
    ]
