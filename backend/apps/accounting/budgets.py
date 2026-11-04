"""Budgets (backlog P2-22, spec 3.4 and 6).

- A budget covers one financial year (from the month in Settings → Organisation, April by
  default) and holds, per income or cost account, division and month, the amount expected in
  LKR. Income and costs are both typed as positive amounts.
- The Accountant prepares it on the page or imports it from Excel (the same layout as the
  export: Account, Division, then one column per month), and sends it to the Director, who
  approves it (approval engine, "budget"; never the person who prepared it).
- An approved budget never changes. A revision is a new version of the year, started from
  the approved one; once approved it replaces it. Only one version of a year is open at a time.
- The profit and loss shows each account's budget for the months of the period next to the
  actual, with the difference and the %. The difference is shown so that a positive figure is
  better than budget: more income, or lower costs.
"""

import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Max, QuerySet, Sum
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from apps.core import approvals
from apps.core.access import effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, Company, Division, User

from . import services
from .catalogue import PROFIT_AND_LOSS, TYPES, section_of
from .models import Account, Budget, BudgetLine

DOC = "budget"
ZERO = Decimal("0")
CENT = Decimal("0.01")
MAX_BYTES = 5 * 1024 * 1024
INCOME_TYPES = {"income", "other_income"}
St = Budget.Status


class BudgetError(Exception):
    pass


def can_view(user: User) -> bool:
    return effective_access(user).has("accounting", "view")


def can_manage(user: User) -> bool:
    return effective_access(user).has("accounting", "enter")


def _accountant(user: User) -> None:
    if not can_manage(user):
        raise BudgetError("Only the Accountant prepares budgets.")


# --- The financial year ----------------------------------------------------------------------


def start_month() -> int:
    company = Company.objects.filter(pk=1).first()
    return company.financial_year_start_month if company else 4


def year_start_of(day: date) -> date:
    """The first day of the financial year `day` falls in."""
    first = start_month()
    year = day.year if day.month >= first else day.year - 1
    return date(year, first, 1)


def months(year_start: date) -> list[date]:
    out, day = [], year_start
    for _ in range(12):
        out.append(day)
        day = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return out


def label(year_start: date) -> str:
    if year_start.month == 1:
        return str(year_start.year)
    return f"{year_start.year}-{(year_start.year + 1) % 100:02d}"


def budget_accounts() -> QuerySet[Account]:
    types = [code for code, (_, section, _) in TYPES.items() if section == PROFIT_AND_LOSS]
    return Account.objects.filter(account_type__in=types, is_active=True, merged_into=None)


# --- Preparing -------------------------------------------------------------------------------


@dataclass
class LineInput:
    account: Account
    division: Division
    month: date
    amount: Decimal


def start(user: User, year: int, notes: str = "") -> Budget:
    """A new draft for the financial year starting in `year`. When the year has an approved
    budget the draft is its revision and starts as a copy of it."""
    _accountant(user)
    year_start = date(int(year), start_month(), 1)
    with audit_context("budget_started"), transaction.atomic():
        existing = Budget.objects.select_for_update().filter(year_start=year_start)
        if existing.filter(status__in=[St.DRAFT, St.AWAITING_APPROVAL]).exists():
            raise BudgetError(
                f"The {label(year_start)} budget already has a version being prepared."
            )
        version = (existing.aggregate(v=Max("version"))["v"] or 0) + 1
        approved = existing.filter(status=St.APPROVED).first()
        budget = Budget.objects.create(
            year_start=year_start,
            version=version,
            notes=(notes or "").strip()[:500],
            created_by=user,
        )
        if approved is not None:
            BudgetLine.objects.bulk_create(
                BudgetLine(
                    budget=budget,
                    account_id=x.account_id,
                    division_id=x.division_id,
                    month=x.month,
                    amount=x.amount,
                )
                for x in approved.lines.all()
            )
        return budget


def _draft(user: User, budget: Budget) -> Budget:
    _accountant(user)
    budget = Budget.objects.select_for_update().get(pk=budget.pk)
    if budget.status != St.DRAFT:
        raise BudgetError("Only a draft budget is changed.")
    if budget.created_by_id != user.pk:
        raise BudgetError("Only the person who started this version changes it.")
    return budget


def _check(budget: Budget, given: list[LineInput]) -> dict[tuple, Decimal]:
    allowed = set(months(budget.year_start))
    out: dict[tuple, Decimal] = {}
    for line in given:
        if section_of(line.account.account_type) != PROFIT_AND_LOSS:
            raise BudgetError(f"{line.account.name} is not an income or cost account.")
        if not line.account.is_active or line.account.merged_into_id:
            raise BudgetError(f"{line.account.name} is not active.")
        if not line.division.is_active:
            raise BudgetError(f"Division {line.division.code} is deactivated.")
        if line.month not in allowed:
            raise BudgetError(f"{line.month:%b %Y} is not in the {label(budget.year_start)} year.")
        amount = Decimal(line.amount)
        if amount != amount.quantize(CENT) or not amount.is_finite():
            raise BudgetError(f"{line.account.name}: amounts are to the cent.")
        key = (line.account.pk, line.division.pk, line.month)
        out[key] = out.get(key, ZERO) + amount
    return {k: v for k, v in out.items() if v}


