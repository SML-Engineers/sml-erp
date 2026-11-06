"""Employee self-service (backlog P2B-11): each employee, signed in on the phone, sees only
their own records.

- **Who**: the employee whose record is linked to the signed-in user (HR links it on the
  employee's page). Nobody else's figures are ever shown here, whatever the user's role.
- **Payslips** of the approved payrolls (PDF; not locked, as the person is signed in), the
  **EPF and ETF** paid for them month by month and the **APIT** for the year of assessment,
  with the year-end certificate.
- **Leave**: the year's balances and their leave; they **apply for leave**, which their
  section's supervisor or HR approves (never themselves, rule 5), and may withdraw an
  application not yet decided.
- **Attendance**: their days in the latest pay months, and the phone clock (P2B-12,
  punches.py) for those HR has switched on.
- **Supervisors** see the leave applications of the sections they supervise, to approve or
  reject.

Asking HR to change personal or bank details comes with P2B-20.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.audit import audit_context
from apps.core.models import User

from . import leave, payslips, periods, punches, returns
from .models import AttendanceDay, Employee, Leave, LeaveType, PayrollLine, PayrollRun

ZERO = Decimal("0.00")


class SelfServiceError(Exception):
    pass


def me(user: User) -> Employee:
    employee = Employee.objects.filter(user=user).select_related("division", "section").first()
    if employee is None:
        raise SelfServiceError(
            "Your sign-in is not linked to an employee record yet. Ask HR to link it."
        )
    return employee


def approved_lines(employee: Employee):
    return (
        PayrollLine.objects.filter(employee=employee, run__status=PayrollRun.Status.APPROVED)
        .select_related("run", "run__division")
        .order_by("-run__month")
    )


def summary(user: User) -> dict:
    e = me(user)
    today = timezone.localdate()
    year = today.year
    lines = list(approved_lines(e)[:24])
    current = periods.pay_month_of(today)
    first, last = periods.pay_period(periods.previous_month(current))
    days = AttendanceDay.objects.filter(employee=e, date__gte=first).order_by("-date")[:62]
    tax_year = payslips.year_start(today)
    return {
        "employee": {
            "number": e.number,
            "name": e.full_name,
            "division": e.division.code,
            "section": e.section.name if e.section_id else "",
            "designation": e.designation,
            "category": e.get_category_display(),
            "epf_no": e.epf_no,
        },
        "payslips": [
            {
                "id": x.pk,
                "month": x.run.month.isoformat()[:7],
                "gross": f"{x.gross:.2f}",
                "net": f"{x.net:.2f}",
                "epf_employee": f"{x.epf_employee:.2f}",
                "epf_employer": f"{x.epf_employer:.2f}",
                "etf": f"{x.etf:.2f}",
                "apit": f"{x.apit:.2f}",
            }
            for x in lines
        ],
        "tax_year": tax_year.year,
        "leave_year": year,
        "balances": [
            {
                "code": b.leave_type.code,
                "name": b.leave_type.name,
                "granted": f"{b.granted}",
                "taken": f"{b.taken}",
                "pending": f"{b.pending}",
                "left": f"{b.available}",
            }
            for b in leave.balances(e, year)
        ],
        "leave": [
            {
                "id": x.pk,
                "type": x.leave_type.name,
                "start": x.start,
                "end": x.end,
                "days": f"{x.days}",
                "status": x.status,
                "status_label": x.get_status_display(),
                "note": x.decision_note,
                "can_withdraw": x.status == Leave.Status.APPLIED,
            }
            for x in Leave.objects.filter(employee=e, start__year__gte=year - 1)
            .select_related("leave_type")
            .order_by("-start")[:30]
        ],
        "leave_types": [
            {"code": k.code, "name": k.name}
            for k in LeaveType.objects.filter(is_active=True).exclude(code="NOPAY")
        ],
        "attendance": {
            "from": first,
            "days": [
                {
                    "date": d.date,
                    "time_in": d.time_in.strftime("%H:%M") if d.time_in else "",
                    "time_out": d.time_out.strftime("%H:%M") if d.time_out else "",
                    "leave": d.leave_type.name if d.leave_type_id else "",
                    "late": d.late_minutes,
                }
                for d in days.select_related("leave_type")
            ],
        },
        "clock": punches.status(e),
        "to_approve": [application(x) for x in to_approve(user)],
    }


def payslip(user: User, line_id) -> tuple[str, bytes]:
    e = me(user)
    line = approved_lines(e).filter(pk=line_id).prefetch_related("items").first()
    if line is None:
        raise SelfServiceError("There is no such payslip of yours.")
    with audit_context("own_payslip_printed", payslips.filename(line)):
        return payslips.filename(line), payslips.render([line])


def certificate(user: User, year) -> bytes:
    e = me(user)
    try:
        year = int(year)
    except (TypeError, ValueError):
        raise SelfServiceError("Choose the year of assessment.") from None
    content = returns.certificate_for(e, year)
    if content is None:
        raise SelfServiceError("You have no approved payroll in that year.")
    return content


def apply(user: User, values: dict) -> Leave:
    e = me(user)
    kind = LeaveType.objects.filter(code=str(values.get("leave_type") or "").upper()).first()
    if kind is None or kind.code == "NOPAY":
        raise SelfServiceError("Choose the kind of leave.")
    try:
        return leave.record(
            user,
            e,
            kind,
            values.get("start"),
            values.get("end"),
            half_day=bool(values.get("half_day")),
            reason=values.get("reason", ""),
            source=Leave.Source.APPLIED,
        )
    except leave.LeaveError as error:
        raise SelfServiceError(str(error)) from None


def withdraw(user: User, leave_id) -> Leave:
    e = me(user)
    with audit_context("leave_application_withdrawn", ""), transaction.atomic():
        x = Leave.objects.select_for_update().filter(employee=e, pk=leave_id).first()
        if x is None:
            raise SelfServiceError("There is no such leave of yours.")
        if x.status != Leave.Status.APPLIED:
            raise SelfServiceError("Only an application not yet decided can be withdrawn.")
        x.status = Leave.Status.CANCELLED
        x.decided_by, x.decided_at = user, timezone.now()
        x.decision_note = "Withdrawn by the employee"
        x.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
        return x


# --- Supervisors ---------------------------------------------------------------------------------


def to_approve(user: User):
    return (
        Leave.objects.filter(status=Leave.Status.APPLIED, employee__section__supervisors=user)
        .exclude(employee__user=user)
        .select_related("employee", "leave_type")
        .order_by("start")
    )


def application(x: Leave) -> dict:
    return {
        "id": x.pk,
        "employee": f"{x.employee.number} {x.employee.full_name}",
        "type": x.leave_type.name,
        "start": x.start,
        "end": x.end,
        "days": f"{x.days}",
        "reason": x.reason,
    }


def decide(user: User, leave_id, approve: bool, note: str = "") -> Leave:
    x = to_approve(user).filter(pk=leave_id).first()
    if x is None:
        raise SelfServiceError("This application is not waiting for you.")
    try:
        return leave.decide(user, x, approve, note)
    except leave.LeaveError as error:
        raise SelfServiceError(str(error)) from None
