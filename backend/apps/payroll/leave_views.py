"""Holidays and leave API (P2B-03). Rules live in leave.py."""

from datetime import date

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from . import employees, leave
from .leave import LeaveError
from .models import Holiday, Leave, LeaveType
from .views import _Employees, _name


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _d(value) -> str:
    return f"{value:.1f}"


def _year(request) -> int:
    try:
        return int(request.query_params.get("year") or timezone.localdate().year)
    except ValueError:
        return timezone.localdate().year


def _holiday(h: Holiday) -> dict:
    return {
        "id": h.pk,
        "date": h.date,
        "name": h.name,
        "kind": h.kind,
        "kind_label": h.get_kind_display(),
        "can_remove": h.date > timezone.localdate(),
    }


def _type(t: LeaveType) -> dict:
    return {
        "id": t.pk,
        "code": t.code,
        "name": t.name,
        "rule": t.rule,
        "rule_label": t.get_rule_display(),
        "days": _d(t.days),
        "wb_rule": t.wb_rule,
        "wb_days": None if t.wb_days is None else _d(t.wb_days),
        "max_days": None if t.max_days is None else _d(t.max_days),
        "paid": t.paid,
        "carry_forward_max": _d(t.carry_forward_max),
        "is_active": t.is_active,
    }


def _leave(x: Leave, user) -> dict:
    mine = user.pk in (x.created_by_id, x.employee.user_id)
    return {
        "id": x.pk,
        "employee": {
            "id": x.employee.pk,
            "number": x.employee.number,
            "name": x.employee.full_name,
        },
        "leave_type": x.leave_type.code,
        "leave_type_name": x.leave_type.name,
        "start": x.start,
        "end": x.end,
        "half_day": x.half_day,
        "days": _d(x.days),
        "reason": x.reason,
        "status": x.status,
        "source": x.source,
        "created_by": _name(x.created_by),
        "decided_by": _name(x.decided_by),
        "decision_note": x.decision_note,
        "can_decide": x.status == Leave.Status.APPLIED and employees.can_edit(user) and not mine,
        "can_cancel": x.status in leave.OPEN and employees.can_edit(user),
    }


class HolidayListView(_Employees):
    access_write_level = "manage"

    def get(self, request):
        year = _year(request)
        rows = Holiday.objects.filter(date__year=year)
        return Response(
            {
                "year": year,
                "results": [_holiday(h) for h in rows],
                "kinds": [{"value": v, "label": label} for v, label in Holiday.Kind.choices],
                "can_manage": leave.can_manage(request.user),
            }
        )

    def post(self, request):
        try:
            holiday = leave.add_holiday(request.user, request.data)
        except LeaveError as error:
            return _error(error)
        return Response(_holiday(holiday), status=status.HTTP_201_CREATED)


class HolidayDetailView(_Employees):
    access_write_level = "manage"

    def delete(self, request, pk):
        holiday = get_object_or_404(Holiday, pk=pk)
        try:
            leave.remove_holiday(request.user, holiday, request.data.get("reason", ""))
        except LeaveError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LeaveTypeListView(_Employees):
    access_write_level = "manage"

    def get(self, request):
        return Response(
            {
                "results": [_type(t) for t in LeaveType.objects.all()],
                "rules": [{"value": v, "label": label} for v, label in LeaveType.Rule.choices],
                "can_manage": leave.can_manage(request.user),
            }
        )

    def post(self, request):
        try:
            kind = leave.save_leave_type(request.user, request.data)
        except LeaveError as error:
            return _error(error)
        return Response(_type(kind), status=status.HTTP_201_CREATED)


class LeaveTypeDetailView(_Employees):
    access_write_level = "manage"

    def patch(self, request, pk):
        kind = get_object_or_404(LeaveType, pk=pk)
        values = {k: v for k, v in request.data.items() if k != "reason"}
        try:
            kind = leave.save_leave_type(request.user, values, kind, request.data.get("reason", ""))
        except LeaveError as error:
            return _error(error)
        return Response(_type(kind))


