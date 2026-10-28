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
        extra.setdefault("all_divisions", True)
        user = self.create_user(email, full_name, password, **extra)
        # The first administrator holds the System Administrator role; being a Django
        # superuser grants nothing extra in the ERP's own access checks.
        role = Role.objects.filter(code="system_admin").first()
        if role is not None:
            UserRole.objects.get_or_create(
                user=user, role=role, defaults={"reason": "First administrator"}
            )
        return user


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

    # Data scope (spec 1.2): the divisions this person works in, or all of them.
    all_divisions = models.BooleanField(default=False)
    divisions = models.ManyToManyField("core.Division", blank=True, related_name="users")

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


class Company(models.Model):
    """The company profile (spec 3): one row, id 1, created by migration 0007."""

    MONTHS = [
        (1, "January"),
        (2, "February"),
        (3, "March"),
        (4, "April"),
        (5, "May"),
        (6, "June"),
        (7, "July"),
        (8, "August"),
        (9, "September"),
        (10, "October"),
        (11, "November"),
        (12, "December"),
    ]

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    name = models.CharField(max_length=200)
    registration_no = models.CharField("Business registration no.", max_length=50, blank=True)
    tin = models.CharField("Taxpayer identification no. (TIN)", max_length=50, blank=True)
    vat_no = models.CharField("VAT registration no.", max_length=50, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    website = models.CharField(max_length=200, blank=True)
    # Fixed once the company is created: every amount in the books is in this currency. The
    # database refuses a change (migration 0007).
    base_currency = models.CharField(max_length=3, default="LKR")
    # Sri Lankan companies usually run April to March.
    financial_year_start_month = models.PositiveSmallIntegerField(choices=MONTHS, default=4)
    logo = models.FileField(upload_to="company/", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "company"
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="core_company_single_row"),
            models.CheckConstraint(
                condition=models.Q(financial_year_start_month__gte=1)
                & models.Q(financial_year_start_month__lte=12),
                name="core_company_fy_month_valid",
            ),
        ]

    def __str__(self):
        return self.name

    @classmethod
    def get(cls) -> "Company":
        return cls.objects.get(pk=1)


class Division(models.Model):
    """A division of the company (spec 3.1). Its code is the PP in voucher numbers."""

    class Type(models.TextChoices):
        PRODUCTION = "production", "Production"
        SHARED = "shared", "Shared"

    code = models.CharField(max_length=2, unique=True)
    name = models.CharField(max_length=100)
    division_type = models.CharField(max_length=20, choices=Type.choices, default=Type.PRODUCTION)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    # Set the first time a document uses this division (its number, its lines). From then on
    # the code is fixed and the division can only be deactivated; the database enforces both
    # (migration 0007). The default bank account is added with bank accounts (P0-14).
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code__regex=r"^[A-Z0-9]{2}$"), name="core_division_code_format"
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def in_use(self) -> bool:
        return self.first_used_at is not None


class Role(models.Model):
    """A set of access levels and special actions (spec 1.1, 1.2)."""

    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    # Standard roles come from the specification and cannot be edited; the Admin copies one
    # to make a custom role.
    is_standard = models.BooleanField(default=False)
    # Roles for later phases exist from the start but cannot be assigned until switched on.
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    area = models.CharField(max_length=40)
    level = models.CharField(max_length=10)
    note = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "area", "level"], name="core_roleperm_unique")
        ]

    def __str__(self):
        return f"{self.role}: {self.area} {self.level}"


class RoleAction(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="actions")
    action = models.CharField(max_length=40)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "action"], name="core_roleaction_unique")
        ]

    def __str__(self):
        return f"{self.role}: {self.action}"


