"""Employees' pay settings approved by the Director (backlog P2B-17; owner, 5 Nov 2026).

- HR (the HR and Payroll Officer, owner's follow-up 3) prepares a **pay change** for one
  employee: the pay month it starts from, the reason, new monthly amounts (0 ends a
  component) with the employee's own EPF/ETF and APIT marks where they differ from the
  component's (follow-up 7), and, if wanted, the employee's settings: normal day, grace,
  overtime rates (instead of the division's work rule), annual and casual-and-sick leave days
  (instead of the category's) and the APIT table (primary or secondary employment).
- The first change of an employee is marked "new employee". The attendance bonus (ATTEND,
  default LKR 1,500) is an amount like the others; an employee has **at most four
  allowances** at a time (components marked as allowances).
- Draft → sent to the Director (approval engine, "pay_change") → approved, returned (back to
  a draft) or rejected. HR may withdraw it until it is decided. Nobody approves a change they
  prepared (rule 5). Only on approval do the amounts (PayRate) and settings (EmployeeSetting)
  take effect; a decided change never changes (database).
- An approved amount or setting for a pay month that has not yet come is replaced by a later
  approved change for the same month; one in force never changes.
- One open change per employee at a time keeps the picture simple.

Gratuity settings (entered by the Accountant, follow-up 9) come with the gratuity itself
(P2B-07).
"""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.core import approvals
from apps.core.access import effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User

from . import employees, pay, periods
from .models import (
    SETTING_FIELDS,
    Employee,
    EmployeeSetting,
    PayChange,
    PayChangeLine,
    PayComponent,
    PayRate,
    PayrollRun,
)

DOC = "pay_change"
MAX_ALLOWANCES = 4
OPEN = (PayChange.Status.DRAFT, PayChange.Status.AWAITING)
St = PayChange.Status


class ChangeError(Exception):
    pass


# --- Settings in force --------------------------------------------------------------------------


def can_prepare(user: User) -> bool:
    return employees.can_edit(user)


def can_approve(user: User, change: PayChange) -> bool:
    if change.status != St.AWAITING:
        return False
    state = approvals.state_of(DOC, change.pk)
    return state is not None and approvals.why_not(user, state) is None


# --- Preparing -----------------------------------------------------------------------------------


def _flag(value) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("default", "same"):
            return None
        return text in ("1", "true", "yes", "y")
    return bool(value)


def _number(value, label: str, places: str, low: Decimal, high: Decimal) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ChangeError(f"The {label} is a number.") from None
    if not number.is_finite() or number < low or number > high:
        raise ChangeError(f"The {label} is from {low} to {high}.")
    if number != number.quantize(Decimal(places)):
        raise ChangeError(f"The {label} has too many decimal places.")
    return number.quantize(Decimal(places))


def _days(value, label: str) -> Decimal | None:
    days = _number(value, label, "0.1", Decimal(0), Decimal(60))
    if days is not None and (days * 2) % 1:
        raise ChangeError(f"The {label} is in whole or half days.")
    return days


def _minutes(value, label: str, high: int) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(str(value).strip())
    except ValueError:
        raise ChangeError(f"The {label} is a whole number of minutes.") from None
    if not 0 <= number <= high:
        raise ChangeError(f"The {label} is from 0 to {high} minutes.")
    return number


def _settings(values: dict) -> dict:
    out = {
        "normal_day_minutes": _minutes(values.get("normal_day_minutes"), "normal day", 960),
        "grace_minutes": _minutes(values.get("grace_minutes"), "grace", 120),
        "annual_leave_days": _days(values.get("annual_leave_days"), "annual leave"),
        "casual_leave_days": _days(values.get("casual_leave_days"), "casual and sick leave"),
    }
    if out["normal_day_minutes"] == 0:
        raise ChangeError("The normal day is more than 0 minutes.")
    for field, label in (
        ("rate_working_day", "overtime rate on a working day"),
        ("rate_sunday", "overtime rate on a Sunday"),
        ("rate_holiday", "overtime rate on a holiday"),
    ):
        out[field] = _number(values.get(field), label, "0.01", Decimal(1), Decimal(5))
    apit = values.get("apit") or EmployeeSetting.Apit.PRIMARY
    if apit not in EmployeeSetting.Apit.values:
        raise ChangeError("Choose the APIT table: primary or secondary employment.")
    out["apit"] = apit
    return out


