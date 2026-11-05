"""Employee API (P2B-01). Rules live in employees.py; these views only translate.

Personal details are shown only to HR (HR and payroll: Enter) and the Director (Approve).
The Accountant's "totals only" view of payroll gets no employee list: `employees.visible`
returns nothing for them.
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals
from apps.core.permissions import AreaAccess

from . import changes, employees, overtime, pay, periods
from .changes import ChangeError
from .employees import EmployeeError
from .models import SETTING_FIELDS, Employee, LeaveType, PayChange, PayComponent, PayRate
from .models import setting_on as _setting_on
from .pay import PayError

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class _Employees(APIView):
    permission_classes = [AreaAccess]
    access_area = "hr_payroll"
    access_write_level = "enter"

    def check_permissions(self, request):
        super().check_permissions(request)
        if not employees.can_view(request.user):
            self.permission_denied(request, message="Only HR and the Director see employees.")


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _name(user):
    return user.full_name if user else None


def _row(e: Employee) -> dict:
    return {
        "id": e.pk,
        "number": e.number,
        "full_name": e.full_name,
        "designation": e.designation,
        "division": e.division.code,
        "section": e.section.code if e.section else "",
        "employment_type": e.employment_type,
        "employment_type_label": e.get_employment_type_display(),
        "category": e.category,
        "category_label": e.get_category_display(),
        "join_date": e.join_date,
        "is_active": e.is_active,
        "bank_check_pending": e.bank_check_pending,
    }


def _detail(e: Employee, user) -> dict:
    return _row(e) | {
        "name_with_initials": e.name_with_initials,
        "nic": e.nic,
        "date_of_birth": e.date_of_birth,
        "address": e.address,
        "phone": e.phone,
        "email": e.email,
        "epf_no": e.epf_no,
        "etf_no": e.etf_no,
        "grade": e.grade,
        "confirmation_date": e.confirmation_date,
        "leaving_date": e.leaving_date,
        "leaving_reason": e.leaving_reason,
        "user": None if e.user is None else {"id": e.user.pk, "name": e.user.full_name},
        "bank_name": e.bank_name,
        "bank_branch": e.bank_branch,
        "account_name": e.account_name,
        "account_number": e.account_number,
        "bank_changed_at": e.bank_changed_at,
        "bank_changed_by": _name(e.bank_changed_by),
        "bank_checked_at": e.bank_checked_at,
        "bank_checked_by": _name(e.bank_checked_by),
        "created_by": _name(e.created_by),
        "created_at": e.created_at,
        "can_edit": e.is_active and employees.can_edit(user),
        "can_check_bank": e.bank_check_pending
        and employees.can_check_bank(user)
        and e.bank_changed_by_id != user.pk,
    }


class EmployeeListView(_Employees):
    def get(self, request):
        rows = employees.search(employees.visible(request.user), request.query_params.get("q"))
        state = request.query_params.get("status", "active")
        if state == "active":
            rows = rows.filter(is_active=True)
        elif state == "left":
            rows = rows.filter(is_active=False)
        if request.query_params.get("division"):
            rows = rows.filter(division__code=request.query_params["division"].upper())
        if request.query_params.get("bank_check") == "pending":
            rows = [e for e in rows if e.bank_check_pending]
        return Response(
            {
                "results": [_row(e) for e in rows],
                "can_add": employees.can_edit(request.user),
                "types": [{"value": v, "label": label} for v, label in Employee.Type.choices],
                "categories": [
                    {"value": v, "label": label} for v, label in Employee.Category.choices
                ],
            }
        )

    def post(self, request):
        try:
            employee = employees.create(request.user, request.data)
        except EmployeeError as error:
            return _error(error)
        return Response(_detail(employee, request.user), status=status.HTTP_201_CREATED)


class EmployeeDetailView(_Employees):
    def _get(self, request, pk):
        return get_object_or_404(employees.visible(request.user), pk=pk)

    def get(self, request, pk):
        return Response(_detail(self._get(request, pk), request.user))

    def patch(self, request, pk):
        employee = self._get(request, pk)
        values = {k: v for k, v in request.data.items() if k != "reason"}
        try:
            employee = employees.update(
                request.user, employee, values, request.data.get("reason", "")
            )
        except EmployeeError as error:
            return _error(error)
        return Response(_detail(employee, request.user))


class EmployeeBankCheckView(_Employees):
    # The Director (HR and payroll: Approve, not Enter) checks bank accounts.
    def get_permissions(self):
        self.access_write_level = "approve"
        return super().get_permissions()

    def post(self, request, pk):
        employee = get_object_or_404(employees.visible(request.user), pk=pk)
        try:
            employee = employees.check_bank(request.user, employee)
        except EmployeeError as error:
            return _error(error)
        return Response(_detail(employee, request.user))


class EmployeeLeaveView(_Employees):
    def post(self, request, pk):
        employee = get_object_or_404(employees.visible(request.user), pk=pk)
        on = parse_date(str(request.data.get("leaving_date") or ""))
        if on is None:
            return _error("Give the leaving date.")
        try:
            employee = employees.leave(request.user, employee, on, request.data.get("reason", ""))
        except EmployeeError as error:
            return _error(error)
        return Response(_detail(employee, request.user))


class EmployeeExcelView(_Employees):
    parser_classes = [MultiPartParser]

    def get(self, request):
        if request.query_params.get("template"):
            rows, name = [], "employee-template.xlsx"
        elif not employees.can_export(request.user):
            return Response(
                {"detail": "Exporting employees' personal details needs that permission."},
                status=status.HTTP_403_FORBIDDEN,
            )
        else:
            rows, name = employees.visible(request.user), "employees.xlsx"
        response = HttpResponse(employees.export_workbook(rows), content_type=XLSX)
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response

    def post(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose an Excel file to import.")
        if uploaded.size > employees.MAX_BYTES:
            return _error("The file is larger than 5 MB.")
        dry_run = str(request.data.get("dry_run", "true")).lower() != "false"
        try:
            result = employees.import_workbook(
                request.user,
                uploaded.read(),
                dry_run=dry_run,
                reason=request.data.get("reason", ""),
            )
        except EmployeeError as error:
            return _error(error)
        return Response(result)


# --- Pay structure (P2B-02) ------------------------------------------------------------------


def _component(c: PayComponent) -> dict:
    return {
        "id": c.pk,
        "code": c.code,
        "name": c.name,
        "kind": c.kind,
        "basis": c.basis,
        "epf_liable": c.epf_liable,
        "apit_taxable": c.apit_taxable,
        "is_allowance": c.is_allowance,
        "sort_order": c.sort_order,
        "is_active": c.is_active,
    }


def _rate(r: PayRate) -> dict:
    return {
        "id": r.pk,
        "component": r.component.code,
        "component_name": r.component.name,
        "kind": r.component.kind,
        "effective_from": r.effective_from.isoformat()[:7],
        "amount": f"{r.amount:.2f}",
        "epf_liable": r.epf_liable,
        "apit_taxable": r.apit_taxable,
        "reason": r.reason,
        "created_by": _name(r.created_by),
        "created_at": r.created_at,
    }


class PayComponentListView(_Employees):
    access_write_level = "manage"

    def get(self, request):
        return Response(
            {
                "results": [_component(c) for c in PayComponent.objects.all()],
                "can_manage": pay.can_manage_components(request.user),
            }
        )

    def post(self, request):
        try:
            component = pay.save_component(request.user, request.data)
        except PayError as error:
            return _error(error)
        return Response(_component(component), status=status.HTTP_201_CREATED)


class PayComponentDetailView(_Employees):
    access_write_level = "manage"

    def patch(self, request, pk):
        component = get_object_or_404(PayComponent, pk=pk)
        values = {k: v for k, v in request.data.items() if k != "reason"}
        try:
            component = pay.save_component(
                request.user, values, component, request.data.get("reason", "")
            )
        except PayError as error:
            return _error(error)
        return Response(_component(component))


def _value(v):
    return None if v is None else str(v)


def _settings(x) -> dict:
    return {field: _value(getattr(x, field)) for field in SETTING_FIELDS}


def _defaults(e: Employee) -> dict:
    """What applies when the employee has no setting of their own: the division's work rule and
    the category's leave (P2B-16)."""
    rule = overtime.rule_for(e.division_id, periods.pay_month_of(timezone.localdate()))
    out = {
        field: _value(getattr(rule, field, None)) if rule else None
        for field in (
            "normal_day_minutes",
            "grace_minutes",
            "rate_working_day",
            "rate_sunday",
            "rate_holiday",
        )
    }
    for code, field in (("ANNUAL", "annual_leave_days"), ("CASUAL", "casual_leave_days")):
        kind = LeaveType.objects.filter(code=code).first()
        out[field] = _value(kind.rule_for(e.category)[1]) if kind else None
    out["apit"] = "primary"
    return out


