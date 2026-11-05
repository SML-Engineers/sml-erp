"""Overtime API (P2B-05). Rules live in overtime.py.

Overtime is seen and checked by HR and the Director and by each section's supervisors (who
hold HR and payroll: View for attendance); the service decides whose employees each sees."""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.access import division_scope, effective_access
from apps.core.permissions import AreaAccess

from . import overtime, periods
from .models import PayPeriodRule, WorkRule
from .overtime import OvertimeError, minutes_text
from .views import _Employees, _name


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _rule(r: WorkRule) -> dict:
    return {
        "id": r.pk,
        "division": r.division.code,
        "effective_from": r.effective_from.isoformat()[:7],
        **{name: getattr(r, name) for name in overtime.MINUTE_FIELDS},
        **{name: f"{getattr(r, name):.2f}" for name in overtime.RATE_FIELDS},
        "reason": r.reason,
        "created_by": _name(r.created_by),
        "can_withdraw": not overtime.in_force(r),
    }


class WorkRuleListView(_Employees):
    access_write_level = "manage"

    def get(self, request):
        rules = WorkRule.objects.filter(division__in=division_scope(request.user)).select_related(
            "division", "created_by"
        )
        return Response(
            {
                "results": [_rule(r) for r in rules],
                "divisions": list(division_scope(request.user).values_list("code", flat=True)),
                "can_manage": effective_access(request.user).has("hr_payroll", "manage"),
            }
        )

    def post(self, request):
        try:
            rule = overtime.add_rule(request.user, request.data.get("division"), request.data)
        except OvertimeError as error:
            return _error(error)
        return Response(_rule(rule), status=status.HTTP_201_CREATED)


class WorkRuleDetailView(_Employees):
    access_write_level = "manage"

    def delete(self, request, pk):
        rule = get_object_or_404(WorkRule, pk=pk, division__in=division_scope(request.user))
        try:
            overtime.withdraw_rule(request.user, rule, request.data.get("reason", ""))
        except OvertimeError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class _Overtime(APIView):
    permission_classes = [AreaAccess]
    access_area = "hr_payroll"
    access_write_level = "view"  # the service decides who checks whom


class OvertimeView(_Overtime):
    def get(self, request):
        month = request.query_params.get("month")
        if not month:
            month = periods.last_pay_month().isoformat()[:7]
        divisions = list(division_scope(request.user).filter(is_active=True).order_by("code"))
        code = request.query_params.get("division") or (divisions[0].code if divisions else "")
        try:
            division, first, confirmed, rows = overtime.division_month(request.user, code, month)
        except (OvertimeError, overtime.attendance.AttendanceError) as error:
            return _error(error)
        rule = overtime.rule_for(division.pk, first)
        return Response(
            {
                "month": first.isoformat()[:7],
                "period": periods.label(first),
                "division": division.code,
                "divisions": [d.code for d in divisions],
                "confirmed": confirmed,
                "rule": _rule(rule) if rule else None,
                "rows": [
                    {
                        "employee": {
                            "id": m.employee.pk,
                            "number": m.employee.number,
                            "name": m.employee.full_name,
                            "section": m.employee.section.code if m.employee.section else "",
                        },
                        "ot_working": minutes_text(m.ot_working),
                        "ot_sunday": minutes_text(m.ot_sunday),
                        "ot_holiday": minutes_text(m.ot_holiday),
                        "short": minutes_text(m.short_minutes),
                        "short_leaves": m.short_leaves,
                        "nopay_time": minutes_text(m.nopay_minutes),
                        "nopay_days": f"{m.nopay_days:.1f}",
                        "checked_by": _name(m.check.checked_by) if m.check else None,
                        "checked_at": m.check.checked_at if m.check else None,
                        "can_check": confirmed
                        and m.check is None
                        and overtime.can_check(request.user, m.employee),
                    }
                    for m in rows
                ],
            }
        )


class OvertimeCheckView(_Overtime):
    def post(self, request):
        try:
            count = overtime.check(
                request.user,
                request.data.get("division"),
                request.data.get("month"),
                request.data.get("employees"),
            )
        except (OvertimeError, overtime.attendance.AttendanceError, ValueError, TypeError) as error:
            return _error(error)
        return Response({"checked": count})


# --- Pay period (P2B-15) -------------------------------------------------------------------------


def _period_rule(r: PayPeriodRule) -> dict:
    return {
        "id": r.pk,
        "effective_from": r.effective_from.isoformat()[:7],
        "start_day": r.start_day,
        "reason": r.reason,
        "created_by": _name(r.created_by),
        "can_withdraw": periods.can_withdraw(r),
    }


class PayPeriodListView(_Employees):
    access_write_level = "manage"

    def get(self, request):
        current = periods.pay_month_of(timezone.localdate())
        return Response(
            {
                "results": [
                    _period_rule(r) for r in PayPeriodRule.objects.select_related("created_by")
                ],
                "current": periods.label(current),
                "last": periods.label(periods.previous_month(current)),
                "can_manage": effective_access(request.user).has("hr_payroll", "manage"),
            }
        )

    def post(self, request):
        try:
            rule = periods.add_rule(request.user, request.data)
        except periods.PeriodError as error:
            return _error(error)
        return Response(_period_rule(rule), status=status.HTTP_201_CREATED)


class PayPeriodDetailView(_Employees):
    access_write_level = "manage"

    def delete(self, request, pk):
        rule = get_object_or_404(PayPeriodRule, pk=pk)
        try:
            periods.withdraw_rule(request.user, rule, request.data.get("reason", ""))
        except periods.PeriodError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)
