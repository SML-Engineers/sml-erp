from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import logout
from django.utils import timezone

from .auth_services import SESSION_AUTH_TIME


class AbsoluteSessionTimeoutMiddleware:
    """Sign the user out a fixed time after they signed in, however active they are.

    The idle timeout is handled by Django itself (SESSION_COOKIE_AGE with
    SESSION_SAVE_EVERY_REQUEST), so an unattended screen also signs out.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            started = request.session.get(SESSION_AUTH_TIME)
            limit = timedelta(hours=settings.SESSION_ABSOLUTE_HOURS)
            if not started or timezone.now() - datetime.fromisoformat(started) > limit:
                logout(request)
        return self.get_response(request)