def _change(c: PayChange, user) -> dict:
    state = approvals.state_of(changes.DOC, c.pk)
    mine = c.created_by_id == user.pk
    open_ = c.status in changes.OPEN
    return {
        "id": c.pk,
        "effective_from": c.effective_from.isoformat()[:7],
        "is_new_employee": c.is_new_employee,
        "reason": c.reason,
        "status": c.status,
        "status_label": c.get_status_display(),
        "returned": bool(state and state.status == state.Status.RETURNED),
        "lines": [
            {
                "component": x.component.code,
                "component_name": x.component.name,
                "kind": x.component.kind,
                "amount": f"{x.amount:.2f}",
                "epf_liable": x.epf_liable,
                "apit_taxable": x.apit_taxable,
            }
            for x in c.lines.select_related("component")
        ],
        "settings": _settings(c) if c.has_settings else None,
        "created_by": _name(c.created_by),
        "created_at": c.created_at,
        "approved_at": c.approved_at,
        "history": [
            {
                "action": h.get_action_display(),
                "user": _name(h.user),
                "reason": h.reason,
                "at": h.acted_at,
            }
            for h in (approvals.history(changes.DOC, c.pk) if state else [])
        ],
        "can_edit": c.status == PayChange.Status.DRAFT and mine,
        "can_submit": c.status == PayChange.Status.DRAFT and mine,
        "can_withdraw": open_ and changes.can_prepare(user),
        "can_approve": changes.can_approve(user, c),
    }


