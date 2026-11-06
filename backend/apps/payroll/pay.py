"""Pay structure (backlog P2B-02).

- Pay components: the earnings and deductions on a payslip, each marked as counting for EPF
  and ETF or not, and taxable for APIT or not. HR (HR and payroll: Manage) keeps the list;
  a component's code and kind never change, and one no longer used is deactivated.
- Each employee's monthly amount of a component is dated from the 1st of a month. A raise is
  a new amount from its month; earlier months keep the old amount (rule 11). An amount of 0
  ends the component. Amounts are never changed; one whose month has not yet come may be
  withdrawn (the database refuses anything else).
- Amounts are seen by HR and the Director, like the rest of the employee (P2B-01). The
  payroll (P2B-06) reads `amounts_on` for the month it pays, and refuses months already paid.
- Since P2B-17 (owner, 5 Nov 2026) amounts take effect only through a pay change the Director
  approves (changes.py); `add_rate` below is no longer offered to HR directly. An amount may
  carry the employee's own EPF/APIT marks, which then replace the component's.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import User

from . import employees
from .models import Employee, PayComponent, PayRate

CODE = re.compile(r"^[A-Z][A-Z0-9_-]{0,19}$")
CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("9999999999999999.99")


class PayError(Exception):
    pass


def can_manage_components(user: User) -> bool:
    return effective_access(user).has("hr_payroll", "manage")


# --- Components --------------------------------------------------------------------------------


def _flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y")
    return bool(value)


def save_component(
    user: User, values: dict, current: PayComponent | None = None, reason: str = ""
) -> PayComponent:
    if not can_manage_components(user):
        raise PayError("Only HR keeps the pay components.")
    reason = " ".join((reason or "").split())
    if current is not None and not reason:
        raise PayError("Give a reason for changing a pay component.")
    component = current or PayComponent(created_by=user)
    if current is None:
        code = str(values.get("code") or "").strip().upper()
        if not CODE.match(code):
            raise PayError(
                "The code is 1 to 20 capital letters, digits, _ or -, starting with a letter."
            )
        kind = values.get("kind")
        if kind not in PayComponent.Kind.values:
            raise PayError("Choose earning or deduction.")
        component.code, component.kind = code, kind
    else:
        for field in ("code", "kind"):
            if (
                field in values
                and str(values[field]).strip().lower() != str(getattr(current, field)).lower()
            ):
                raise PayError("A pay component's code and kind never change.")
    if current is None or "name" in values:
        name = " ".join(str(values.get("name") or "").split())
        if not name:
            raise PayError("The name is required.")
        component.name = name[:100]
    if current is None or "basis" in values:
        basis = values.get("basis") or PayComponent.Basis.FIXED
        if basis not in PayComponent.Basis.values:
            raise PayError("Choose fixed each month or entered each month.")
        component.basis = basis
    for field in ("epf_liable", "apit_taxable", "is_allowance", "in_day_rate", "is_active"):
        if field in values:
            setattr(component, field, _flag(values[field]))
    if "sort_order" in values:
        try:
            component.sort_order = max(0, min(999, int(values["sort_order"])))
        except (TypeError, ValueError):
            raise PayError("The order is a whole number.") from None
    if component.kind == PayComponent.Kind.DEDUCTION and (
        component.epf_liable or component.apit_taxable
    ):
        raise PayError("A deduction does not count for EPF or APIT; only earnings do.")
    event = "pay_component_added" if current is None else "pay_component_changed"
    try:
        with audit_context(event, reason), transaction.atomic():
            component.save()
    except IntegrityError:
        raise PayError(f"The code {component.code} is taken.") from None
    return component


# --- Employees' amounts ------------------------------------------------------------------------


def month_of(value) -> date:
    """The 1st of the month given as 'YYYY-MM', 'YYYY-MM-DD' or a date."""
    if isinstance(value, date):
        day = value
    else:
        text = str(value or "").strip()
        match = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$", text)
        if not match:
            raise PayError("Give the month the amount starts from (for example 2026-12).")
        try:
            day = date(int(match[1]), int(match[2]), int(match[3] or 1))
        except ValueError:
            raise PayError(f"{text} is not a date.") from None
    if day.day != 1:
        raise PayError("An amount starts on the 1st of a month.")
    return day


def _amount(value) -> Decimal:
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise PayError("The amount is a number, for example 45000.00.") from None
    if not amount.is_finite() or amount < 0 or amount > MAX_AMOUNT:
        raise PayError("The amount is 0 or more (0 ends the component).")
    if amount != amount.quantize(CENT):
        raise PayError("The amount has at most 2 decimal places.")
    return amount.quantize(CENT)


def add_rate(
    user: User, employee: Employee, component: PayComponent, month, amount, reason: str
) -> PayRate:
    if not employees.can_edit(user):
        raise PayError("Only HR enters pay amounts.")
    employee = employees.visible(user).filter(pk=employee.pk).first()  # as saved now
    if employee is None:
        raise PayError("This employee is not in one of your divisions.")
    if not employee.is_active:
        raise PayError("This employee has left; their pay is kept as it was.")
    if not component.is_active:
        raise PayError(f"{component.name} is no longer used.")
    start = month_of(month)
    if start < employee.join_date.replace(day=1):
        raise PayError("The month is before the employee joined.")
    value = _amount(amount)
    reason = " ".join((reason or "").split())
    if not reason:
        raise PayError("Give the reason (for example: joined, annual increment, promotion).")
    if value == 0 and current_amount(employee, component, start) is None:
        raise PayError(f"{employee.full_name} has no {component.name} to end.")
    try:
        with audit_context("pay_amount_added", reason), transaction.atomic():
            return PayRate.objects.create(
                employee=employee,
                component=component,
                effective_from=start,
                amount=value,
                reason=reason[:200],
                created_by=user,
            )
    except IntegrityError:
        raise PayError(
            f"{component.name} already has an amount from {start:%B %Y}. "
            "Withdraw it first if that month has not yet come."
        ) from None


def withdraw_rate(user: User, rate: PayRate, reason: str) -> None:
    if not employees.can_edit(user):
        raise PayError("Only HR withdraws pay amounts.")
    if not employees.visible(user).filter(pk=rate.employee_id).exists():
        raise PayError("This employee is not in one of your divisions.")
    if rate.effective_from <= timezone.localdate():
        raise PayError("This amount has taken effect; enter a new amount from a later month.")
    reason = " ".join((reason or "").split())
    if not reason:
        raise PayError("Give the reason for withdrawing the amount.")
    with audit_context("pay_amount_withdrawn", reason), transaction.atomic():
        rate.delete()


def current_amount(employee: Employee, component: PayComponent, day: date) -> Decimal | None:
    rate = (
        PayRate.objects.filter(employee=employee, component=component, effective_from__lte=day)
        .order_by("-effective_from")
        .first()
    )
    return None if rate is None else rate.amount


@dataclass
class Line:
    component: PayComponent
    amount: Decimal
    rate: PayRate

    @property
    def epf_liable(self) -> bool:
        """The employee's own mark if set (P2B-17), otherwise the component's."""
        own = self.rate.epf_liable
        return self.component.epf_liable if own is None else own

    @property
    def apit_taxable(self) -> bool:
        own = self.rate.apit_taxable
        return self.component.apit_taxable if own is None else own


def amounts_on(employee: Employee, day: date) -> list[Line]:
    """The amounts in force on `day`, one per component (components ended with 0 left out)."""
    latest: dict[int, PayRate] = {}
    rates = (
        PayRate.objects.filter(employee=employee, effective_from__lte=day)
        .select_related("component")
        .order_by("component_id", "-effective_from")
    )
    for rate in rates:
        latest.setdefault(rate.component_id, rate)
    lines = [Line(r.component, r.amount, r) for r in latest.values() if r.amount > 0]
    key = {PayComponent.Kind.EARNING: 0, PayComponent.Kind.DEDUCTION: 1}
    return sorted(
        lines, key=lambda x: (key[x.component.kind], x.component.sort_order, x.component.code)
    )


def totals(lines: list[Line]) -> dict[str, Decimal]:
    """Fixed monthly totals (before overtime, variable amounts, EPF and APIT, which the payroll
    adds in P2B-06)."""
    zero = Decimal("0.00")
    earnings = sum((x.amount for x in lines if x.component.kind == "earning"), zero)
    deductions = sum((x.amount for x in lines if x.component.kind == "deduction"), zero)
    epf = sum((x.amount for x in lines if x.epf_liable), zero)
    taxable = sum((x.amount for x in lines if x.apit_taxable), zero)
    return {
        "earnings": earnings,
        "deductions": deductions,
        "net": earnings - deductions,
        "epf_earnings": epf,
        "apit_earnings": taxable,
    }
