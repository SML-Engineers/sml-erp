"""Sign-in, two-factor and password rules (backlog P0-03).

All business rules for authentication live here; the API views only call these functions.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pyotp
import segno
from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import crypto
from .audit import audited
from .models import LoginEvent, LoginLock, RecoveryCode, User, normalize_email

SESSION_AUTH_TIME = "auth_time"
SESSION_PENDING_USER = "pending_2fa_user"
SESSION_PENDING_AT = "pending_2fa_at"

RECOVERY_CODE_COUNT = 10
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I confusion

# Requirements a signed-in user must complete before using anything else.
PASSWORD_CHANGE_REQUIRED = "password_change_required"  # noqa: S105 (a status name)
TWO_FACTOR_SETUP_REQUIRED = "two_factor_setup_required"


@dataclass
class SignInResult:
    status: str  # "ok", "two_factor_required", "invalid", "locked"
    user: User | None = None
    requirements: list[str] = field(default_factory=list)


# --- Helpers ----------------------------------------------------------------------------


def client_ip(request) -> str | None:
    if settings.USE_X_FORWARDED_FOR:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            # Nginx appends the address it saw as the last entry; earlier ones can be forged.
            return forwarded.split(",")[-1].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def record_event(request, email: str, outcome: str, user: User | None = None) -> LoginEvent:
    return LoginEvent.objects.create(
        user=user,
        email=normalize_email(email),
        outcome=outcome,
        ip_address=client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
    )


def setup_requirements(user: User) -> list[str]:
    """What a signed-in user must do before they can use the rest of the system."""
    pending = []
    if user.must_change_password:
        pending.append(PASSWORD_CHANGE_REQUIRED)
    if user.two_factor_required and not user.two_factor_enabled:
        pending.append(TWO_FACTOR_SETUP_REQUIRED)
    return pending


# --- Lockout ----------------------------------------------------------------------------


def is_locked(email: str) -> bool:
    return LoginLock.objects.filter(
        email=normalize_email(email), locked_until__gt=timezone.now()
    ).exists()


def _register_failure(request, email: str, outcome: str, user: User | None) -> None:
    """Record a failed attempt and lock the email after too many in the window.

    Works the same for emails that do not belong to any account, so the response never
    reveals whether an account exists.
    """
    email = normalize_email(email)
    now = timezone.now()
    record_event(request, email, outcome, user)

    window_start = now - timedelta(minutes=settings.LOGIN_LOCK_WINDOW_MINUTES)
    last_success = (
        LoginEvent.objects.filter(email=email, outcome=LoginEvent.Outcome.SUCCESS)
        .values_list("created_at", flat=True)
        .first()
    )
    if last_success and last_success > window_start:
        window_start = last_success

    failures = LoginEvent.objects.filter(
        email=email,
        outcome__in=[LoginEvent.Outcome.BAD_CREDENTIALS, LoginEvent.Outcome.BAD_CODE],
        created_at__gt=window_start,
    ).count()
    if failures >= settings.LOGIN_LOCK_THRESHOLD:
        LoginLock.objects.update_or_create(
            email=email,
            defaults={"locked_until": now + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)},
        )


def unlock(email: str) -> None:
    """Remove a lock early (used by the Admin's User access page, P0-04b)."""
    LoginLock.objects.filter(email=normalize_email(email)).delete()


# --- Sign in ----------------------------------------------------------------------------


@transaction.atomic
def sign_in(request, email: str, password: str) -> SignInResult:
    email = normalize_email(email)
    if is_locked(email):
        record_event(request, email, LoginEvent.Outcome.LOCKED)
        return SignInResult("locked")

    user = authenticate(request, username=email, password=password)
    if user is None:  # wrong password, unknown email or deactivated account: same answer
        known = User.objects.filter(email__iexact=email).first()
        _register_failure(request, email, LoginEvent.Outcome.BAD_CREDENTIALS, known)
        return SignInResult("invalid")

    if user.two_factor_enabled:
        request.session.cycle_key()
        request.session[SESSION_PENDING_USER] = user.pk
        request.session[SESSION_PENDING_AT] = timezone.now().isoformat()
        return SignInResult("two_factor_required", user)

    _complete_sign_in(request, user)
    return SignInResult("ok", user, setup_requirements(user))


def _complete_sign_in(request, user: User, outcome: str = LoginEvent.Outcome.SUCCESS) -> None:
    request.session.pop(SESSION_PENDING_USER, None)
    request.session.pop(SESSION_PENDING_AT, None)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session[SESSION_AUTH_TIME] = timezone.now().isoformat()
    record_event(request, user.email, outcome, user)
    unlock(user.email)


def pending_two_factor_user(request) -> User | None:
    """The user who entered a correct password and still owes a two-factor code."""
    user_id = request.session.get(SESSION_PENDING_USER)
    started = request.session.get(SESSION_PENDING_AT)
    if not user_id or not started:
        return None
    age = timezone.now() - datetime.fromisoformat(started)
    if age > timedelta(seconds=settings.TWO_FACTOR_PENDING_SECONDS):
        request.session.pop(SESSION_PENDING_USER, None)
        request.session.pop(SESSION_PENDING_AT, None)
        return None
    return User.objects.filter(pk=user_id, is_active=True).first()


@transaction.atomic
def verify_second_factor(request, code: str) -> SignInResult:
    user = pending_two_factor_user(request)
    if user is None:
        return SignInResult("invalid")
    if is_locked(user.email):
        record_event(request, user.email, LoginEvent.Outcome.LOCKED, user)
        return SignInResult("locked")

    user = User.objects.select_for_update().get(pk=user.pk)
    if _verify_totp(user, code):
        _complete_sign_in(request, user)
        return SignInResult("ok", user, setup_requirements(user))
    if _use_recovery_code(user, code):
        _complete_sign_in(request, user, LoginEvent.Outcome.RECOVERY_CODE_USED)
        return SignInResult("ok", user, setup_requirements(user))

    _register_failure(request, user.email, LoginEvent.Outcome.BAD_CODE, user)
    if is_locked(user.email):
        return SignInResult("locked")
    return SignInResult("invalid")


def sign_out(request) -> None:
    user = request.user
    if user.is_authenticated:
        record_event(request, user.email, LoginEvent.Outcome.LOGOUT, user)
    logout(request)


# --- Two-factor (authenticator app, RFC 6238) ------------------------------------------


def _totp(user: User) -> pyotp.TOTP:
    return pyotp.TOTP(crypto.decrypt(user.totp_secret_encrypted))


def _verify_totp(user: User, code: str) -> bool:
    """Accept the current code or its neighbours (clock drift), each only once."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if not user.totp_secret_encrypted or len(code) != 6:
        return False
    totp = _totp(user)
    current = totp.timecode(timezone.now())
    for step in (current - 1, current, current + 1):
        if hmac.compare_digest(totp.generate_otp(step), code):
            if user.totp_last_timestep is not None and step <= user.totp_last_timestep:
                return False  # this code (or an earlier one) was already used
            user.totp_last_timestep = step
            user.save(update_fields=["totp_last_timestep"])
            return True
    return False


class TwoFactorError(Exception):
    pass


@audited("two_factor_setup_started")
def start_two_factor_setup(user: User) -> dict:
    """Create a new authenticator secret for the user to scan. Not active until confirmed."""
    if user.two_factor_enabled:
        raise TwoFactorError(
            "Two-factor sign-in is already set up. Ask the administrator to reset it."
        )
    secret = pyotp.random_base32()
    user.totp_secret_encrypted = crypto.encrypt(secret)
    user.totp_last_timestep = None
    user.save(update_fields=["totp_secret_encrypted", "totp_last_timestep"])
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=settings.TOTP_ISSUER)
    return {
        "secret": secret,
        "otpauth_uri": uri,
        "qr_svg_data_uri": segno.make(uri, error="m").svg_data_uri(scale=5),
    }


@audited("two_factor_enabled")
@transaction.atomic
def confirm_two_factor(request, user: User, code: str) -> list[str]:
    """Turn two-factor on after the user proves their app works; returns recovery codes."""
    user = User.objects.select_for_update().get(pk=user.pk)
    if user.two_factor_enabled:
        raise TwoFactorError("Two-factor sign-in is already set up.")
    if not user.totp_secret_encrypted:
        raise TwoFactorError("Start the setup first.")
    if not _verify_totp(user, code):
        raise TwoFactorError("That code is not correct. Check the time on your phone and retry.")
    user.totp_confirmed_at = timezone.now()
    user.save(update_fields=["totp_confirmed_at"])
    codes = _new_recovery_codes(user)
    record_event(request, user.email, LoginEvent.Outcome.TWO_FACTOR_ENABLED, user)
    return codes


@audited("two_factor_reset")
def reset_two_factor(user: User) -> None:
    """Remove a user's authenticator so they set it up again (Admin, P0-04b)."""
    user.totp_secret_encrypted = ""
    user.totp_confirmed_at = None
    user.totp_last_timestep = None
    user.save(update_fields=["totp_secret_encrypted", "totp_confirmed_at", "totp_last_timestep"])
    user.recovery_codes.all().delete()


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _normalise_recovery_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def _new_recovery_codes(user: User) -> list[str]:
    user.recovery_codes.all().delete()
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(10))
        RecoveryCode.objects.create(user=user, code_hash=_hash_code(raw))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def _use_recovery_code(user: User, code: str) -> bool:
    raw = _normalise_recovery_code(code)
    if len(raw) != 10:
        return False
    match = user.recovery_codes.filter(code_hash=_hash_code(raw), used_at__isnull=True).first()
    if match is None:
        return False
    match.used_at = timezone.now()
    match.save(update_fields=["used_at"])
    return True


# --- Passwords --------------------------------------------------------------------------


class PasswordChangeError(Exception):
    def __init__(self, messages):
        super().__init__("; ".join(messages))
        self.messages = messages


@audited("password_changed")
@transaction.atomic
def change_password(request, user: User, current: str, new: str) -> None:
    if not user.check_password(current):
        raise PasswordChangeError(["Your current password is not correct."])
    if current == new:
        raise PasswordChangeError(["The new password must be different from the current one."])
    try:
        validate_password(new, user)
    except ValidationError as error:
        raise PasswordChangeError(list(error.messages)) from error
    user.set_password(new)
    user.must_change_password = False
    user.password_changed_at = timezone.now()
    user.save(update_fields=["password", "must_change_password", "password_changed_at"])
    update_session_auth_hash(request, user)  # stay signed in on this device only
    record_event(request, user.email, LoginEvent.Outcome.PASSWORD_CHANGED, user)