def _pay(e: Employee, user) -> dict:
    today = timezone.localdate()
    lines = pay.amounts_on(e, today)
    upcoming = (
        PayRate.objects.filter(employee=e, effective_from__gt=today)
        .select_related("component", "created_by")
        .order_by("effective_from", "component__sort_order")
    )
    history = (
        PayRate.objects.filter(employee=e)
        .select_related("component", "created_by")
        .order_by("-effective_from", "component__kind", "component__sort_order")
    )
    own = _setting_on(e, today)
    return {
        "on": today,
        "current": [
            {
                "component": x.component.code,
                "component_name": x.component.name,
                "kind": x.component.kind,
                "epf_liable": x.epf_liable,
                "apit_taxable": x.apit_taxable,
                "own_marks": x.rate.epf_liable is not None or x.rate.apit_taxable is not None,
                "amount": f"{x.amount:.2f}",
                "since": x.rate.effective_from.isoformat()[:7],
            }
            for x in lines
        ],
        "totals": {k: f"{v:.2f}" for k, v in pay.totals(lines).items()},
        "upcoming": [_rate(r) for r in upcoming],
        "history": [_rate(r) for r in history],
        "components": [_component(c) for c in PayComponent.objects.filter(is_active=True)],
        "settings": _settings(own) if own else None,
        "settings_since": own.effective_from.isoformat()[:7] if own else None,
        "defaults": _defaults(e),
        "changes": [
            _change(c, user)
            for c in e.pay_changes.select_related("created_by").order_by("-created_at", "-id")
        ],
        "next_month": periods.next_month(periods.pay_month_of(today)).isoformat()[:7],
        "can_prepare": e.is_active
        and changes.can_prepare(user)
        and not e.pay_changes.filter(status__in=changes.OPEN).exists(),
    }


class EmployeePayView(_Employees):
    def get(self, request, pk):
        e = get_object_or_404(employees.visible(request.user), pk=pk)
        return Response(_pay(e, request.user))


class PayChangeListView(_Employees):
    """HR prepares a pay change for an employee (P2B-17)."""

    def post(self, request, pk):
        e = get_object_or_404(employees.visible(request.user), pk=pk)
        try:
            changes.prepare(request.user, e, request.data)
        except ChangeError as error:
            return _error(error)
        return Response(_pay(e, request.user), status=status.HTTP_201_CREATED)


class PayChangeDetailView(_Employees):
    def put(self, request, pk):
        change = get_object_or_404(PayChange, pk=pk, employee__in=employees.visible(request.user))
        try:
            changes.edit(request.user, change, request.data)
        except ChangeError as error:
            return _error(error)
        return Response(_pay(change.employee, request.user))


ACTIONS = {
    "submit": lambda user, c, text: changes.submit(user, c, text),
    "approve": lambda user, c, text: changes.approve(user, c, text),
    "return": lambda user, c, text: changes.send_back(user, c, text),
    "reject": lambda user, c, text: changes.reject(user, c, text),
    "withdraw": lambda user, c, text: changes.withdraw(user, c, text),
}


class PayChangeActionView(_Employees):
    """Submit or withdraw (HR), approve, return or reject (the Director): the service decides
    who may (rule 5: never the person who prepared it)."""

    access_write_level = "view"

    def post(self, request, pk, action):
        change = get_object_or_404(PayChange, pk=pk, employee__in=employees.visible(request.user))
        act = ACTIONS.get(action)
        if act is None:
            return _error("Unknown action.")
        try:
            act(request.user, change, request.data.get("reason", ""))
        except ChangeError as error:
            return _error(error)
        return Response(_pay(change.employee, request.user))
