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

from apps.core.permissions import AreaAccess

from . import employees, pay
from .employees import EmployeeError
from .models import Employee, PayComponent, PayRate
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
        "reason": r.reason,
        "created_by": _name(r.created_by),
        "created_at": r.created_at,
        "can_withdraw": r.effective_from > timezone.localdate(),
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
    return {
        "on": today,
        "current": [
            {
                "component": x.component.code,
                "component_name": x.component.name,
                "kind": x.component.kind,
                "epf_liable": x.component.epf_liable,
                "apit_taxable": x.component.apit_taxable,
                "amount": f"{x.amount:.2f}",
                "since": x.rate.effective_from.isoformat()[:7],
            }
            for x in lines
        ],
        "totals": {k: f"{v:.2f}" for k, v in pay.totals(lines).items()},
        "upcoming": [_rate(r) for r in upcoming],
        "history": [_rate(r) for r in history],
        "components": [_component(c) for c in PayComponent.objects.filter(is_active=True)],
        "can_edit": e.is_active and employees.can_edit(user),
    }


class EmployeePayView(_Employees):
    def get(self, request, pk):
        e = get_object_or_404(employees.visible(request.user), pk=pk)
        return Response(_pay(e, request.user))

    def post(self, request, pk):
        e = get_object_or_404(employees.visible(request.user), pk=pk)
        component = PayComponent.objects.filter(
            code=str(request.data.get("component") or "").upper()
        ).first()
        if component is None:
            return _error("Choose a pay component.")
        try:
            pay.add_rate(
                request.user,
                e,
                component,
                request.data.get("month"),
                request.data.get("amount"),
                request.data.get("reason", ""),
            )
        except PayError as error:
            return _error(error)
        return Response(_pay(e, request.user), status=status.HTTP_201_CREATED)


class EmployeePayRateView(_Employees):
    def delete(self, request, pk, rate_pk):
        e = get_object_or_404(employees.visible(request.user), pk=pk)
        rate = get_object_or_404(PayRate, pk=rate_pk, employee=e)
        try:
            pay.withdraw_rate(request.user, rate, request.data.get("reason", ""))
        except PayError as error:
            return _error(error)
        return Response(_pay(e, request.user))
