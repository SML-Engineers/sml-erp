"""Attendance API (P2B-04). Rules live in attendance.py."""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from apps.core.access import division_scope

from . import attendance, employees, periods
from .attendance import AttendanceError
from .models import AttendanceDay, AttendanceMonth
from .views import XLSX, _Employees, _name


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _hm(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d}"


def _month(request):
    value = request.query_params.get("month")
    if not value:
        return periods.last_pay_month()
    return attendance.first_of(value)


class AttendanceView(_Employees):
    """A division's month: whether it is confirmed, and each employee's totals."""

    def get(self, request):
        try:
            month = _month(request)
        except AttendanceError as error:
            return _error(error)
        divisions = list(division_scope(request.user).filter(is_active=True).order_by("code"))
        code = request.query_params.get("division") or (divisions[0].code if divisions else "")
        division = next((d for d in divisions if d.code == code.upper()), None)
        if division is None:
            return _error("Choose one of your divisions.")
        record = AttendanceMonth.objects.filter(division=division, month=month).first()
        rows = attendance.month_summary(request.user, division, month)
        confirmed = bool(record and record.confirmed)
        period = periods.label(month)
        return Response(
            {
                "month": month.isoformat()[:7],
                "period": period,
                "division": division.code,
                "divisions": [d.code for d in divisions],
                "confirmed": confirmed,
                "confirmed_by": _name(record.confirmed_by) if confirmed else None,
                "confirmed_at": record.confirmed_at if confirmed else None,
                "can_edit": employees.can_edit(request.user),
                "month_ended": period["end"] < timezone.localdate().isoformat(),
                "rows": [
                    {
                        "employee": {
                            "id": r.employee.pk,
                            "number": r.employee.number,
                            "name": r.employee.full_name,
                        },
                        "working_days": r.working_days,
                        "days_worked": r.days_worked,
                        "hours_worked": _hm(r.minutes_worked),
                        "late_days": r.late_days,
                        "late": _hm(r.late_minutes),
                        "early": _hm(r.early_minutes),
                        "leave_days": f"{r.leave_days:.1f}",
                        "absent_days": r.absent_days,
                    }
                    for r in rows
                ],
            }
        )


class AttendanceDaysView(_Employees):
    def get(self, request, pk):
        person = get_object_or_404(employees.visible(request.user), pk=pk)
        try:
            month = _month(request)
        except AttendanceError as error:
            return _error(error)
        days = AttendanceDay.objects.filter(
            employee=person, date__range=periods.pay_period(month)
        ).select_related("shift", "leave_type")
        return Response(
            {
                "month": month.isoformat()[:7],
                "period": periods.label(month),
                "days": [
                    {
                        "date": d.date,
                        "shift": d.shift.code if d.shift else "",
                        "time_in": d.time_in.strftime("%H:%M") if d.time_in else "",
                        "time_out": d.time_out.strftime("%H:%M") if d.time_out else "",
                        "leave": d.leave_type.code if d.leave_type else "",
                        "worked": _hm(d.worked_minutes),
                        "late": d.late_minutes,
                        "early": d.early_minutes,
                        "remarks": d.remarks,
                    }
                    for d in days
                ],
            }
        )


class AttendanceTemplateView(_Employees):
    def get(self, request):
        response = HttpResponse(attendance.template(), content_type=XLSX)
        response["Content-Disposition"] = 'attachment; filename="attendance-template.xlsx"'
        return response


class AttendanceImportView(_Employees):
    parser_classes = [MultiPartParser]

    def post(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose an Excel file to upload.")
        if uploaded.size > attendance.MAX_BYTES:
            return _error("The file is larger than 5 MB.")
        dry_run = str(request.data.get("dry_run", "true")).lower() != "false"
        try:
            result = attendance.import_sheet(
                request.user, uploaded.read(), uploaded.name, dry_run=dry_run
            )
        except AttendanceError as error:
            return _error(error)
        return Response(result)


class AttendanceMonthActionView(_Employees):
    action = ""

    def post(self, request):
        try:
            if self.action == "confirm":
                attendance.confirm(
                    request.user, request.data.get("division"), request.data.get("month")
                )
            else:
                attendance.reopen(
                    request.user,
                    request.data.get("division"),
                    request.data.get("month"),
                    request.data.get("reason", ""),
                )
        except AttendanceError as error:
            return _error(error)
        return Response({"ok": True})
