"""Self-service API (P2B-11): /api/v1/my/... Any signed-in user; each view shows only the
signed-in user's own employee record (or, for supervisors, their sections' applications)."""

from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import detailchanges, punches, selfservice
from .detailchanges import DetailChangeError
from .punches import PunchError
from .selfservice import SelfServiceError


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class _Mine(APIView):
    permission_classes = [IsAuthenticated]


class MySummaryView(_Mine):
    def get(self, request):
        try:
            return Response(selfservice.summary(request.user) | {"linked": True})
        except SelfServiceError as error:
            # A supervisor without an employee record still decides applications.
            return Response(
                {
                    "detail": str(error),
                    "linked": False,
                    "to_approve": [
                        selfservice.application(x) for x in selfservice.to_approve(request.user)
                    ],
                }
            )


class MyPayslipView(_Mine):
    def get(self, request, pk):
        try:
            name, content = selfservice.payslip(request.user, pk)
        except SelfServiceError as error:
            return _error(error)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{name}"'
        return response


class MyCertificateView(_Mine):
    def get(self, request):
        year = request.query_params.get("year")
        try:
            content = selfservice.certificate(request.user, year)
        except SelfServiceError as error:
            return _error(error)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="apit-certificate-{year}.pdf"'
        return response


class MyLeaveView(_Mine):
    def post(self, request):
        try:
            selfservice.apply(request.user, request.data)
        except SelfServiceError as error:
            return _error(error)
        return Response(selfservice.summary(request.user), status=status.HTTP_201_CREATED)


class MyLeaveWithdrawView(_Mine):
    def post(self, request, pk):
        try:
            selfservice.withdraw(request.user, pk)
        except SelfServiceError as error:
            return _error(error)
        return Response(selfservice.summary(request.user))


class TeamLeaveDecideView(_Mine):
    """A section supervisor approves or rejects an application (never their own)."""

    def post(self, request, pk, action):
        if action not in ("approve", "reject"):
            return _error("Unknown action.")
        try:
            selfservice.decide(
                request.user, pk, action == "approve", request.data.get("reason", "")
            )
        except SelfServiceError as error:
            return _error(error)
        return MySummaryView().get(request)


# --- Phone punch clock (P2B-12) ------------------------------------------------------------------


class MyPunchView(_Mine):
    """Clock in or out: {kind: in|out, latitude, longitude, accuracy}. The time is the server's."""

    def post(self, request):
        data = request.data
        try:
            punches.punch(
                request.user,
                str(data.get("kind") or ""),
                data.get("latitude"),
                data.get("longitude"),
                data.get("accuracy"),
            )
        except PunchError as error:
            return _error(error)
        return Response(selfservice.summary(request.user) | {"linked": True}, status=201)


class MyLocationConsentView(_Mine):
    """Give ({consent: true}) or withdraw ({consent: false}) consent to the location check."""

    def post(self, request):
        try:
            punches.consent(request.user, request.data.get("consent") is True)
        except PunchError as error:
            return _error(error)
        return Response(selfservice.summary(request.user) | {"linked": True})


# --- Asking to change details (P2B-20) -----------------------------------------------------------


class MyDetailsView(_Mine):
    """Ask HR to change phone, address, email or salary account: the new values and a note."""

    def post(self, request):
        try:
            detailchanges.ask(request.user, request.data, request.data.get("note", ""))
        except DetailChangeError as error:
            return _error(error)
        return Response(selfservice.summary(request.user) | {"linked": True}, status=201)


class MyDetailsWithdrawView(_Mine):
    def post(self, request, pk):
        try:
            detailchanges.withdraw(request.user, pk)
        except DetailChangeError as error:
            return _error(error)
        return Response(selfservice.summary(request.user) | {"linked": True})
