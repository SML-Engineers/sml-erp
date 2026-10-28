"""Sign-in rules (backlog P0-03)."""

import importlib
import time
from datetime import timedelta

import pyotp
import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.auth_services import SESSION_AUTH_TIME, SESSION_PENDING_AT
from apps.core.models import LoginEvent, LoginLock, User

from .conftest import PASSWORD, enable_two_factor, login, secret_of

pytestmark = pytest.mark.django_db

ME = "/api/v1/auth/me/"
PROTECTED = "/api/v1/auth/login-history/"  # an endpoint that needs a fully signed-in user


# --- Passwords and accounts --------------------------------------------------------------


def test_passwords_are_stored_with_argon2(user):
    assert user.password.startswith("argon2")


def test_email_is_case_insensitive(client, user):
    response = login(client, email="  Clerk@SML.lk ")
    assert response.json()["status"] == "ok"


def test_sign_in_with_correct_password(client, user):
    response = login(client)

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "clerk@sml.lk"
    assert client.get(ME).json()["authenticated"] is True
    assert client.get(PROTECTED).status_code == 200
    assert LoginEvent.objects.filter(user=user, outcome="success").count() == 1


def test_wrong_password_and_unknown_email_get_the_same_answer(client, user):
    wrong = login(client, password="not-it-at-all")
    unknown = login(client, email="nobody@sml.lk")

    assert wrong.status_code == unknown.status_code == 400
    assert wrong.json() == unknown.json()
    assert client.get(ME).json()["authenticated"] is False


def test_deactivated_user_cannot_sign_in(client, make_user):
    make_user(email="leaver@sml.lk", is_active=False)
    response = login(client, email="leaver@sml.lk")
    assert response.status_code == 400


def test_failed_attempts_are_recorded(client, user):
    login(client, password="wrong-1")
    event = LoginEvent.objects.get()
    assert event.outcome == "bad_credentials"
    assert event.user == user
    assert event.email == "clerk@sml.lk"


def test_sign_out(client, user):
    login(client)
    assert client.post("/api/v1/auth/logout/").status_code == 200
    assert client.get(ME).json()["authenticated"] is False
    assert LoginEvent.objects.filter(outcome="logout").exists()


def test_anonymous_users_cannot_reach_protected_endpoints(client):
    assert client.get(PROTECTED).status_code == 403


# --- Lockout: 5 failures in 15 minutes locks sign-in for 15 minutes ----------------------


def test_five_failures_lock_the_account_even_for_the_right_password(client, user):
    for _ in range(4):
        assert login(client, password="wrong").status_code == 400
    assert not LoginLock.objects.exists()

    assert login(client, password="wrong").status_code == 400  # 5th failure locks
    lock = LoginLock.objects.get(email="clerk@sml.lk")
    assert timedelta(minutes=14) < lock.locked_until - timezone.now() <= timedelta(minutes=15)

    response = login(client)  # correct password, but locked
    assert response.status_code == 429
    assert response.json()["status"] == "locked"
    assert LoginEvent.objects.filter(outcome="locked").count() == 1


def test_lock_ends_after_its_time(client, user):
    for _ in range(5):
        login(client, password="wrong")
    LoginLock.objects.update(locked_until=timezone.now() - timedelta(seconds=1))

    assert login(client).json()["status"] == "ok"
    assert not LoginLock.objects.exists()  # cleared by the successful sign-in


def test_unknown_emails_lock_the_same_way(client):
    for _ in range(5):
        login(client, email="guess@sml.lk", password="wrong")
    assert login(client, email="guess@sml.lk", password="wrong").status_code == 429


def test_a_success_resets_the_failure_count(client, user):
    for _ in range(4):
        login(client, password="wrong")
    login(client)
    client.post("/api/v1/auth/logout/")
    for _ in range(4):
        login(client, password="wrong")
    assert not LoginLock.objects.exists()


# --- Two-factor sign-in ------------------------------------------------------------------


