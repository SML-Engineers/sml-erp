"""Guards on project-wide settings that protect the business rules in CLAUDE.md."""

from django.conf import settings

from apps.core.tasks import ping


def test_api_requires_login_by_default():
    # Rule 8: every endpoint is protected unless it explicitly opts out.
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == [
        "rest_framework.permissions.IsAuthenticated"
    ]


def test_decimals_are_sent_as_strings():
    # Rule 1: money never passes through floating point, including in JSON.
    assert settings.REST_FRAMEWORK["COERCE_DECIMAL_TO_STRING"] is True


def test_database_is_postgresql():
    assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"


def test_uploaded_files_use_private_signed_urls():
    assert settings.AWS_QUERYSTRING_AUTH is True
    assert settings.AWS_DEFAULT_ACL is None
    assert settings.AWS_QUERYSTRING_EXPIRE <= 900


def test_time_zone_is_sri_lanka():
    assert settings.TIME_ZONE == "Asia/Colombo"
    assert settings.USE_TZ is True


def test_background_task_runs():
    assert ping.apply().get() == "pong"
