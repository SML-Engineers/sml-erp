"""Employees ask to change their own details (backlog P2B-20).

- On the self-service page an employee asks to change their **phone, address, email** or
  **salary account** (bank, branch, account name and number), with a note. The values are
  checked as HR's would be. One request waits at a time; it can be withdrawn until decided.
- **HR decides** (approve or reject with a reason), never the employee themselves (rule 5).
  Approving changes the employee record exactly as HR's own change would, recorded in the
  audit log with the request; a new salary account then still waits for the Director's check
  (P2B-01) before any salary is paid to it, and nobody checks their own account.
- A request whose fields have been changed by HR since it was made is refused at approval,
  so an old request never overwrites newer details.
- Requests are never deleted, and once decided never change (database).
"""

from django.db import transaction
from django.utils import timezone

from apps.core.audit import audit_context
from apps.core.models import User

from . import employees
from .employees import BANK_FIELDS, EmployeeError
from .models import DetailChange, Employee

FIELDS = ("phone", "address", "email") + BANK_FIELDS


class DetailChangeError(Exception):
    pass


def _mine(user: User) -> Employee:
    employee = Employee.objects.filter(user=user).first()
    if employee is None:
        raise DetailChangeError(
            "Your sign-in is not linked to an employee record yet. Ask HR to link it."
        )
    return employee


def current(employee: Employee) -> dict:
    return {f: getattr(employee, f) or "" for f in FIELDS}


def ask(user: User, values: dict, note: str = "") -> DetailChange:
    employee = _mine(user)
    if not employee.is_active:
        raise DetailChangeError("You are no longer employed; ask HR.")
    before = current(employee)
    wanted = {
        f: " ".join(str(values[f] or "").split())
        for f in FIELDS
        if f in values and " ".join(str(values[f] or "").split()) != before[f]
    }
    if not wanted:
        raise DetailChangeError("Nothing is different from your details now.")
    if any(f in wanted for f in BANK_FIELDS) and not wanted.get("account_number", "x"):
        raise DetailChangeError("Give the account number.")
    try:
        # The same checks as HR's own change (email, account number).
        employees.clean(user, wanted, employee)
    except EmployeeError as error:
        raise DetailChangeError(str(error)) from None
    with audit_context("detail_change_asked", ""), transaction.atomic():
        Employee.objects.select_for_update().get(pk=employee.pk)
        if employee.detail_changes.filter(status=DetailChange.Status.WAITING).exists():
            raise DetailChangeError(
                "You already have a request waiting for HR; withdraw it to ask again."
            )
        return DetailChange.objects.create(
            employee=employee,
            wanted=wanted,
            before={f: before[f] for f in wanted},
            note=" ".join((note or "").split())[:200],
            created_by=user,
        )


def withdraw(user: User, change_id) -> DetailChange:
    employee = _mine(user)
    with audit_context("detail_change_withdrawn", ""), transaction.atomic():
        change = (
            DetailChange.objects.select_for_update().filter(employee=employee, pk=change_id).first()
        )
        if change is None:
            raise DetailChangeError("There is no such request of yours.")
        if change.status != DetailChange.Status.WAITING:
            raise DetailChangeError("Only a request still waiting for HR can be withdrawn.")
        change.status = DetailChange.Status.WITHDRAWN
        change.decided_by, change.decided_at = user, timezone.now()
        change.save(update_fields=["status", "decided_by", "decided_at"])
        return change


def waiting(user: User):
    """The requests HR can decide: waiting, in the user's divisions, never their own."""
    if not employees.can_edit(user):
        return DetailChange.objects.none()
    return (
        DetailChange.objects.filter(
            status=DetailChange.Status.WAITING, employee__in=employees.visible(user)
        )
        .exclude(employee__user=user)
        .select_related("employee", "created_by")
        .order_by("created_at")
    )


def decide(user: User, change_id, approve: bool, reason: str = "") -> DetailChange:
    if not employees.can_edit(user):
        raise DetailChangeError("Only HR decides requests to change details.")
    reason = " ".join((reason or "").split())
    if not approve and not reason:
        raise DetailChangeError("Give the reason for rejecting.")
    with audit_context("detail_change_decided", reason), transaction.atomic():
        change = (
            DetailChange.objects.select_for_update()
            .filter(pk=change_id, employee__in=employees.visible(user))
            .select_related("employee")
            .first()
        )
        if change is None:
            raise DetailChangeError("There is no such request.")
        if change.employee.user_id == user.pk or change.created_by_id == user.pk:
            raise DetailChangeError("Nobody decides a request to change their own details.")
        if change.status != DetailChange.Status.WAITING:
            raise DetailChangeError("This request is already decided.")
        if approve:
            now = current(change.employee)
            moved = [f for f, was in change.before.items() if now.get(f) != was]
            if moved:
                raise DetailChangeError(
                    "HR has changed these details since the request was made: "
                    + ", ".join(f.replace("_", " ") for f in moved)
                    + ". Reject it and ask the employee to ask again."
                )
            try:
                employees.update(
                    user,
                    change.employee,
                    change.wanted,
                    reason=f"Asked by the employee on {change.created_at:%Y-%m-%d}"
                    + (f": {change.note}" if change.note else ""),
                )
            except EmployeeError as error:
                raise DetailChangeError(str(error)) from None
        change.status = DetailChange.Status.APPROVED if approve else DetailChange.Status.REJECTED
        change.decided_by, change.decided_at = user, timezone.now()
        change.decision_note = reason[:200]
        change.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
        return change


def row(change: DetailChange) -> dict:
    return {
        "id": change.pk,
        "employee": f"{change.employee.number} {change.employee.full_name}",
        "employee_id": change.employee_id,
        "changes": [
            {"field": f, "before": change.before.get(f, ""), "after": value}
            for f, value in change.wanted.items()
        ],
        "bank": any(f in change.wanted for f in BANK_FIELDS),
        "note": change.note,
        "status": change.status,
        "status_label": change.get_status_display(),
        "created_at": change.created_at,
        "decision_note": change.decision_note,
    }