def test_users_who_must_use_two_factor_are_held_until_they_set_it_up(client, make_user):
    director = make_user(email="director@sml.lk", two_factor_required=True)
    response = login(client, email=director.email)

    assert response.json()["user"]["requirements"] == ["two_factor_setup_required"]
    assert client.get(PROTECTED).status_code == 403

    client.post("/api/v1/auth/two-factor/setup/")
    code = pyotp.TOTP(secret_of(director)).now()
    confirm = client.post("/api/v1/auth/two-factor/confirm/", {"code": code}, format="json")

    assert confirm.status_code == 200
    assert len(confirm.json()["recovery_codes"]) == 10
    assert client.get(PROTECTED).status_code == 200


def test_setup_returns_a_scannable_code(client, user):
    login(client)
    data = client.post("/api/v1/auth/two-factor/setup/").json()
    assert data["otpauth_uri"].startswith("otpauth://totp/")
    assert data["qr_svg_data_uri"].startswith("data:image/svg+xml")


def test_wrong_code_does_not_turn_two_factor_on(client, user):
    login(client)
    client.post("/api/v1/auth/two-factor/setup/")
    response = client.post("/api/v1/auth/two-factor/confirm/", {"code": "000000"}, format="json")
    assert response.status_code == 400
    user.refresh_from_db()
    assert user.totp_confirmed_at is None


def test_authenticator_secret_is_encrypted_in_the_database(client, user):
    login(client)
    secret = client.post("/api/v1/auth/two-factor/setup/").json()["secret"]
    with connection.cursor() as cursor:
        cursor.execute("SELECT totp_secret_encrypted FROM core_user WHERE id = %s", [user.pk])
        stored = cursor.fetchone()[0]
    assert stored and secret not in stored


def test_password_alone_is_not_enough_once_two_factor_is_on(client, user):
    totp, _ = enable_two_factor(client, user)

    response = login(client)
    assert response.json() == {"status": "two_factor_required"}
    assert client.get(ME).json() == {"authenticated": False, "two_factor_pending": True}
    assert client.get(PROTECTED).status_code == 403

    next_code = totp.at(time.time() + 30)
    verified = client.post("/api/v1/auth/login/verify/", {"code": next_code}, format="json")
    assert verified.json()["status"] == "ok"
    assert client.get(PROTECTED).status_code == 200


def test_a_code_cannot_be_used_twice(client, user):
    totp, _ = enable_two_factor(client, user)
    code = totp.at(time.time() + 30)

    login(client)
    assert (
        client.post("/api/v1/auth/login/verify/", {"code": code}, format="json").status_code == 200
    )
    client.post("/api/v1/auth/logout/")

    login(client)
    replay = client.post("/api/v1/auth/login/verify/", {"code": code}, format="json")
    assert replay.status_code == 400


def test_wrong_codes_count_towards_the_lock(client, user):
    enable_two_factor(client, user)
    login(client)
    for _ in range(5):
        client.post("/api/v1/auth/login/verify/", {"code": "000000"}, format="json")
    assert LoginLock.objects.filter(email=user.email).exists()


def test_code_must_be_entered_within_five_minutes(client, user):
    totp, _ = enable_two_factor(client, user)
    login(client)
    session = client.session
    session[SESSION_PENDING_AT] = (timezone.now() - timedelta(minutes=6)).isoformat()
    session.save()

    response = client.post(
        "/api/v1/auth/login/verify/", {"code": totp.at(time.time() + 30)}, format="json"
    )
    assert response.status_code == 400


def test_recovery_code_works_once(client, user):
    _, codes = enable_two_factor(client, user)

    login(client)
    first = client.post("/api/v1/auth/login/verify/", {"code": codes[0]}, format="json")
    assert first.json()["status"] == "ok"
    assert LoginEvent.objects.filter(outcome="recovery_code_used").count() == 1
    client.post("/api/v1/auth/logout/")

    login(client)
    again = client.post("/api/v1/auth/login/verify/", {"code": codes[0]}, format="json")
    assert again.status_code == 400


def test_two_factor_cannot_be_replaced_without_the_administrator(client, user):
    enable_two_factor(client, user)
    totp_user = User.objects.get(pk=user.pk)
    client.force_authenticate(totp_user)  # even when signed in
    assert client.post("/api/v1/auth/two-factor/setup/").status_code == 400


