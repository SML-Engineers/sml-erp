"""Document email settings and the record of emails sent (P0-19). Rules live in
document_email.py; each document module adds its own Email button and send endpoint."""

from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import document_email
from .document_email import EmailError
from .models import SentEmail
from .permissions import AreaAccess


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class _Settings(APIView):
    permission_classes = [AreaAccess]
    access_area = "settings"
    access_write_level = "manage"


class AccountInput(serializers.Serializer):
    from_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    from_address = serializers.CharField(max_length=254, required=False, allow_blank=True)
    reply_to = serializers.CharField(max_length=254, required=False, allow_blank=True)
    copy_to = serializers.CharField(max_length=254, required=False, allow_blank=True)
    host = serializers.CharField(max_length=200, required=False, allow_blank=True)
    port = serializers.IntegerField(required=False)
    security = serializers.CharField(max_length=10, required=False)
    username = serializers.CharField(max_length=200, required=False, allow_blank=True)
    password = serializers.CharField(
        max_length=500, required=False, allow_blank=True, trim_whitespace=False
    )
    clear_password = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class AccountView(_Settings):
    def get(self, request):
        return Response(document_email.account_view())

    def put(self, request):
        data = AccountInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            return Response(document_email.update_account(request.user, values, reason))
        except EmailError as error:
            return _error(error)


class TestView(_Settings):
    def post(self, request):
        try:
            result = document_email.send_test(request.user, str(request.data.get("to", "")))
        except EmailError as error:
            return _error(error)
        return Response(result)


class TemplateListView(_Settings):
    def get(self, request):
        return Response(document_email.templates())


class TemplateInput(serializers.Serializer):
    subject = serializers.CharField(max_length=500, allow_blank=True)
    body = serializers.CharField(allow_blank=True, trim_whitespace=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class TemplateView(_Settings):
    def put(self, request, kind):
        data = TemplateInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            document_email.update_template(
                request.user, kind, subject=v["subject"], body=v["body"], reason=v["reason"]
            )
        except EmailError as error:
            return _error(error)
        return Response(next(t for t in document_email.templates() if t["kind"] == kind))


class TemplatePreviewView(_Settings):
    access_write_level = "view"  # shows sample text; changes nothing

    def post(self, request, kind):
        data = TemplateInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            return Response(
                document_email.preview(
                    kind, data.validated_data["subject"], data.validated_data["body"]
                )
            )
        except EmailError as error:
            return _error(error)


def sent_row(e: SentEmail) -> dict:
    return {
        "id": e.pk,
        "document_type": e.document_type,
        "document_id": e.document_id,
        "document_label": e.document_label,
        "from": e.from_address,
        "to": e.to,
        "cc": e.cc,
        "subject": e.subject,
        "body": e.body,
        "attachment_name": e.attachment_name,
        "attachment_sha256": e.attachment_sha256,
        "status": e.status,
        "error": e.error,
        "sent_by": e.sent_by.full_name,
        "sent_at": e.sent_at,
    }


class SentEmailListView(APIView):
    """Every document email sent or attempted, newest first (Admin, Director, Auditor)."""

    permission_classes = [AreaAccess]
    access_area = "audit_logs"

    def get(self, request):
        rows = SentEmail.objects.select_related("sent_by")
        params = request.query_params
        if params.get("document_type"):
            rows = rows.filter(document_type=params["document_type"])
        if params.get("document_id", "").isdigit():
            rows = rows.filter(document_id=int(params["document_id"]))
        return Response([sent_row(e) for e in rows[:500]])