def _lines(values) -> list[dict]:
    if not isinstance(values, list):
        raise ChangeError("Give the amounts as a list.")
    lines, seen = [], set()
    for item in values:
        if not isinstance(item, dict):
            raise ChangeError("Give each amount with its component.")
        code = str(item.get("component") or "").strip().upper()
        if item.get("amount") in (None, ""):
            continue  # left blank: unchanged
        component = PayComponent.objects.filter(code=code).first()
        if component is None:
            raise ChangeError(f"There is no pay component {code}.")
        if code in seen:
            raise ChangeError(f"{component.name} is given twice.")
        seen.add(code)
        if not component.is_active:
            raise ChangeError(f"{component.name} is no longer used.")
        try:
            amount = pay._amount(item.get("amount"))
        except pay.PayError as error:
            raise ChangeError(f"{component.name}: {error}") from None
        epf, apit = _flag(item.get("epf_liable")), _flag(item.get("apit_taxable"))
        if component.kind == PayComponent.Kind.DEDUCTION and (epf or apit):
            raise ChangeError(
                f"{component.name} is a deduction: it counts for neither EPF nor APIT."
            )
        lines.append({"component": component, "amount": amount, "epf": epf, "apit": apit})
    return lines


def _employee(user: User, employee: Employee) -> Employee:
    if not can_prepare(user):
        raise ChangeError("Only HR prepares pay changes.")
    found = employees.visible(user).filter(pk=employee.pk).first()
    if found is None:
        raise ChangeError("This employee is not in one of your divisions.")
    if not found.is_active:
        raise ChangeError("This employee has left; their pay is kept as it was.")
    return found


def _fill(change: PayChange, values: dict) -> list[dict]:
    try:
        change.effective_from = pay.month_of(values.get("effective_from"))
    except pay.PayError as error:
        raise ChangeError(str(error)) from None
    if change.effective_from < periods.pay_month_of(change.employee.join_date):
        raise ChangeError("The pay month is before the employee joined.")
    reason = " ".join(str(values.get("reason") or "").split())
    if not reason:
        raise ChangeError("Give the reason (for example: joined, annual increment, promotion).")
    change.reason = reason[:200]
    settings = values.get("settings")
    change.has_settings = isinstance(settings, dict)
    for field, value in (_settings(settings) if change.has_settings else {}).items():
        setattr(change, field, value)
    if not change.has_settings:
        for field in SETTING_FIELDS:
            setattr(change, field, None if field != "apit" else EmployeeSetting.Apit.PRIMARY)
    lines = _lines(values.get("lines") or [])
    if not lines and not change.has_settings:
        raise ChangeError("The change has no amounts and no settings.")
    return lines


def _save_lines(change: PayChange, lines: list[dict]) -> None:
    change.lines.all().delete()
    PayChangeLine.objects.bulk_create(
        PayChangeLine(
            change=change,
            component=x["component"],
            amount=x["amount"],
            epf_liable=x["epf"],
            apit_taxable=x["apit"],
        )
        for x in lines
    )


def prepare(user: User, employee: Employee, values: dict) -> PayChange:
    employee = _employee(user, employee)
    with audit_context("pay_change_prepared", values.get("reason", "")), transaction.atomic():
        if PayChange.objects.filter(employee=employee, status__in=OPEN).exists():
            raise ChangeError(
                f"{employee.full_name} already has a pay change waiting; finish or withdraw it."
            )
        change = PayChange(employee=employee, created_by=user)
        change.is_new_employee = not PayChange.objects.filter(
            employee=employee, status=St.APPROVED
        ).exists()
        lines = _fill(change, values)
        change.save()
        _save_lines(change, lines)
        return change


def _locked(change: PayChange, *statuses) -> PayChange:
    change = PayChange.objects.select_for_update().get(pk=change.pk)
    if change.status not in statuses:
        raise ChangeError(f"The pay change is {change.get_status_display().lower()}.")
    return change


def edit(user: User, change: PayChange, values: dict) -> PayChange:
    _employee(user, change.employee)
    with audit_context("pay_change_edited", values.get("reason", "")), transaction.atomic():
        change = _locked(change, St.DRAFT)
        if change.created_by_id != user.pk:
            raise ChangeError("Only the person who prepared the change edits it.")
        lines = _fill(change, values)
        change.save()
        _save_lines(change, lines)
        return change


def _allowances_after(change: PayChange) -> int:
    """How many allowances the employee would have from the change's pay month on."""
    current = {
        x.component.pk: x.amount
        for x in pay.amounts_on(change.employee, change.effective_from)
        if x.component.is_allowance
    }
    for line in change.lines.select_related("component"):
        if line.component.is_allowance:
            current[line.component_id] = line.amount
    later = PayRate.objects.filter(
        employee=change.employee, effective_from__gt=change.effective_from, amount__gt=0
    ).filter(component__is_allowance=True)
    return len([1 for amount in current.values() if amount > 0]) + len(
        {r.component_id for r in later if r.component_id not in current}
    )


