"""Gratuity (backlog P2B-19; owner, follow-up 9).

- **The law**: the Payment of Gratuity Act No. 12 of 1983 gives an employee who leaves after
  **5 completed years** half a month's wage or salary for each completed year of service.
  The wage here is the monthly pay of the components "in the day rate" (basic and fixed
  allowance by default, as the day rate; the Accountant confirms).
- **Settings** per employee (service counted from, months' pay per completed year, years
  before it is earned) are entered by the **Accountant** and approved by the **Director**,
  from a pay month on (rule 11). They are never less than the Act: at least half a month a
  year, earned after at most 5 years, service counted from joining or earlier. Without a
  setting, the Act applies.
- **Monthly provision** (the method to confirm with the auditors, LKAS 19): each payroll
  works out every employee's liability at the end of the pay period as if they left then
  (completed years x months per year x wage, once the years are earned) and provides the
  change since their previous approved payroll: Dr Gratuity (division) Cr Provision for
  gratuity. A fall (a lower wage) releases the difference. Before the first payroll the
  provision is nil, so the first payroll provides the whole liability (P2B-14 can bring an
  opening provision instead).
- **Paid on leaving** by a payment voucher coded to Provision for gratuity (rule 4: the
  Director approves it); the page shows each employee's liability.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User

from . import pay, periods
from .models import Employee, GratuitySetting, PayrollLine, PayrollRun

DOC = "gratuity_setting"
ACT_MONTHS = Decimal("0.5")
ACT_YEARS = 5
ZERO = Decimal("0.00")
CENT = Decimal("0.01")
St = GratuitySetting.Status


class GratuityError(Exception):
    pass


def q(value) -> Decimal:
    return Decimal(value).quantize(CENT, ROUND_HALF_UP)


@dataclass
class Terms:
    service_from: date
    months_per_year: Decimal
    after_years: int
    setting: GratuitySetting | None  # None: the Act


def terms(employee: Employee, month: date) -> Terms:
    """The approved setting in force for a pay month, or the Act."""
    s = (
        employee.gratuity_settings.filter(status=St.APPROVED, effective_from__lte=month)
        .order_by("-effective_from", "-approved_at", "-id")
        .first()
    )
    if s is None:
        return Terms(employee.join_date, ACT_MONTHS, ACT_YEARS, None)
    return Terms(s.service_from, s.months_per_year, s.after_years, s)


def completed_years(start: date, on: date) -> int:
    years = on.year - start.year - ((on.month, on.day) < (start.month, start.day))
    return max(years, 0)


def liability(employee: Employee, month: date, on: date, wage: Decimal) -> tuple[int, Decimal]:
    """Completed years and the gratuity if the employee left on `on`."""
    t = terms(employee, month)
    years = completed_years(t.service_from, on)
    if years < t.after_years or wage <= 0:
        return years, ZERO
    return years, q(wage * t.months_per_year * years)


def provided(employee: Employee, before: date) -> Decimal:
    """The provision so far: the liability at the employee's latest approved payroll."""
    line = (
        PayrollLine.objects.filter(
            employee=employee, run__status=PayrollRun.Status.APPROVED, run__month__lt=before
        )
        .order_by("-run__month")
        .first()
    )
    if line is not None:
        return line.gratuity_liability
    # Before the first payroll here: what the old payroll provided (P2B-14), if brought over.
    from .takeover import opening_gratuity

    return opening_gratuity(employee, before) or ZERO


def wage(employee: Employee, month: date) -> Decimal:
    return sum((x.amount for x in pay.amounts_on(employee, month) if x.component.in_day_rate), ZERO)


# --- Settings ------------------------------------------------------------------------------------


def can_enter(user: User) -> bool:
    return effective_access(user).has("accounting", "enter")


def can_see(user: User) -> bool:
    return effective_access(user).has("accounting", "view")


def visible(user: User):
    return Employee.objects.filter(division__in=division_scope(user))


def _amount(value) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise GratuityError("The months' pay per year is a number, e.g. 0.5.") from None
    if not number.is_finite() or number != number.quantize(CENT):
        raise GratuityError("The months' pay per year has at most two decimal places.")
    return number