def save_lines(user: User, budget: Budget, given: list[LineInput], notes=None) -> Budget:
    """Replace the draft's lines with `given` (zero amounts are left out)."""
    with audit_context("budget_changed"), transaction.atomic():
        budget = _draft(user, budget)
        checked = _check(budget, given)
        budget.lines.all().delete()
        BudgetLine.objects.bulk_create(
            BudgetLine(budget=budget, account_id=a, division_id=d, month=m, amount=v)
            for (a, d, m), v in checked.items()
        )
        if notes is not None:
            budget.notes = str(notes).strip()[:500]
            budget.save(update_fields=["notes"])
        return budget


def discard(user: User, budget: Budget) -> None:
    with audit_context("budget_discarded"), transaction.atomic():
        budget = _draft(user, budget)
        if approvals.state_of(DOC, budget.pk) is not None:
            raise BudgetError("A budget sent for approval is kept; it can be rejected instead.")
        budget.delete()


# --- Excel -----------------------------------------------------------------------------------


def _grid(budget: Budget) -> list[dict]:
    """The budget as rows of account and division with an amount per month."""
    rows: dict[tuple, dict] = {}
    lines = budget.lines.select_related("account", "division").order_by(
        "account__number", "account__name", "division__code", "month"
    )
    for line in lines:
        key = (line.account_id, line.division_id)
        row = rows.setdefault(
            key, {"account": line.account, "division": line.division, "amounts": {}}
        )
        row["amounts"][line.month] = line.amount
    return list(rows.values())