class LeaveListView(_Employees):
    def get(self, request):
        rows = leave.search(leave.visible_leave(request.user), request.query_params.get("q"))
        year = _year(request)
        rows = rows.filter(start__year=year)
        state = request.query_params.get("status")
        if state:
            rows = rows.filter(status=state)
        if request.query_params.get("employee"):
            rows = rows.filter(employee_id=request.query_params["employee"])
        return Response(
            {
                "year": year,
                "results": [_leave(x, request.user) for x in rows[:500]],
                "types": [_type(t) for t in LeaveType.objects.filter(is_active=True)],
                "can_record": employees.can_edit(request.user),
            }
        )

    def post(self, request):
        person = get_object_or_404(employees.visible(request.user), pk=request.data.get("employee"))
        kind = LeaveType.objects.filter(
            code=str(request.data.get("leave_type") or "").upper()
        ).first()
        if kind is None:
            return _error("Choose the kind of leave.")
        try:
            taken = leave.record(
                request.user,
                person,
                kind,
                request.data.get("start"),
                request.data.get("end"),
                half_day=bool(request.data.get("half_day")),
                reason=request.data.get("reason", ""),
            )
        except LeaveError as error:
            return _error(error)
        return Response(_leave(taken, request.user), status=status.HTTP_201_CREATED)


class LeaveActionView(_Employees):
    action = ""

    def post(self, request, pk):
        found = get_object_or_404(leave.visible_leave(request.user), pk=pk)
        note = request.data.get("note") or request.data.get("reason") or ""
        try:
            if self.action == "cancel":
                found = leave.cancel(request.user, found, note)
            else:
                found = leave.decide(request.user, found, self.action == "approve", note)
        except LeaveError as error:
            return _error(error)
        return Response(_leave(found, request.user))


class LeaveGrantView(_Employees):
    def post(self, request):
        try:
            made = leave.grant_year(request.user, request.data.get("year"))
        except LeaveError as error:
            return _error(error)
        return Response(made)


class EmployeeLeaveBalanceView(_Employees):
    """An employee's balances for a year, and HR's adjustments."""

    def _body(self, person, year, user):
        rows = leave.balances(person, year)
        grants = person.leave_grants.filter(year=year).select_related("leave_type", "created_by")
        return {
            "year": year,
            "balances": [
                {
                    "leave_type": b.leave_type.code,
                    "name": b.leave_type.name,
                    "granted": _d(b.granted),
                    "taken": _d(b.taken),
                    "pending": _d(b.pending),
                    "available": _d(b.available),
                }
                for b in rows
            ],
            "grants": [
                {
                    "id": g.pk,
                    "leave_type": g.leave_type.code,
                    "kind": g.kind,
                    "days": _d(g.days),
                    "reason": g.reason,
                    "created_by": _name(g.created_by),
                    "created_at": g.created_at,
                }
                for g in grants
            ],
            "leave": [
                _leave(x, user)
                for x in leave.visible_leave(user).filter(employee=person, start__year=year)
            ],
            "can_adjust": person.is_active and employees.can_edit(user),
        }

    def get(self, request, pk):
        person = get_object_or_404(employees.visible(request.user), pk=pk)
        return Response(self._body(person, _year(request), request.user))

    def post(self, request, pk):
        person = get_object_or_404(employees.visible(request.user), pk=pk)
        kind = LeaveType.objects.filter(
            code=str(request.data.get("leave_type") or "").upper()
        ).first()
        if kind is None:
            return _error("Choose the kind of leave.")
        year = request.data.get("year") or date.today().year
        try:
            leave.adjust(
                request.user,
                person,
                kind,
                year,
                request.data.get("days"),
                request.data.get("reason", ""),
            )
        except LeaveError as error:
            return _error(error)
        return Response(self._body(person, int(year), request.user), status=status.HTTP_201_CREATED)
