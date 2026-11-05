"""The monthly payroll run (backlog P2B-06; owner's answers of 5 Nov 2026).

HR prepares a division's payroll for a **pay month** (P2B-15) once HR has confirmed the
attendance and the supervisor or the Director has checked every employee's overtime. Each
employee's line is worked out from the approved pay settings (P2B-17) and every figure says
where it came from:

- **Earnings**: the approved monthly amounts in force for the pay month. A joiner or leaver
  in the middle of the period gets calendar days employed x monthly amount / 30, never more
  than the monthly amount (follow-up 8). Amounts HR types in for the month (components
  "entered each month", e.g. an incentive) are added.
- **Attendance bonus** (ATTEND): lost for the pay month when the employee is away four half
  days or more: days absent and days of approved leave count, maternity leave does not,
  holidays and Sundays are not working days (follow-up 2). All or nothing.
- **Day rate** = monthly pay / 30, monthly pay being the components marked "in the day rate"
  (basic + fixed allowance by default; follow-up 1). **Hourly rate** = monthly pay / the work
  rule's hourly divisor (240).
- **Overtime** from the checked figures: hours x hourly rate x the employee's own rate or the
  work rule's (1.5 working day, 2.0 Sunday, 2.0 holiday).
- **No-pay**: no-pay days x day rate; short time not covered by short leave x hourly rate;
  each unpaid Wages Board short leave = a quarter of the day rate (P2B-16). No-pay reduces the
  earnings that count for EPF and APIT.
- **EPF** employee 8% and employer 12%, **ETF** 3% (dated rates) on the EPF-liable earnings.
- **APIT** from the dated IRD table of the employee's setting (Table 01 primary employment by
  default; Table 07 secondary), on the APIT-taxable earnings including overtime.
- **Deductions**: the approved monthly deductions (welfare, union, ...) and amounts typed in
  (e.g. an advance recovery); advances and loans themselves come with P2B-10.
- **Net** = earnings - no-pay - EPF 8% - APIT - deductions. Owner, follow-up 4: the employee
  always receives more than 40% of the basic salary; a payroll where someone would not is
  refused when it is sent.

Draft (worked out again whenever HR asks, e.g. after typing in amounts) -> sent to the
Director (approval engine, "payroll") -> approved (locked, database) or returned (draft) or
rejected (HR may prepare it again). Nobody approves a payroll they prepared (rule 5).
Once a payroll is sent or approved its attendance cannot be reopened, and a pay change cannot
start in a pay month already in an approved payroll.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, Division, User

from . import attendance, leave, pay, periods
from .models import (
    AttendanceMonth,
    Employee,
    EmployeeSetting,
    Leave,
    OvertimeCheck,
    PayComponent,
    PayrollEntry,
    PayrollItem,
    PayrollLine,
    PayrollRun,
    StatutoryRate,
    TaxTable,
    setting_on,
)

DOC = "payroll"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
THIRTY = Decimal(30)
BONUS = "ATTEND"
MATERNITY = "MATERNITY"
BONUS_HALF_DAYS = 4
NET_SHARE_OF_BASIC = Decimal("0.40")
St = PayrollRun.Status


class PayrollError(Exception):
    pass


def q(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def money(value) -> str:
    return f"{q(value):,.2f}"


# --- Dated rates --------------------------------------------------------------------------------


def statutory_on(day: date) -> StatutoryRate | None:
    return StatutoryRate.objects.filter(effective_from__lte=day).order_by("-effective_from").first()


def tax_table(kind: str, day: date) -> TaxTable | None:
    return (
        TaxTable.objects.filter(kind=kind, effective_from__lte=day)
        .order_by("-effective_from")
        .prefetch_related("bands")
        .first()
    )


def apit_for(earnings: Decimal, table: TaxTable) -> tuple[Decimal, str]:
    """The month's tax by the table: earnings x rate - constant in the first band whose upper
    limit the earnings do not pass; never below 0."""
    if earnings <= 0:
        return ZERO, "No taxable earnings"
    bands = sorted(table.bands.all(), key=lambda b: (b.up_to is None, b.up_to or 0))
    for band in bands:
        if band.up_to is None or earnings <= band.up_to:
            tax = max(ZERO, q(earnings * band.rate / 100 - band.constant))
            how = f"{money(earnings)} x {band.rate}%"
            if band.constant:
                how += f" - {money(band.constant)}"
            return tax, f"{how} ({table.get_kind_display()} from {table.effective_from:%d %b %Y})"
    raise PayrollError(f"The APIT table {table} has no top band.")


# --- Working out one employee ------------------------------------------------------------------


@dataclass
class Figures:
    employee: Employee
    days_employed: int
    days_in_period: int
    day_rate: Decimal = ZERO
    hourly_rate: Decimal = ZERO
    items: list[dict] = field(default_factory=list)
    epf_earnings: Decimal = ZERO
    apit_earnings: Decimal = ZERO
    gross: Decimal = ZERO
    deductions: Decimal = ZERO
    epf_employee: Decimal = ZERO
    epf_employer: Decimal = ZERO
    etf: Decimal = ZERO
    apit: Decimal = ZERO
    net: Decimal = ZERO
    basic: Decimal = ZERO

    def add(self, code, name, kind, amount, basis="", epf=False, apit=False):
        amount = q(amount)
        self.items.append(
            {"code": code, "name": name, "kind": kind, "amount": amount, "basis": basis[:300]}
        )
        if kind == PayrollItem.Kind.EARNING:
            self.gross += amount
            if epf:
                self.epf_earnings += amount
            if apit:
                self.apit_earnings += amount
        elif kind == PayrollItem.Kind.DEDUCTION:
            self.deductions += amount


def _away_half_days(employee, first, last, absent_days) -> Decimal:
    """Half days away for the attendance bonus: absent days and approved leave, maternity
    leave excepted."""
    days = Decimal(absent_days)
    for x in Leave.objects.filter(
        employee=employee,
        status=Leave.Status.APPROVED,
        start__lte=last,
        end__gte=first,
    ).select_related("leave_type"):
        if x.leave_type.code == MATERNITY:
            continue
        if x.half_day:
            days += x.days
        else:
            days += leave.working_days(max(x.start, first), min(x.end, last))
    return days * 2


def work_out_one(run, employee, check, summary, entries, statutory) -> Figures:
    E, D, R = PayrollItem.Kind.EARNING, PayrollItem.Kind.DEDUCTION, PayrollItem.Kind.EMPLOYER
    start, end = run.period_start, run.period_end
    first = max(start, employee.join_date)
    last = min(end, employee.leaving_date or end)
    out = Figures(employee, (last - first).days + 1, (end - start).days + 1)
    part = out.days_employed < out.days_in_period
    lines = pay.amounts_on(employee, run.month)
    if not lines and not entries:
        raise PayrollError(f"{employee.number} {employee.full_name} has no approved pay.")
    own = setting_on(employee, run.month)
    monthly = sum((x.amount for x in lines if x.component.in_day_rate), ZERO)
    out.day_rate = q(monthly / THIRTY)
    divisor = check.rule.hourly_divisor
    out.hourly_rate = q(monthly / divisor) if divisor else ZERO

    away = _away_half_days(employee, first, last, summary.absent_days if summary else 0)
    for x in lines:
        c = x.component
        if c.kind != PayComponent.Kind.EARNING:
            continue
        amount, basis = x.amount, f"Monthly amount since {x.rate.effective_from:%B %Y}"
        if part:
            amount = min(x.amount, q(x.amount * out.days_employed / THIRTY))
            basis = f"{money(x.amount)} x {out.days_employed} days employed / 30"
        if c.code == BONUS and away >= BONUS_HALF_DAYS:
            amount = ZERO
            basis = f"Lost: away {away} half days (4 or more) in the pay month"
        if c.code == "BASIC":
            out.basic = q(amount)
        out.add(c.code, c.name, E, amount, basis, x.epf_liable, x.apit_taxable)
    for x in entries:
        if x.component.kind == PayComponent.Kind.EARNING:
            note = f": {x.note}" if x.note else ""
            out.add(
                x.component.code,
                x.component.name,
                E,
                x.amount,
                f"Entered for the month{note}",
                x.component.epf_liable,
                x.component.apit_taxable,
            )

    # Overtime: the checked figures x the hourly rate x the rate.
    for minutes, rate_field, code, name in (
        (check.ot_working_minutes, "rate_working_day", "OT_WORKING", "Overtime, working days"),
        (check.ot_sunday_minutes, "rate_sunday", "OT_SUNDAY", "Overtime, Sundays"),
        (check.ot_holiday_minutes, "rate_holiday", "OT_HOLIDAY", "Overtime, holidays"),
    ):
        if not minutes:
            continue
        own_rate = getattr(own, rate_field, None) if own else None
        rate = getattr(check.rule, rate_field) if own_rate is None else own_rate
        hours = Decimal(minutes) / 60
        out.add(
            code,
            name,
            E,
            out.hourly_rate * hours * rate,
            f"{minutes // 60}:{minutes % 60:02d} h x {money(out.hourly_rate)} x {rate}",
            epf=False,
            apit=True,
        )

    # No-pay: reduces the earnings, including those for EPF and APIT.
    nopay = []
    if check.nopay_days:
        nopay.append(
            (
                "NOPAY_DAYS",
                "No-pay days",
                out.day_rate * check.nopay_days,
                f"{check.nopay_days} days x day rate {money(out.day_rate)} (monthly pay / 30)",
            )
        )
    if check.nopay_minutes:
        m = check.nopay_minutes
        nopay.append(
            (
                "NOPAY_TIME",
                "No-pay time",
                out.hourly_rate * Decimal(m) / 60,
                f"{m // 60}:{m % 60:02d} h short time x {money(out.hourly_rate)}",
            )
        )
    if check.unpaid_short_leaves:
        n = check.unpaid_short_leaves
        nopay.append(
            (
                "NOPAY_SHORT",
                "Short leave (Wages Board)",
                out.day_rate / 4 * n,
                f"{n} x a quarter of the day rate {money(out.day_rate)}",
            )
        )
    for code, name, amount, basis in nopay:
        amount = q(amount)
        out.items.append({"code": code, "name": name, "kind": D, "amount": amount, "basis": basis})
        out.gross -= amount
        out.epf_earnings -= amount
        out.apit_earnings -= amount
    out.epf_earnings = max(ZERO, out.epf_earnings)
    out.apit_earnings = max(ZERO, out.apit_earnings)

    # EPF and ETF.
    s = statutory
    out.epf_employee = q(out.epf_earnings * s.epf_employee / 100)
    out.epf_employer = q(out.epf_earnings * s.epf_employer / 100)
    out.etf = q(out.epf_earnings * s.etf / 100)
    base = f"{s.epf_employee}% of {money(out.epf_earnings)}"
    out.items.append(
        {
            "code": "EPF_EE",
            "name": "EPF (employee)",
            "kind": D,
            "amount": out.epf_employee,
            "basis": base,
        }
    )

    # APIT.
    kind = own.apit if own else EmployeeSetting.Apit.PRIMARY
    table = tax_table(kind, run.period_end)
    if table is None:
        raise PayrollError(
            f"There is no APIT table for {EmployeeSetting.Apit(kind).label.lower()} on "
            f"{run.period_end:%d %B %Y} ({employee.number}); the Accountant enters it first."
        )
    out.apit, how = apit_for(out.apit_earnings, table)
    out.items.append({"code": "APIT", "name": "APIT", "kind": D, "amount": out.apit, "basis": how})

    # Other deductions.
    for x in lines:
        if x.component.kind == PayComponent.Kind.DEDUCTION and x.amount > 0:
            out.add(
                x.component.code,
                x.component.name,
                D,
                x.amount,
                f"Monthly deduction since {x.rate.effective_from:%B %Y}",
            )
    for x in entries:
        if x.component.kind == PayComponent.Kind.DEDUCTION:
            note = f": {x.note}" if x.note else ""
            out.add(x.component.code, x.component.name, D, x.amount, f"Entered for the month{note}")

    out.items.append(
        {
            "code": "EPF_ER",
            "name": "EPF (employer)",
            "kind": R,
            "amount": out.epf_employer,
            "basis": f"{s.epf_employer}% of {money(out.epf_earnings)}",
        }
    )
    out.items.append(
        {
            "code": "ETF",
            "name": "ETF (employer)",
            "kind": R,
            "amount": out.etf,
            "basis": f"{s.etf}% of {money(out.epf_earnings)}",
        }
    )
    out.net = out.gross - out.epf_employee - out.apit - out.deductions
    return out


# --- The run ------------------------------------------------------------------------------------


def can_prepare(user: User) -> bool:
    return effective_access(user).has("hr_payroll", "manage")


def _division(user: User, code) -> Division:
    found = division_scope(user).filter(code=str(code or "").upper()).first()
    if found is None:
        raise PayrollError("Choose one of your divisions.")
    return found


def people(run: PayrollRun):
    return (
        Employee.objects.filter(division=run.division, join_date__lte=run.period_end)
        .exclude(leaving_date__lt=run.period_start)
        .order_by("number")
    )


def _work_out(run: PayrollRun) -> None:
    if not AttendanceMonth.objects.filter(
        division=run.division, month=run.month, confirmed=True
    ).exists():
        raise PayrollError(
            f"HR has not confirmed attendance for pay month {run.month:%B %Y} in "
            f"{run.division.code}."
        )
    statutory = statutory_on(run.period_end)
    if statutory is None:
        raise PayrollError("There are no EPF and ETF rates for this pay month.")
    staff = list(people(run))
    if not staff:
        raise PayrollError(f"{run.division.code} has nobody employed in this pay month.")
    checks = {
        c.employee_id: c
        for c in OvertimeCheck.objects.filter(
            employee__in=staff, month=run.month, voided=False
        ).select_related("rule")
    }
    missing = [e.number for e in staff if e.pk not in checks]
    if missing:
        raise PayrollError(
            "The overtime of these employees is not checked yet: " + ", ".join(missing) + "."
        )
    summaries = {
        s.employee.pk: s
        for s in attendance.month_summary_for(Employee.objects.all(), run.division, run.month)
    }
    entries = {}
    for x in run.entries.select_related("component"):
        entries.setdefault(x.employee_id, []).append(x)
    run.lines.all().delete()
    for e in staff:
        f = work_out_one(
            run, e, checks[e.pk], summaries.get(e.pk), entries.get(e.pk, []), statutory
        )
        line = PayrollLine.objects.create(
            run=run,
            employee=e,
            days_employed=f.days_employed,
            days_in_period=f.days_in_period,
            day_rate=f.day_rate,
            hourly_rate=f.hourly_rate,
            gross=f.gross,
            epf_earnings=f.epf_earnings,
            apit_earnings=f.apit_earnings,
            epf_employee=f.epf_employee,
            epf_employer=f.epf_employer,
            etf=f.etf,
            apit=f.apit,
            deductions=f.deductions,
            net=f.net,
            basic=f.basic,
        )
        PayrollItem.objects.bulk_create(
            PayrollItem(line=line, sort_order=i, **item) for i, item in enumerate(f.items)
        )
    run.statutory = statutory
    run.worked_out_at = timezone.now()


def prepare(user: User, division_code, month) -> PayrollRun:
    if not can_prepare(user):
        raise PayrollError("Only HR prepares the payroll.")
    division = _division(user, division_code)
    month = attendance.first_of(month)
    start, end = periods.pay_period(month)
    with audit_context("payroll_prepared", f"{division.code} {month:%Y-%m}"), transaction.atomic():
        if (
            PayrollRun.objects.filter(division=division, month=month)
            .exclude(status=St.REJECTED)
            .exists()
        ):
            raise PayrollError(f"{division.code} already has a payroll for {month:%B %Y}.")
        statutory = statutory_on(end)
        if statutory is None:
            raise PayrollError("There are no EPF and ETF rates for this pay month.")
        run = PayrollRun.objects.create(
            division=division,
            month=month,
            period_start=start,
            period_end=end,
            statutory=statutory,
            created_by=user,
        )
        _work_out(run)
        run.save()
        return run


def _locked(run: PayrollRun, *statuses) -> PayrollRun:
    run = PayrollRun.objects.select_for_update().get(pk=run.pk)
    if run.status not in statuses:
        raise PayrollError(f"The payroll is {run.get_status_display().lower()}.")
    return run


def recompute(user: User, run: PayrollRun) -> PayrollRun:
    if not can_prepare(user):
        raise PayrollError("Only HR prepares the payroll.")
    with audit_context("payroll_worked_out", ""), transaction.atomic():
        run = _locked(run, St.DRAFT)
        _work_out(run)
        run.save()
        return run


def set_entry(user: User, run: PayrollRun, employee_id, code, amount, note="") -> PayrollRun:
    """HR types in an amount for the month (0 or blank removes it); the payroll is worked out
    again."""
    if not can_prepare(user):
        raise PayrollError("Only HR prepares the payroll.")
    with audit_context("payroll_entry", note or ""), transaction.atomic():
        run = _locked(run, St.DRAFT)
        employee = people(run).filter(pk=employee_id).first()
        if employee is None:
            raise PayrollError("The employee is not in this payroll.")
        component = PayComponent.objects.filter(code=str(code or "").upper()).first()
        if component is None or not component.is_active:
            raise PayrollError("Choose a pay component in use.")
        try:
            value = pay._amount(amount if amount not in (None, "") else "0")
        except pay.PayError as error:
            raise PayrollError(str(error)) from None
        PayrollEntry.objects.filter(run=run, employee=employee, component=component).delete()
        if value > 0:
            PayrollEntry.objects.create(
                run=run,
                employee=employee,
                component=component,
                amount=value,
                note=" ".join(str(note or "").split())[:200],
            )
        _work_out(run)
        run.save()
        return run


def totals(run: PayrollRun) -> dict:
    sums = run.lines.aggregate(
        gross=Sum("gross"),
        epf_employee=Sum("epf_employee"),
        epf_employer=Sum("epf_employer"),
        etf=Sum("etf"),
        apit=Sum("apit"),
        deductions=Sum("deductions"),
        net=Sum("net"),
    )
    out = {k: q(v or 0) for k, v in sums.items()}
    out["employees"] = run.lines.count()
    return out


def _below_share(run: PayrollRun) -> list[str]:
    return [
        f"{x.employee.number} (net {money(x.net)}, basic {money(x.basic)})"
        for x in run.lines.select_related("employee")
        if x.basic > 0 and x.net <= q(x.basic * NET_SHARE_OF_BASIC)
    ]


def submit(user: User, run: PayrollRun, comment: str = "") -> PayrollRun:
    if not can_prepare(user):
        raise PayrollError("Only HR prepares the payroll.")
    with audit_context("payroll_submitted", comment), transaction.atomic():
        run = _locked(run, St.DRAFT)
        _work_out(run)  # always sent as worked out from the latest figures
        run.save()
        low = _below_share(run)
        if low:
            raise PayrollError(
                "These employees would receive 40% of the basic salary or less: "
                + "; ".join(low)
                + ". Reduce the amounts typed in for the month."
            )
        t = totals(run)
        try:
            approvals.submit(
                user,
                DOC,
                run.pk,
                created_by=run.created_by,
                division=run.division,
                comment=comment,
                title=f"Payroll {run.division.code} {run.month:%B %Y}: {t['employees']} "
                f"employees, net LKR {money(t['net'])}",
                link=f"/payroll/{run.pk}",
            )
        except ApprovalError as error:
            raise PayrollError(str(error)) from None
        run.status = St.AWAITING
        run.save(update_fields=["status", "statutory", "worked_out_at"])
        return run


def approve(user: User, run: PayrollRun, comment: str = "") -> PayrollRun:
    with transaction.atomic():
        run = _locked(run, St.AWAITING)
        try:
            state = approvals.approve(user, DOC, run.pk, comment)
        except ApprovalError as error:
            raise PayrollError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("payroll_approved", comment):
                run.status = St.APPROVED
                run.approved_at = timezone.now()
                run.save(update_fields=["status", "approved_at"])
        return run


def send_back(user: User, run: PayrollRun, reason: str) -> PayrollRun:
    with transaction.atomic():
        run = _locked(run, St.AWAITING)
        try:
            approvals.send_back(user, DOC, run.pk, reason)
        except ApprovalError as error:
            raise PayrollError(str(error)) from None
        with audit_context("payroll_returned", reason):
            run.status = St.DRAFT
            run.save(update_fields=["status"])
        return run


def reject(user: User, run: PayrollRun, reason: str) -> PayrollRun:
    with transaction.atomic():
        run = _locked(run, St.AWAITING)
        try:
            approvals.reject(user, DOC, run.pk, reason)
        except ApprovalError as error:
            raise PayrollError(str(error)) from None
        with audit_context("payroll_rejected", reason):
            run.status = St.REJECTED
            run.save(update_fields=["status"])
        return run


def can_approve(user: User, run: PayrollRun) -> bool:
    if run.status != St.AWAITING:
        return False
    state = approvals.state_of(DOC, run.pk)
    return state is not None and approvals.why_not(user, state) is None


def in_payroll(division_id: int, month: date) -> bool:
    """A pay month in a payroll that is sent or approved: its attendance stays as it is."""
    return PayrollRun.objects.filter(
        division_id=division_id, month=month, status__in=[St.AWAITING, St.APPROVED]
    ).exists()


def paid_through(employee: Employee) -> date | None:
    """The last pay month of the employee's division with an approved payroll."""
    run = (
        PayrollRun.objects.filter(division_id=employee.division_id, status=St.APPROVED)
        .order_by("-month")
        .first()
    )
    return run.month if run else None
