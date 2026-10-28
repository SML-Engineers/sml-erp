from django.conf import settings
from django.db import DatabaseError, connection, transaction
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


# Outside the per-request transaction, so a database outage gives a clean 503 instead of a 500.
@transaction.non_atomic_requests
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])  # Public on purpose: used by monitoring, returns no business data.
def health(request):
    """Report whether the API is running and can reach the database."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        database = "ok"
    except DatabaseError:
        database = "unavailable"

    healthy = database == "ok"
    return Response(
        {
            "status": "ok" if healthy else "degraded",
            "database": database,
            "version": settings.APP_VERSION,
        },
        status=200 if healthy else 503,
    )