# --- Password change and first sign-in --------------------------------------------------


def test_change_password(client, user):
    login(client)
    response = client.post(
        "/api/v1/auth/password/change/",
        {"current_password": PASSWORD, "new_password": "Another-Strong-77"},
        format="json",
    )
    assert response.status_code == 200
    assert client.get(PROTECTED).status_code == 200  # still signed in on this device
    client.post("/api/v1/auth/logout/")
    assert login(client).status_code == 400
    assert login(client, password="Another-Strong-77").json()["status"] == "ok"


def test_change_password_needs_the_current_password(client, user):
    login(client)
    response = client.post(
        "/api/v1/auth/password/change/",
        {"current_password": "guess", "new_password": "Another-Strong-77"},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.parametrize("weak", ["short1", "password123", "1234567890"])
def test_weak_passwords_are_refused(client, user, weak):
    login(client)
    response = client.post(
        "/api/v1/auth/password/change/",
        {"current_password": PASSWORD, "new_password": weak},
        format="json",
    )
    assert response.status_code == 400


def test_temporary_password_must_be_changed_first(client, make_user):
    make_user(email="new@sml.lk", must_change_password=True)
    response = login(client, email="new@sml.lk")

    assert response.json()["user"]["requirements"] == ["password_change_required"]
    assert client.get(PROTECTED).status_code == 403

    client.post(
        "/api/v1/auth/password/change/",
        {"current_password": PASSWORD, "new_password": "My-Own-Secret-55"},
        format="json",
    )
    assert client.get(PROTECTED).status_code == 200


# --- Sessions ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_idle_timeout_is_set():
    from django.conf import settings

    assert settings.SESSION_SAVE_EVERY_REQUEST is True
    assert settings.SESSION_COOKIE_AGE <= 60 * 60


def test_absolute_timeout_signs_the_user_out(client, user):
    login(client)
    session = client.session
    session[SESSION_AUTH_TIME] = (timezone.now() - timedelta(hours=13)).isoformat()
    session.save()

    assert client.get(PROTECTED).status_code == 403
    assert client.get(ME).json()["authenticated"] is False


def test_sign_in_form_requires_the_csrf_token(user):
    browser = APIClient(enforce_csrf_checks=True)
    without = browser.post(
        "/api/v1/auth/login/", {"email": user.email, "password": PASSWORD}, format="json"
    )
    assert without.status_code == 403

    browser.get("/api/v1/auth/csrf/")
    token = browser.cookies["csrftoken"].value
    with_token = browser.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": PASSWORD},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert with_token.json()["status"] == "ok"


# --- Records and configuration ----------------------------------------------------------


def test_sign_in_history_cannot_be_changed_or_deleted(client, user):
    login(client)
    event = LoginEvent.objects.first()

    with pytest.raises(DatabaseError), transaction.atomic():
        LoginEvent.objects.filter(pk=event.pk).update(outcome="logout")
    with pytest.raises(DatabaseError), transaction.atomic():
        LoginEvent.objects.filter(pk=event.pk).delete()


def test_users_see_their_own_history(client, user, make_user):
    make_user(email="other@sml.lk")
    login(client, email="other@sml.lk")
    client.post("/api/v1/auth/logout/")
    login(client)

    rows = client.get(PROTECTED).json()
    assert rows and all(row["outcome"] in ("success", "logout") for row in rows)
    assert LoginEvent.objects.filter(email="other@sml.lk").exists()
    assert len(rows) == LoginEvent.objects.filter(user=user).count()


def test_django_admin_is_not_served_when_debug_is_off():
    import config.urls

    with override_settings(DEBUG=False):
        importlib.reload(config.urls)
        routes = [str(p.pattern) for p in config.urls.urlpatterns]
    importlib.reload(config.urls)
    assert "admin/" not in routes


def test_superusers_must_use_two_factor(db):
    admin = User.objects.create_superuser("admin@sml.lk", "Admin", PASSWORD)
    assert admin.two_factor_required is True


def test_login_route_names():
    assert reverse("auth-login") == "/api/v1/auth/login/"