def _check(change: PayChange) -> None:
    paid = (
        PayrollRun.objects.filter(
            division_id=change.employee.division_id, status=PayrollRun.Status.APPROVED
        )
        .order_by("-month")
        .first()
    )
    if paid and change.effective_from <= paid.month:
        raise ChangeError(
            f"Pay month {paid.month:%B %Y} is already paid (approved payroll); a change starts "
            "from a later pay month."
        )
    if _allowances_after(change) > MAX_ALLOWANCES:
        raise ChangeError(
            f"An employee has at most {MAX_ALLOWANCES} allowances; end one before adding another."
        )
    today = timezone.localdate()
    for line in change.lines.select_related("component"):
        taken = PayRate.objects.filter(
            employee=change.employee,
            component=line.component,
            effective_from=change.effective_from,
            effective_from__lte=today,
        ).exists()
        if taken:
            raise ChangeError(
                f"{line.component.name} already has an amount in force from "
                f"{change.effective_from:%B %Y}; choose a later pay month."
            )
        if line.amount == 0 and (
            pay.current_amount(change.employee, line.component, change.effective_from) is None
        ):
            raise ChangeError(f"{change.employee.full_name} has no {line.component.name} to end.")
    if (
        change.has_settings
        and EmployeeSetting.objects.filter(
            employee=change.employee,
            effective_from=change.effective_from,
            effective_from__lte=today,
        ).exists()
    ):
        raise ChangeError(
            f"Settings from {change.effective_from:%B %Y} are in force; choose a later pay month."
        )


def submit(user: User, change: PayChange, comment: str = "") -> PayChange:
    _employee(user, change.employee)
    with audit_context("pay_change_submitted", comment), transaction.atomic():
        change = _locked(change, St.DRAFT)
        _check(change)
        employee = change.employee
        what = "New employee" if change.is_new_employee else "Pay change"
        try:
            approvals.submit(
                user,
                DOC,
                change.pk,
                created_by=change.created_by,
                division=employee.division,
                comment=comment,
                title=f"{what}: {employee.number} {employee.full_name}, "
                f"from {change.effective_from:%B %Y}",
                link=f"/employees/{employee.pk}",
            )
        except ApprovalError as error:
            raise ChangeError(str(error)) from None
        change.status = St.AWAITING
        change.save(update_fields=["status"])
        return change


# --- Deciding ------------------------------------------------------------------------------------


def _apply(change: PayChange) -> None:
    """The Director approved: the amounts and settings take effect (replacing any approved for
    the same pay month that has not yet come)."""
    employee, start = change.employee, change.effective_from
    for line in change.lines.select_related("component"):
        PayRate.objects.filter(
            employee=employee, component=line.component, effective_from=start
        ).delete()
        PayRate.objects.create(
            employee=employee,
            component=line.component,
            effective_from=start,
            amount=line.amount,
            epf_liable=line.epf_liable,
            apit_taxable=line.apit_taxable,
            change=change,
            reason=change.reason,
            created_by=change.created_by,
        )
    if change.has_settings:
        EmployeeSetting.objects.filter(employee=employee, effective_from=start).delete()
        EmployeeSetting.objects.create(
            employee=employee,
            effective_from=start,
            change=change,
            **{field: getattr(change, field) for field in SETTING_FIELDS},
        )


def approve(user: User, change: PayChange, comment: str = "") -> PayChange:
    with transaction.atomic():
        change = _locked(change, St.AWAITING)
        try:
            state = approvals.approve(user, DOC, change.pk, comment)
        except ApprovalError as error:
            raise ChangeError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("pay_change_approved", comment):
                _check(change)
                _apply(change)
                change.status = St.APPROVED
                change.approved_at = timezone.now()
                change.save(update_fields=["status", "approved_at"])
        return change


def send_back(user: User, change: PayChange, reason: str) -> PayChange:
    with transaction.atomic():
        change = _locked(change, St.AWAITING)
        try:
            approvals.send_back(user, DOC, change.pk, reason)
        except ApprovalError as error:
            raise ChangeError(str(error)) from None
        with audit_context("pay_change_returned", reason):
            change.status = St.DRAFT
            change.save(update_fields=["status"])
        return change


def reject(user: User, change: PayChange, reason: str) -> PayChange:
    with transaction.atomic():
        change = _locked(change, St.AWAITING)
        try:
            approvals.reject(user, DOC, change.pk, reason)
        except ApprovalError as error:
            raise ChangeError(str(error)) from None
        with audit_context("pay_change_rejected", reason):
            change.status = St.REJECTED
            change.save(update_fields=["status"])
        return change


def withdraw(user: User, change: PayChange, reason: str) -> PayChange:
    _employee(user, change.employee)
    reason = " ".join((reason or "").split())
    if not reason:
        raise ChangeError("Give the reason for withdrawing the change.")
    with audit_context("pay_change_withdrawn", reason), transaction.atomic():
        change = _locked(change, St.DRAFT, St.AWAITING)
        if approvals.state_of(DOC, change.pk) is not None:
            approvals.withdraw(user, DOC, change.pk, reason)
        change.status = St.WITHDRAWN
        change.save(update_fields=["status"])
        return change


def is_director(user: User) -> bool:
    return effective_access(user).has("hr_payroll", "approve")
