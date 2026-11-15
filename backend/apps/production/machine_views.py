"""Machine time API (backlog P3-24 a): the machine board, start and finish jobs."""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.access import has_access
from apps.core.permissions import AreaAccess, IsFullyAuthenticated

from . import machine_jobs
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
