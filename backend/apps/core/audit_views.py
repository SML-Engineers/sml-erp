"""Reading the audit log (P0-05). There is no way to change it through the API."""

from datetime import datetime, time

from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AuditEvent
from .permissions import AreaAccess

MAX_ROWS = 500


class AuditEventSerializer(serializers.ModelSerializer):
    related_user_email = serializers.SlugRelatedField(
        source="related_user", read_only=True, slug_field="email"
    )

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "occurred_at",
            "actor_email",
            "ip_address",
            "action",
            "object_type",
            "object_id",
            "object_repr",
            "related_user",
            "related_user_email",
            "event",
            "reason",
            "changes",
        ]


def _day(value: str, end: bool):
    day = datetime.strptime(value, "%Y-%m-%d").date()
    return timezone.make_aware(datetime.combine(day, time.max if end else time.min))


class AuditLogView(APIView):
    """Newest first. Filters: user, object_type, object_id, event, actor (email), from, to
    (YYYY-MM-DD), limit (up to 500)."""

    permission_classes = [AreaAccess]
    access_area = "audit_logs"

    def get(self, request):
        q = request.query_params
        rows = AuditEvent.objects.select_related("related_user")
        if q.get("user"):
            rows = rows.filter(related_user_id=q["user"])
        if q.get("object_type"):
            rows = rows.filter(object_type=q["object_type"])
        if q.get("object_id"):
            rows = rows.filter(object_id=q["object_id"])
        if q.get("event"):
            rows = rows.filter(event=q["event"])
        if q.get("actor"):
            rows = rows.filter(actor_email__iexact=q["actor"])
        try:
            if q.get("from"):
                rows = rows.filter(occurred_at__gte=_day(q["from"], end=False))
            if q.get("to"):
                rows = rows.filter(occurred_at__lte=_day(q["to"], end=True))
            limit = min(int(q.get("limit", 100)), MAX_ROWS)
        except ValueError:
            return Response({"detail": "Dates are YYYY-MM-DD; limit is a number."}, status=400)
        return Response(AuditEventSerializer(rows[:limit], many=True).data)
