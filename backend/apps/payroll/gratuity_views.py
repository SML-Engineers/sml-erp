"""Gratuity page (P2B-19): the Accountant enters settings, the Director approves."""

from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import AreaAccess

from . import gratuity
from .gratuity import GratuityError


def _error(error) -> Response:
    return Response({"detail": str(error)}, status=400)


class _Gratuity(APIView):
    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "view"  # the service checks who may enter and who approves


class GratuityView(_Gratuity):
    def get(self, request):
        return Response(
            {
                "results": gratuity.overview(request.user),
                "can_enter": gratuity.can_enter(request.user),
            }
        )

    def post(self, request):
        employee = get_object_or_404(
            gratuity.visible(request.user), pk=request.data.get("employee_id") or 0
        )
        try:
            gratuity.propose(request.user, employee, request.data)
        except GratuityError as error:
            return _error(error)
        return self.get(request)


class GratuitySettingView(_Gratuity):
    """approve, reject or withdraw ({reason})."""

    def post(self, request, pk, action):
        try:
            gratuity.decide(request.user, pk, action, request.data.get("reason", ""))
        except GratuityError as error:
            return _error(error)
        return GratuityView().get(request)