class UserRole(models.Model):
    """A role held by a user, with who gave it and why."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="role_assignments"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    assigned_at = models.DateTimeField(default=timezone.now)
    reason = models.TextField(blank=True, default="")
    conflict_warning = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "role"], name="core_userrole_unique")
        ]

    def __str__(self):
        return f"{self.user} as {self.role}"


class AccessOverride(models.Model):
    """An Admin's per-user grant or removal of access, over the roles' defaults (spec 1.3).

    Never deleted: revoked and expired overrides stay as history.
    """

    class Effect(models.TextChoices):
        GRANT = "grant", "Grant"
        REMOVE = "remove", "Remove"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="access_overrides"
    )
    # Either an area and level, or a special action.
    area = models.CharField(max_length=40, blank=True, default="")
    level = models.CharField(max_length=10, blank=True, default="")
    action = models.CharField(max_length=40, blank=True, default="")
    effect = models.CharField(max_length=10, choices=Effect.choices)
    reason = models.TextField()
    ends_on = models.DateField(null=True, blank=True)  # last day it applies; empty = no end
    # A sensitive grant has no effect until the Director confirms it.
    is_sensitive = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.TextField(blank=True, default="")
    expiry_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        target = self.action or f"{self.area} {self.level}"
        return f"{self.effect} {target} for {self.user_id}"

    @property
    def status(self) -> str:
        if self.revoked_at:
            return "revoked"
        if self.ends_on and self.ends_on < timezone.localdate():
            return "expired"
        if self.effect == self.Effect.GRANT and self.is_sensitive and not self.confirmed_at:
            return "pending"
        return "active"


class AccessReview(models.Model):
    """A periodic confirmation that a user's access is still right (spec 1.3)."""

    class Outcome(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed as correct"
        CHANGED = "changed", "Changed during review"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="access_reviews"
    )
    period = models.CharField(max_length=7)  # e.g. 2026-Q4
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    reviewed_at = models.DateTimeField(default=timezone.now)
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    note = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "period"], name="core_accessreview_unique")
        ]

    def __str__(self):
        return f"{self.period} review of {self.user_id}: {self.outcome}"


class AuditEvent(models.Model):
    """The audit log (P0-05): who changed what, when, from where, old and new values, and why.

    Insert-only: a database trigger refuses updates and deletes, for everyone.
    """

    class Action(models.TextChoices):
        CREATE = "create", "Created"
        UPDATE = "update", "Changed"
        DELETE = "delete", "Deleted"

    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    actor_email = models.CharField(max_length=254, blank=True, default="")  # "system" for jobs
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    action = models.CharField(max_length=10, choices=Action.choices)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=64)
    object_repr = models.CharField(max_length=255, blank=True, default="")
    # The person the change concerns (their account, roles, overrides, reviews).
    related_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_events",
    )
    event = models.CharField(max_length=50, blank=True, default="")
    reason = models.TextField(blank=True, default="")
    changes = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [models.Index(fields=["object_type", "object_id"], name="core_audit_object")]

    def __str__(self):
        return (
            f"{self.occurred_at:%Y-%m-%d %H:%M} {self.actor_email} {self.action} {self.object_repr}"
        )


class NumberSeries(models.Model):
    """How one document type is numbered (spec 3, Number series; backlog P0-08).

    The format is literal text with tokens in braces: {PP} division code, {YY} or {YYYY}
    year, {MM} month, {DD} day, and one running number {XXX} or {NNNN} (its length is the
    number of digits). The voucher format is {PP}{YY}{MM}{DD}{XXX}, reset daily.
    Document types come with the software; the Admin changes their format and reset period.
    """

    class Reset(models.TextChoices):
        DAILY = "daily", "Every day"
        MONTHLY = "monthly", "Every month"
        YEARLY = "yearly", "Every year"
        NEVER = "never", "Never"

    document_type = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    format = models.CharField(max_length=60)
    reset_period = models.CharField(max_length=10, choices=Reset.choices)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "number series"

    def __str__(self):
        return f"{self.name} ({self.format})"


class NumberCounter(models.Model):
    """The last running number given in one series, for one division and one period."""

    series = models.ForeignKey(NumberSeries, on_delete=models.PROTECT, related_name="counters")
    # Empty when the format has no {PP}: then all divisions share one running number.
    division = models.ForeignKey(
        Division, null=True, blank=True, on_delete=models.PROTECT, related_name="number_counters"
    )
    # "2026-10-23" (daily), "2026-10" (monthly), "2026" (yearly) or "all" (never).
    period = models.CharField(max_length=10)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["series", "division", "period"],
                name="core_numbercounter_unique",
                nulls_distinct=False,
            ),
        ]

    def __str__(self):
        division = self.division_id or "-"
        return f"{self.series.document_type} {division} {self.period}: {self.last_number}"


class IssuedNumber(models.Model):
    """Every number ever given, kept for good so none is ever given twice (insert-only)."""

    series = models.ForeignKey(NumberSeries, on_delete=models.PROTECT, related_name="issued")
    number = models.CharField(max_length=60)
    division = models.ForeignKey(
        Division, null=True, blank=True, on_delete=models.PROTECT, related_name="issued_numbers"
    )
    issued_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["series", "number"], name="core_issuednumber_unique"),
        ]

    def __str__(self):
        return self.number