def propose(user: User, employee: Employee, values: dict) -> GratuitySetting:
    if not can_enter(user):
        raise GratuityError("Only the Accountant enters gratuity settings.")
    employee = visible(user).filter(pk=employee.pk).first()
    if employee is None:
        raise GratuityError("This employee is not in one of your divisions.")
    try:
        month = date.fromisoformat(f"{str(values.get('effective_from') or '')[:7]}-01")
        service_from = date.fromisoformat(str(values.get("service_from") or employee.join_date))
    except ValueError:
        raise GratuityError("Give the dates as on the form, e.g. 2026-11 and 2020-01-15.") from None
    current = periods.pay_month_of(timezone.localdate())
    if month < current:
        raise GratuityError(f"Settings start in pay month {current:%B %Y} or later.")
    if service_from > employee.join_date:
        raise GratuityError(
            "Service is counted from joining or earlier, never later (the Act counts it from "
            f"joining, {employee.join_date:%d %b %Y})."
        )
    months = _amount(values.get("months_per_year") or ACT_MONTHS)
    if not ACT_MONTHS <= months <= 3:
        raise GratuityError("Months' pay per completed year is 0.5 (the Act) to 3.")
    try:
        after = int(values.get("after_years") if values.get("after_years") not in (None, "") else 5)
    except (TypeError, ValueError):
        raise GratuityError("The years before gratuity is earned is a whole number.") from None
    if not 0 <= after <= ACT_YEARS:
        raise GratuityError("Gratuity is earned after 0 to 5 completed years (5 in the Act).")
    reason = " ".join(str(values.get("reason") or "").split())
    if not reason:
        raise GratuityError("Give the reason.")
    with audit_context("gratuity_setting_entered", reason), transaction.atomic():
        if employee.gratuity_settings.filter(status=St.AWAITING).exists():
            raise GratuityError("This employee already has settings waiting for the Director.")
        setting = GratuitySetting.objects.create(
            employee=employee,
            effective_from=month,
            service_from=service_from,
            months_per_year=months,
            after_years=after,
            reason=reason[:200],
            created_by=user,
        )
        try:
            approvals.submit(
                user,
                DOC,
                setting.pk,
                created_by=user,
                division=employee.division,
                title=f"Gratuity settings: {employee.number} {employee.full_name}, "
                f"{months} month(s) a year after {after} years, from {month:%B %Y}",
                link="/gratuity",
            )
        except ApprovalError as error:
            raise GratuityError(str(error)) from None
        return setting


def _locked(setting_id) -> GratuitySetting:
    setting = (
        GratuitySetting.objects.select_for_update()
        .select_related("employee")
        .filter(pk=setting_id)
        .first()
    )
    if setting is None:
        raise GratuityError("There are no such settings.")
    if setting.status != St.AWAITING:
        raise GratuityError(f"These settings are {setting.get_status_display().lower()}.")
    return setting


def decide(user: User, setting_id, action: str, reason: str = "") -> GratuitySetting:
    reason = " ".join((reason or "").split())
    with transaction.atomic():
        setting = _locked(setting_id)
        try:
            if action == "approve":
                state = approvals.approve(user, DOC, setting.pk, reason)
                status = St.APPROVED if state.status == ApprovalState.Status.APPROVED else None
            elif action == "reject":
                approvals.reject(user, DOC, setting.pk, reason)
                status = St.REJECTED
            elif action == "withdraw":
                if setting.created_by_id != user.pk:
                    raise GratuityError("Only the person who entered them withdraws them.")
                if not reason:
                    raise GratuityError("Give the reason for withdrawing them.")
                approvals.withdraw(user, DOC, setting.pk, reason)
                status = St.WITHDRAWN
            else:
                raise GratuityError("Unknown action.")
        except ApprovalError as error:
            raise GratuityError(str(error)) from None
        if status:
            with audit_context(f"gratuity_setting_{status}", reason):
                setting.status = status
                if status == St.APPROVED:
                    setting.approved_at = timezone.now()
                setting.save(update_fields=["status", "approved_at"])
        return setting


def can_approve(user: User, setting: GratuitySetting) -> bool:
    if setting.status != St.AWAITING:
        return False
    state = approvals.state_of(DOC, setting.pk)
    return state is not None and approvals.why_not(user, state) is None


# --- The page ------------------------------------------------------------------------------------


def overview(user: User) -> list[dict]:
    """Each employee's terms, completed years, wage and liability today, and the provision
    made so far by the payrolls."""
    today = timezone.localdate()
    month = periods.pay_month_of(today)
    out = []
    for e in visible(user).filter(is_active=True).select_related("division").order_by("number"):
        t = terms(e, month)
        w = wage(e, month)
        years, owed = liability(e, month, today, w)
        waiting = e.gratuity_settings.filter(status=St.AWAITING).first()
        out.append(
            {
                "id": e.pk,
                "number": e.number,
                "name": e.full_name,
                "division": e.division.code,
                "join_date": e.join_date,
                "service_from": t.service_from,
                "months_per_year": f"{t.months_per_year}",
                "after_years": t.after_years,
                "by_act": t.setting is None,
                "years": years,
                "wage": f"{w:.2f}",
                "liability": f"{owed:.2f}",
                # Up to and including the payroll of the current pay month.
                "provided": f"{provided(e, month + timedelta(days=1)):.2f}",
                "waiting": _setting(waiting, user) if waiting else None,
            }
        )
    return out


def _setting(s: GratuitySetting, user: User) -> dict:
    return {
        "id": s.pk,
        "effective_from": s.effective_from.isoformat()[:7],
        "service_from": s.service_from,
        "months_per_year": f"{s.months_per_year}",
        "after_years": s.after_years,
        "reason": s.reason,
        "status": s.status,
        "status_label": s.get_status_display(),
        "created_by": s.created_by.full_name,
        "can_approve": can_approve(user, s),
        "can_withdraw": s.created_by_id == user.pk and s.status == St.AWAITING,
    }
