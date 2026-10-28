import pyotp
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.core import crypto
from apps.core.models import User

PASSWORD = "Correct-Horse-42"


@pytest.fixture(autouse=True)
def _clear_cache():
    # Sign-in throttling counts live in the cache; start every test fresh.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def make_user(db):
    def _make(email="clerk@sml.lk", password=PASSWORD, **extra):
        return User.objects.create_user(email, "Test User", password, **extra)

    return _make


@pytest.fixture
def user(make_user):
    return make_user()


def login(client, email="clerk@sml.lk", password=PASSWORD):
    return client.post("/api/v1/auth/login/", {"email": email, "password": password}, format="json")


def secret_of(user) -> str:
    user.refresh_from_db()
    return crypto.decrypt(user.totp_secret_encrypted)


def enable_two_factor(client, user, password=PASSWORD):
    """Sign in, set up an authenticator and confirm it. Returns (totp, recovery_codes)."""
    assert login(client, user.email, password).json()["status"] == "ok"
    client.post("/api/v1/auth/two-factor/setup/")
    totp = pyotp.TOTP(secret_of(user))
    response = client.post("/api/v1/auth/two-factor/confirm/", {"code": totp.now()}, format="json")
    assert response.status_code == 200, response.json()
    client.post("/api/v1/auth/logout/")
    return totp, response.json()["recovery_codes"]
