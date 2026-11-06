"""Salary advances and staff loans (backlog P2B-10; owner's answers of 5 Nov 2026).

- HR records an advance or a loan for an employee: the amount, for a loan the interest
  agreed when it is given (0 for none) and the number of months, the pay month recovery
  starts, and the reason. An advance is recovered in full in its pay month (owner, question 3
  and follow-up 4); a loan in equal monthly instalments of (amount + interest) / months
  (question 12: LKR 240,000 over 24 months = 10,000 a month), the last one taking any cent
  left over.
- The Director approves every advance and loan (follow-ups 4 and 5; approval type
  "staff_credit"); nobody approves one they recorded (rule 5). It is numbered on approval.
- **More than 40% of the basic salary stays with the employee** (follow-up 4): an advance or
  loan whose first recovery would leave the month's net pay at 40% of the basic or less is
  refused when sent and when approved (worked out from the pay in force, before overtime and
  APIT). The payroll checks again: a recovery that would take more waits for the next month.
- Paying it out: the Clerk enters a voucher for the amount coded to Staff loans and
  advances; it goes through the three approvals like any voucher (rule 4).
- A leaver's balance is deducted from the final salary as far as it goes (the 40% rule
  still holds); anything left stays on the balance for the Accountant.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core import approvals
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User
from apps.core.numbering import NumberSeriesError, allocate

from . import employees, pay, periods
from .models import Employee, PayComponent, PayrollRun, StaffCredit, StatutoryRate

DOC = "staff_credit"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
SHARE = Decimal("0.40")
MAX_MONTHS = 120
St = StaffCredit.Status


class CreditError(Exception):
    pass


def q(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


# --- Balances -----------------------------------------------------------------------------------


def recovered(credit: StaffCredit, *, statuses=(PayrollRun.Status.APPROVED,)) -> Decimal:
    total = credit.recoveries.filter(line__run__status__in=statuses).aggregate(s=Sum("amount"))
    return total["s"] or ZERO


def balance(credit: StaffCredit) -> Decimal:
    return credit.total - recovered(credit)


def due(employee: Employee, run: PayrollRun) -> list[tuple[StaffCredit, Decimal, str]]:
    """What the payroll `run` should recover from the employee, before the 40% rule:
    (credit, amount, basis) for each approved advance or loan with a balance."""
    leaving = employee.leaving_date and employee.leaving_date <= run.period_end
    out = []
    for c in StaffCredit.objects.filter(
        employee=employee, status=St.APPROVED, first_month__lte=run.month
    ).order_by("first_month", "id"):
        # Recovered in other payrolls that are sent or approved (not this one).
        taken = (
            c.recoveries.filter(
                line__run__status__in=[PayrollRun.Status.AWAITING, PayrollRun.Status.APPROVED]
            )
            .exclude(line__run=run)
            .aggregate(s=Sum("amount"))["s"]
            or ZERO
        )
        left = c.total - taken
        if left <= 0:
            continue
        if leaving:
            amount, basis = left, f"{c.number}: the whole balance (leaving)"
        elif c.kind == StaffCredit.Kind.ADVANCE:
            amount, basis = left, f"{c.number}: advance recovered in full"
        else:
            amount = min(c.instalment, left)
            basis = (
                f"{c.number}: instalment {money(c.instalment)} "
                f"({money(c.total)} over {c.months} months); balance after "
                f"{money(left - amount)}"
            )
        out.append((c, amount, basis))
    return out


def money(value) -> str:
    return f"{q(value):,.2f}"


# --- The 40% check (before overtime and APIT) ----------------------------------------------------


def estimated_net(employee: Employee, month: date, extra: Decimal) -> tuple[Decimal, Decimal]:
    """(net pay, basic) for the pay month from the pay in force, less EPF 8%, the monthly
    deductions, the recoveries already due and `extra`."""
    lines = pay.amounts_on(employee, month)
    earnings = sum((x.amount for x in lines if x.component.kind == PayComponent.Kind.EARNING), ZERO)
    epf_base = sum(
        (x.amount for x in lines if x.component.kind == PayComponent.Kind.EARNING and x.epf_liable),
        ZERO,
    )
    deductions = sum(
        (x.amount for x in lines if x.component.kind == PayComponent.Kind.DEDUCTION), ZERO
    )
    basic = sum((x.amount for x in lines if x.component.code == "BASIC"), ZERO)
    rate = StatutoryRate.objects.filter(effective_from__lte=month).order_by("-effective_from")
    epf = q(epf_base * (rate.first().epf_employee if rate.exists() else 8) / 100)
    already = ZERO
    for c in StaffCredit.objects.filter(
        employee=employee, status=St.APPROVED, first_month__lte=month
    ):
        left = balance(c)
        if left > 0:
            already += left if c.kind == StaffCredit.Kind.ADVANCE else min(c.instalment, left)
    return earnings - epf - deductions - already - extra, basic


def _check_share(credit: StaffCredit) -> None:
    first = credit.amount if credit.kind == StaffCredit.Kind.ADVANCE else credit.instalment
    net, basic = estimated_net(credit.employee, credit.first_month, first)
    if basic <= 0:
        raise CreditError(f"{credit.employee.full_name} has no approved basic salary.")
    if net <= q(basic * SHARE):
        raise CreditError(
            f"After this the employee would receive LKR {money(net)} in "
            f"{credit.first_month:%B %Y}, not more than 40% of the basic salary "
            f"(LKR {money(basic * SHARE)}). Lower the amount or spread the loan over more months."
        )


# --- Recording ----------------------------------------------------------------------------------


def _amount(value, label: str, *, zero_ok=False) -> Decimal:
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise CreditError(f"The {label} is an amount in rupees and cents.") from None
    if not number.is_finite() or number < 0 or (number == 0 and not zero_ok):
        raise CreditError(
            f"The {label} is more than 0." if not zero_ok else f"The {label} is 0 or more."
        )
    if number != number.quantize(CENT):
        raise CreditError(f"The {label} has at most two decimal places.")
    return number


def _employee(user: User, employee: Employee) -> Employee:
    if not employees.can_edit(user):
        raise CreditError("Only HR records advances and loans.")
    found = employees.visible(user).filter(pk=employee.pk).first()
    if found is None:
        raise CreditError("This employee is not in one of your divisions.")
    if not found.is_active:
        raise CreditError("This employee has left.")
    return found


def _fill(credit: StaffCredit, values: dict) -> None:
    kind = values.get("kind")
    if kind not in StaffCredit.Kind.values:
        raise CreditError("Choose an advance or a loan.")
    credit.kind = kind
    credit.amount = _amount(values.get("amount"), "amount")
    if kind == StaffCredit.Kind.ADVANCE:
        credit.interest, credit.months = ZERO, 1
    else:
        credit.interest = _amount(values.get("interest") or "0", "interest", zero_ok=True)
        try:
            credit.months = int(values.get("months"))
        except (TypeError, ValueError):
            raise CreditError("Give the number of months to repay the loan.") from None
        if not 1 <= credit.months <= MAX_MONTHS:
            raise CreditError(f"A loan is repaid over 1 to {MAX_MONTHS} months.")
    try:
        credit.first_month = date.fromisoformat(f"{str(values.get('first_month') or '')[:7]}-01")
    except ValueError:
        raise CreditError("Give the pay month recovery starts, for example 2026-11.") from None
    current = periods.pay_month_of(timezone.localdate())
    if credit.first_month < current:
        raise CreditError(f"Recovery starts in pay month {current:%B %Y} or later.")
    reason = " ".join(str(values.get("reason") or "").split())
    if not reason:
        raise CreditError("Give the reason.")
    credit.reason = reason[:200]


def record(user: User, employee: Employee, values: dict) -> StaffCredit:
    employee = _employee(user, employee)
    credit = StaffCredit(employee=employee, created_by=user)
    _fill(credit, values)
    with audit_context("staff_credit_recorded", credit.reason), transaction.atomic():
        credit.save()
    return credit


def _locked(credit: StaffCredit, *statuses) -> StaffCredit:
    credit = StaffCredit.objects.select_for_update().get(pk=credit.pk)
    if credit.status not in statuses:
        raise CreditError(
            f"The {credit.get_kind_display().lower()} is {credit.get_status_display().lower()}."
        )
    return credit


def edit(user: User, credit: StaffCredit, values: dict) -> StaffCredit:
    _employee(user, credit.employee)
    with audit_context("staff_credit_edited", values.get("reason", "")), transaction.atomic():
        credit = _locked(credit, St.DRAFT)
        if credit.created_by_id != user.pk:
            raise CreditError("Only the person who recorded it edits it.")
        _fill(credit, values)
        credit.save()
        return credit


def submit(user: User, credit: StaffCredit, comment: str = "") -> StaffCredit:
    _employee(user, credit.employee)
    with audit_context("staff_credit_submitted", comment), transaction.atomic():
        credit = _locked(credit, St.DRAFT)
        _check_share(credit)
        e = credit.employee
        try:
            approvals.submit(
                user,
                DOC,
                credit.pk,
                created_by=credit.created_by,
                division=e.division,
                comment=comment,
                title=f"{credit.get_kind_display()}: {e.number} {e.full_name}, "
                f"LKR {money(credit.amount)}",
                link="/advances-loans",
            )
        except ApprovalError as error:
            raise CreditError(str(error)) from None
        credit.status = St.AWAITING
        credit.save(update_fields=["status"])
        return credit


def approve(user: User, credit: StaffCredit, comment: str = "") -> StaffCredit:
    with transaction.atomic():
        credit = _locked(credit, St.AWAITING)
        try:
            state = approvals.approve(user, DOC, credit.pk, comment)
        except ApprovalError as error:
            raise CreditError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("staff_credit_approved", comment):
                _check_share(credit)
                try:
                    credit.number = allocate(DOC)
                except NumberSeriesError as error:
                    raise CreditError(str(error)) from None
                credit.status = St.APPROVED
                credit.approved_at = timezone.now()
                credit.save(update_fields=["status", "number", "approved_at"])
        return credit


def send_back(user: User, credit: StaffCredit, reason: str) -> StaffCredit:
    with transaction.atomic():
        credit = _locked(credit, St.AWAITING)
        try:
            approvals.send_back(user, DOC, credit.pk, reason)
        except ApprovalError as error:
            raise CreditError(str(error)) from None
        with audit_context("staff_credit_returned", reason):
            credit.status = St.DRAFT
            credit.save(update_fields=["status"])
        return credit


def reject(user: User, credit: StaffCredit, reason: str) -> StaffCredit:
    with transaction.atomic():
        credit = _locked(credit, St.AWAITING)
        try:
            approvals.reject(user, DOC, credit.pk, reason)
        except ApprovalError as error:
            raise CreditError(str(error)) from None
        with audit_context("staff_credit_rejected", reason):
            credit.status = St.REJECTED
            credit.save(update_fields=["status"])
        return credit


def withdraw(user: User, credit: StaffCredit, reason: str) -> StaffCredit:
    _employee(user, credit.employee)
    reason = " ".join((reason or "").split())
    if not reason:
        raise CreditError("Give the reason for withdrawing it.")
    with audit_context("staff_credit_withdrawn", reason), transaction.atomic():
        credit = _locked(credit, St.DRAFT, St.AWAITING)
        if approvals.state_of(DOC, credit.pk) is not None:
            approvals.withdraw(user, DOC, credit.pk, reason)
        credit.status = St.WITHDRAWN
        credit.save(update_fields=["status"])
        return credit


def can_approve(user: User, credit: StaffCredit) -> bool:
    if credit.status != St.AWAITING:
        return False
    state = approvals.state_of(DOC, credit.pk)
    return state is not None and approvals.why_not(user, state) is None
