from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


def normalize_email(email: str) -> str:
    """Emails are compared case-insensitively and stored lower-case."""
    return (email or "").strip().lower()


class UserManager(BaseUserManager):
    def get_by_natural_key(self, email):
        return self.get(email__iexact=normalize_email(email))

    def create_user(self, email, full_name, password=None, **extra):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=normalize_email(email), full_name=full_name, **extra)
        user.set_password(password)
        user.password_changed_at = timezone.now()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, full_name, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("two_factor_required", True)
        return self.create_user(email, full_name, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """A person who signs in to the ERP. Signs in with their email address."""

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    # Set automatically from roles in P0-04 (Accountant, Director, Cashier, Admin), and by the
    # Admin for anyone else.
    two_factor_required = models.BooleanField(default=False)
    # The authenticator secret is encrypted at rest (apps.core.crypto).
    totp_secret_encrypted = models.TextField(blank=True, default="")
    totp_confirmed_at = models.DateTimeField(null=True, blank=True)
    # Last accepted time step, so a code can never be used twice.
    totp_last_timestep = models.BigIntegerField(null=True, blank=True)

    must_change_password = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    @property
    def two_factor_enabled(self) -> bool:
        return self.totp_confirmed_at is not None


class LoginEvent(models.Model):
    """Sign-in history. Insert-only: a database trigger refuses updates and deletes."""

    class Outcome(models.TextChoices):
        SUCCESS = "success", "Signed in"
        BAD_CREDENTIALS = "bad_credentials", "Wrong email or password"
        BAD_CODE = "bad_code", "Wrong two-factor code"
        LOCKED = "locked", "Refused: account temporarily locked"
        LOGOUT = "logout", "Signed out"
        PASSWORD_CHANGED = "password_changed", "Password changed"
        TWO_FACTOR_ENABLED = "two_factor_enabled", "Two-factor sign-in turned on"
        RECOVERY_CODE_USED = "recovery_code_used", "Signed in with a recovery code"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="login_events",
    )
    email = models.CharField(max_length=254)
    outcome = models.CharField(max_length=32, choices=Outcome.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["email", "created_at"], name="core_login_email_created")]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.email} {self.outcome}"


class LoginLock(models.Model):
    """A temporary lock after too many failed sign-ins, keyed by the email typed in."""

    email = models.CharField(max_length=254, primary_key=True)
    locked_until = models.DateTimeField()

    def __str__(self):
        return f"{self.email} locked until {self.locked_until:%Y-%m-%d %H:%M}"


class RecoveryCode(models.Model):
    """One-time codes for signing in when the authenticator phone is lost. Stored hashed."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recovery_codes"
    )
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Recovery code for {self.user_id} ({'used' if self.used_at else 'unused'})"
