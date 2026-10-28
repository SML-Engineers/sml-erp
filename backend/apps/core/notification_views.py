"""The bell and each person's notification choices (P0-18). Everyone signed in has them,
and each person only ever sees their own."""

from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import notifications
from .notifications import NotificationError

PAGE = 50


def _row(n) -> dict:
    return {
        "id": n.pk,
        "event": n.event,
        "title": n.title,
        "body": n.body,
        "link": n.link,
        "created_at": n.created_at,
        "read": n.read_at is not None,
    }


class NotificationListView(APIView):
    """The latest notifications under the bell, with the unread count."""

    def get(self, request):
        rows = notifications.for_bell(request.user)
        if request.query_params.get("unread") in ("1", "true"):
            rows = rows.filter(read_at__isnull=True)
        return Response(
            {
                "unread": notifications.unread_count(request.user),
                "items": [_row(n) for n in rows[:PAGE]],
            }
        )


class ReadInput(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class NotificationReadView(APIView):
    """Mark some (or, without ids, all) of my notifications as read."""

    def post(self, request):
        data = ReadInput(data=request.data)
        data.is_valid(raise_exception=True)
        notifications.mark_read(request.user, data.validated_data.get("ids"))
        return Response({"unread": notifications.unread_count(request.user)})


class PreferenceInput(serializers.Serializer):
    event = serializers.CharField(max_length=40)
    in_app = serializers.BooleanField(required=False)
    email = serializers.BooleanField(required=False)


class PreferenceView(APIView):
    def get(self, request):
        return Response(notifications.preferences(request.user))

    def put(self, request):
        data = PreferenceInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            rows = notifications.set_preference(
                request.user, v["event"], in_app=v.get("in_app"), email=v.get("email")
            )
        except NotificationError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(rows)