def export_workbook(budget: Budget) -> bytes:
    """The budget in the import layout. An empty budget lists every income and cost account,
    for the Accountant to fill in the division and the months."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Budget"
    year = months(budget.year_start)
    sheet.append(["Account", "Account name", "Division", *[f"{m:%b %Y}" for m in year]])
    grid = _grid(budget)
    if grid:
        for row in grid:
            a = row["account"]
            sheet.append(
                [
                    a.number or a.name,
                    a.name,
                    row["division"].code,
                    *[row["amounts"].get(m) for m in year],
                ]
            )
    else:
        for a in budget_accounts().order_by("account_type", "number", "name"):
            sheet.append([a.number or a.name, a.name, ""])
    for column, width in zip("ABC", (14, 36, 10), strict=True):
        sheet.column_dimensions[column].width = width
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _month_of(value, year: list[date]) -> date | None:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        day = value.replace(day=1)
        return day if day in year else None
    text = " ".join(str(value or "").replace("-", " ").replace("/", " ").split())
    if not text:
        return None
    for fmt in ("%b %Y", "%B %Y", "%Y %m", "%b %y", "%B %y", "%m %Y"):
        try:
            day = datetime.strptime(text, fmt).date().replace(day=1)
        except ValueError:
            continue
        return day if day in year else None
    for fmt in ("%b", "%B"):
        try:
            number = datetime.strptime(text, fmt).month
        except ValueError:
            continue
        return next((m for m in year if m.month == number), None)
    return None


def _name(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value if value is not None else "").split())


def parse(budget: Budget, content: bytes) -> list[LineInput]:
    """The lines of an Excel file in the export layout. Rows whose months are all empty are
    skipped. All or nothing: any row refused stops the import, with every reason listed."""
    from apps.banking.parsing import StatementFileError, money

    if len(content) > MAX_BYTES:
        raise BudgetError("The file is larger than 5 MB.")
    try:
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, OSError, KeyError, ValueError):
        raise BudgetError("The file is not an Excel workbook (.xlsx).") from None
    rows = [list(r) for r in book.worksheets[0].iter_rows(values_only=True)]
    year = months(budget.year_start)
    head_at, head = None, []
    for at, row in enumerate(rows[:20]):
        names = [_name(c).lower() for c in row]
        if "account" in names and "division" in names:
            head_at, head = at, row
            break
    if head_at is None:
        raise BudgetError("No heading row with Account and Division was found.")
    names = [_name(c).lower() for c in head]
    account_col, division_col = names.index("account"), names.index("division")
    month_cols = {i: m for i, c in enumerate(head) if (m := _month_of(c, year)) is not None}
    if not month_cols:
        raise BudgetError(f"No column is a month of the {label(budget.year_start)} year.")
    accounts = list(budget_accounts())
    by_number = {a.number.upper(): a for a in accounts if a.number}
    by_name = {a.name.lower(): a for a in accounts}
    divisions = {d.code.upper(): d for d in Division.objects.filter(is_active=True)}
    lines, errors = [], []
    for at, row in enumerate(rows[head_at + 1 :], start=head_at + 2):
        cells = list(row) + [None] * len(head)
        amounts = {}
        try:
            for i, month in month_cols.items():
                value = money(cells[i], where=f"{month:%b %Y}: ")
                if value:
                    amounts[month] = value
        except StatementFileError as error:
            errors.append(f"Row {at}: {error}")
            continue
        if not amounts:
            continue
        key = _name(cells[account_col])
        account = by_number.get(key.upper()) or by_name.get(key.lower())
        division = divisions.get(_name(cells[division_col]).upper())
        if account is None:
            errors.append(f"Row {at}: no active income or cost account {key or '(empty)'}.")
            continue
        if division is None:
            errors.append(f"Row {at}: give an active division code, such as WS, IM or HO.")
            continue
        lines += [LineInput(account, division, m, v) for m, v in amounts.items()]
    if errors:
        raise BudgetError(" ".join(errors[:20]))
    if not lines:
        raise BudgetError("The file has no amounts.")
    return lines


def import_file(user: User, budget: Budget, content: bytes) -> Budget:
    lines = parse(budget, content)
    with audit_context("budget_imported"):
        return save_lines(user, budget, lines)


# --- Approval --------------------------------------------------------------------------------


def total(budget: Budget, kind: str) -> Decimal:
    """Income or cost total of the budget, as typed."""
    lines = budget.lines.all()
    lines = (
        lines.filter(account__account_type__in=INCOME_TYPES)
        if kind == "income"
        else lines.exclude(account__account_type__in=INCOME_TYPES)
    )
    return lines.aggregate(t=Sum("amount"))["t"] or ZERO


def submit(user: User, budget: Budget, comment: str = "") -> Budget:
    with audit_context("budget_submitted", comment), transaction.atomic():
        budget = _draft(user, budget)
        if not budget.lines.exists():
            raise BudgetError("The budget has no amounts.")
        try:
            approvals.submit(
                user,
                DOC,
                budget.pk,
                created_by=budget.created_by,
                amount=total(budget, "cost"),
                comment=comment,
                title=f"Budget {label(budget.year_start)} (version {budget.version})",
                link=f"/budgets/{budget.pk}",
            )
        except ApprovalError as error:
            raise BudgetError(str(error)) from None
        budget.status = St.AWAITING_APPROVAL
        budget.save(update_fields=["status"])
        return budget


def _waiting(budget: Budget) -> Budget:
    budget = Budget.objects.select_for_update().get(pk=budget.pk)
    if budget.status != St.AWAITING_APPROVAL:
        raise BudgetError("The budget is not waiting for approval.")
    return budget


def approve(user: User, budget: Budget, comment: str = "") -> Budget:
    with transaction.atomic():
        budget = _waiting(budget)
        try:
            state = approvals.approve(user, DOC, budget.pk, comment)
        except ApprovalError as error:
            raise BudgetError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("budget_approved", comment):
                Budget.objects.filter(year_start=budget.year_start, status=St.APPROVED).update(
                    status=St.REPLACED
                )
                budget.status = St.APPROVED
                budget.approved_at = timezone.now()
                budget.save(update_fields=["status", "approved_at"])
        return budget


def send_back(user: User, budget: Budget, reason: str) -> Budget:
    with transaction.atomic():
        budget = _waiting(budget)
        try:
            approvals.send_back(user, DOC, budget.pk, reason)
        except ApprovalError as error:
            raise BudgetError(str(error)) from None
        with audit_context("budget_returned", reason):
            budget.status = St.DRAFT
            budget.save(update_fields=["status"])
        return budget


def reject(user: User, budget: Budget, reason: str) -> Budget:
    with transaction.atomic():
        budget = _waiting(budget)
        try:
            approvals.reject(user, DOC, budget.pk, reason)
        except ApprovalError as error:
            raise BudgetError(str(error)) from None
        with audit_context("budget_rejected", reason):
            budget.status = St.REJECTED
            budget.save(update_fields=["status"])
        return budget


def can_approve(user: User, budget: Budget) -> bool:
    if budget.status != St.AWAITING_APPROVAL:
        return False
    state = approvals.state_of(DOC, budget.pk)
    return state is not None and approvals.why_not(user, state) is None


# --- Budget against actual ------------------------------------------------------------------


def budgeted(date_from: date, date_to: date, division: Division | None = None) -> dict:
    """{account id: budget} from the approved budgets for the months from `date_from`'s to
    `date_to`'s, signed as the profit and loss is: income positive, costs negative."""
    lines = BudgetLine.objects.filter(
        budget__status=St.APPROVED,
        month__gte=date_from.replace(day=1),
        month__lte=date_to.replace(day=1),
    )
    if division is not None:
        lines = lines.filter(division=division)
    totals: dict[int, Decimal] = {}
    for row in lines.values("account", "account__account_type").annotate(t=Sum("amount")):
        sign = 1 if row["account__account_type"] in INCOME_TYPES else -1
        totals[row["account"]] = sign * row["t"]
    return services.roll_up(totals)


def compare(actual: Decimal, budget: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    """The difference (positive is better than budget) and it as a % of the budget."""
    if budget is None:
        return None, None
    difference = actual - budget
    if not budget:
        return difference, None
    percent = (difference / abs(budget) * 100).quantize(Decimal("0.1"))
    return difference, percent
