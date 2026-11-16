"""Machine time API (backlog P3-24): the machine board, start and finish jobs, the
Dashboard panel and the machine hours report."""

from datetime import date

from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.access import has_access
from apps.core.permissions import AreaAccess, IsFullyAuthenticated

from . import machine_hours, machine_jobs
from .machine_hours import MachineHoursError
from .machine_jobs import MachineJobError


def _error(error) -> Response:
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class EnterOrApprove(AreaAccess):
    """Changes need Enter (team leader, supervisor) or Approve (the Production Manager, who
    may also start a second job on a busy machine)."""

    def has_permission(self, request, view):
        if super().has_permission(request, view):
            return True
        return (
            IsFullyAuthenticated.has_permission(self, request, view)
            and request.method not in ("GET", "HEAD", "OPTIONS")
            and has_access(request.user, view.access_area, "approve")
        )


class _MachineTime(APIView):
    permission_classes = [EnterOrApprove]
    access_area = "machine_time"
    access_write_level = "enter"


class MachineBoardView(_MachineTime):
    def get(self, request):
        return Response(machine_jobs.board(request.user))


class MachineTodayView(_MachineTime):
    """The Dashboard's machine panel (P3-24 d)."""

    def get(self, request):
        return Response(machine_jobs.today(request.user))


class MachineJobListView(_MachineTime):
    def get(self, request):
        return Response({"results": machine_jobs.recent(request.user)})

    def post(self, request):
        try:
            job = machine_jobs.start(request.user, request.data)
        except MachineJobError as error:
            return _error(error)
        return Response(machine_jobs.payload(job), status=status.HTTP_201_CREATED)


class MachineJobFinishView(_MachineTime):
    def post(self, request, pk):
        try:
            job = machine_jobs.finish(request.user, pk, request.data)
        except MachineJobError as error:
            return _error(error)
        return Response(machine_jobs.payload(job))


class MachineJobOptionsView(_MachineTime):
    def get(self, request):
        try:
            return Response(machine_jobs.options(request.user, request.query_params.get("machine")))
        except MachineJobError as error:
            return _error(error)


class MachineHoursView(_MachineTime):
    """The machine hours report (P3-24 e)."""

    def get(self, request):
        q = request.query_params
        try:
            today = timezone.localdate()
            start = date.fromisoformat(q.get("start") or today.replace(day=1).isoformat())
            end = date.fromisoformat(q.get("end") or today.isoformat())
            return Response(machine_hours.report(request.user, start, end, q.get("by") or "day"))
        except ValueError:
            return _error("Give the dates as YYYY-MM-DD.")
        except MachineHoursError as error:
            return _error(error)
