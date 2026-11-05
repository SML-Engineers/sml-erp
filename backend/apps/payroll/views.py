"""Employee API (P2B-01). Rules live in employees.py; these views only translate.

Personal details are shown only to HR (HR and payroll: Enter) and the Director (Approve).
The Accountant's "totals only" view of payroll gets no employee list: `employees.visible`
returns nothing for them.
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import AreaAccess

from . import employees
from .employees import EmployeeError
from .models import Employee

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
