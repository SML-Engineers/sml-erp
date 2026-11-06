"""Taking over from the old payroll (P2B-14): templates, uploads, approval and sign-off."""

from django.http import HttpResponse
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from . import changes, employees, takeover
from .models import PayrollRun
from .takeover import TakeoverError
from .views import XLSX, _Employees


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _xlsx(content: bytes, name: str) -> HttpResponse:
    response = HttpResponse(content, content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


def _upload(request):
    uploaded = request.FILES.get("file")
    if uploaded is None:
        raise TakeoverError("Choose an Excel file to upload.")
    if uploaded.size > takeover.MAX_BYTES:
        raise TakeoverError("The file is larger than 5 MB.")
    return uploaded.read(), uploaded.name


def _flag(request, name: str, default: bool) -> bool:
    value = str(request.data.get(name, "true" if default else "false")).lower()
    return value not in ("false", "0", "no")


class TakeoverView(_Employees):
    def get(self, request):
        user = request.user
        runs = PayrollRun.objects.filter(
            division__in=employees.visible(user).values("division")
        ).exclude(status=PayrollRun.Status.REJECTED)
        return Response(
            {
                "can_edit": employees.can_edit(user),
                "is_director": changes.is_director(user),
                "batches": takeover.batches(user),
                "checks": takeover.checks(user),
                "runs": [
                    {
                        "id": r.pk,
                        "title": f"{r.division.code} {r.month:%B %Y}",
                        "status_label": r.get_status_display(),
                    }
                    for r in runs.select_related("division").order_by("-month", "division__code")[
                        :24
                    ]
                ],
            }
        )


class PayTemplateView(_Employees):
    def get(self, request):
        try:
            return _xlsx(takeover.pay_template(request.user), "pay-takeover-template.xlsx")
        except TakeoverError as error:
            return _error(error)


class PayImportView(_Employees):
    parser_classes = [MultiPartParser]

    def post(self, request):
        try:
            content, _ = _upload(request)
            result = takeover.import_pay(
                request.user, content, dry_run=_flag(request, "dry_run", True)
            )
        except TakeoverError as error:
            return _error(error)
        return Response(result)


class OpeningTemplateView(_Employees):
    def get(self, request):
        try:
            return _xlsx(takeover.opening_template(request.user), "year-to-date-template.xlsx")
        except TakeoverError as error:
            return _error(error)


class OpeningImportView(_Employees):
    parser_classes = [MultiPartParser]

    def post(self, request):
        try:
            content, name = _upload(request)
            result = takeover.import_opening(
                request.user, content, name, dry_run=_flag(request, "dry_run", True)
            )
        except TakeoverError as error:
            return _error(error)
        return Response(result)


class OpeningDecideView(_Employees):
    access_write_level = "view"  # the Director (approve level); the service checks

    def post(self, request, pk, action):
        if action not in ("approve", "reject"):
            return _error("Unknown action.")
        try:
            takeover.decide_opening(
                request.user, pk, action == "approve", request.data.get("reason", "")
            )
        except TakeoverError as error:
            return _error(error)
        return TakeoverView().get(request)


class CompareTemplateView(_Employees):
    def get(self, request, run):
        try:
            return _xlsx(takeover.compare_template(request.user, run), "old-payroll-month.xlsx")
        except TakeoverError as error:
            return _error(error)


class CompareView(_Employees):
    parser_classes = [MultiPartParser]

    def post(self, request, run):
        try:
            content, name = _upload(request)
            result = takeover.compare(
                request.user, run, content, name, save=_flag(request, "save", False)
            )
        except TakeoverError as error:
            return _error(error)
        return Response(result)


class SignOffView(_Employees):
    access_write_level = "view"  # the Director (approve level); the service checks

    def post(self, request, pk):
        try:
            takeover.sign_off(request.user, pk, request.data.get("note", ""))
        except TakeoverError as error:
            return _error(error)
        return TakeoverView().get(request)
