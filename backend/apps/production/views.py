"""Production API (Phase 3). P3-01: moulds."""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.access import division_scope
from apps.core.permissions import AreaAccess
from apps.masters.models import Machine

from . import labels, moulds
from .models import Mould
from .moulds import ImportRefused, MouldError

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _error(error, code=status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"detail": str(error)}, status=code)


class _Planning(APIView):
    permission_classes = [AreaAccess]
    access_area = "production_planning"
    access_write_level = "enter"


class MouldListView(_Planning):
    def get(self, request):
        found = moulds.search(
            request.user,
            request.query_params.get("q", "").strip(),
            request.query_params.get("status", ""),
        )
        return Response(
            {
                "results": [moulds.payload(m) for m in found],
                "can_edit": moulds.can_edit(request.user),
                "statuses": [{"value": v, "label": label} for v, label in Mould.Status.choices],
                # The moulding machines a mould can be set against.
                "machines": [
                    {"code": m.code, "name": m.name}
                    for m in Machine.objects.filter(
                        section__section_type="moulding",
                        section__division__in=division_scope(request.user),
                    ).exclude(status=Machine.Status.RETIRED)
                ],
            }
        )

    def post(self, request):
        try:
            mould = moulds.create(request.user, request.data)
        except MouldError as error:
            return _error(error)
        return Response(moulds.payload(mould), status=status.HTTP_201_CREATED)


class MouldDetailView(_Planning):
    def _mould(self, request, pk) -> Mould:
        return get_object_or_404(moulds.visible(request.user), pk=pk)

    def get(self, request, pk):
        return Response(moulds.payload(self._mould(request, pk)))

    def patch(self, request, pk):
        try:
            mould = moulds.update(request.user, self._mould(request, pk), request.data)
        except MouldError as error:
            return _error(error)
        return Response(moulds.payload(mould))

    def delete(self, request, pk):
        try:
            moulds.delete(request.user, self._mould(request, pk))
        except MouldError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MouldFitView(_Planning):
    """Whether a mould fits a machine: ?machine=CODE."""

    def get(self, request, pk):
        mould = get_object_or_404(moulds.visible(request.user), pk=pk)
        machine = get_object_or_404(Machine, code=request.query_params.get("machine", "").upper())
        return Response({"machine": machine.code, "warnings": moulds.fit(mould, machine)})


class MouldExportView(_Planning):
    def get(self, request):
        response = HttpResponse(moulds.export_workbook(request.user), content_type=XLSX)
        today = timezone.localdate().isoformat()
        response["Content-Disposition"] = f'attachment; filename="moulds-{today}.xlsx"'
        return response


class MouldImportView(_Planning):
    parser_classes = [MultiPartParser]

    def post(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose an Excel file to import.")
        dry_run = str(request.data.get("dry_run", "true")).lower() not in ("false", "0", "no")
        try:
            result = moulds.import_workbook(request.user, uploaded.read(), dry_run=dry_run)
        except ImportRefused as refused:
            return Response(
                {"detail": "Nothing was imported.", "errors": refused.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(result)


class MouldLabelsView(_Planning):
    """QR labels: ?ids=1,2,3 (all shown moulds when empty)."""

    def get(self, request):
        found = moulds.visible(request.user).filter(status__in=["active", "maintenance"])
        ids = [int(x) for x in request.query_params.get("ids", "").split(",") if x.isdigit()]
        if ids:
            found = found.filter(pk__in=ids)
        response = HttpResponse(
            labels.render(found.select_related("customer").order_by("code")),
            content_type="application/pdf",
        )
        response["Content-Disposition"] = 'inline; filename="mould-labels.pdf"'
        return response
