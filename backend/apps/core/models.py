from datetime import timedelta

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
    # Section scope (spec 1.1): False limits the user to the sections assigned to them
    # (apps.masters.Section.users), e.g. a Production Supervisor for Manual Milling.
    all_sections = models.BooleanField(default=True)
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
    # On the EPF and ETF returns (P2B-09).
    epf_employer_no = models.CharField("EPF employer no.", max_length=30, blank=True)
    etf_employer_no = models.CharField("ETF employer no.", max_length=30, blank=True)
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
    # The division's code in tax invoice numbers (the QQQQ of YYMMM_QQQQ_XXXXX, Gazette
    # 2481/22), e.g. W1 in 26SEP_W1_35. Set by the Admin; fixed once used on an invoice.
    tax_invoice_code = models.CharField(max_length=15, blank=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code__regex=r"^[A-Z0-9]{2}$"), name="core_division_code_format"
            ),
            models.CheckConstraint(
                condition=models.Q(tax_invoice_code__regex=r"^[A-Z0-9]{0,15}$"),
                name="core_division_tax_invoice_code_format",
            ),
            models.UniqueConstraint(
                fields=["tax_invoice_code"],
                condition=~models.Q(tax_invoice_code=""),
                name="core_division_tax_invoice_code_unique",
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

    The format is literal text with tokens in braces: {PP} division code, {IC} division's
    tax invoice code, {YY} or {YYYY} year, {MM} month number or {MMM} month letters (SEP),
    {DD} day, and one running number {XXX} or {NNNN} (its length is the minimum number of
    digits). Vouchers: {PP}{YY}{MM}{DD}{XXX} reset daily; tax invoices: {YY}{MMM}_{IC}_{XX}
    reset monthly.
    Document types come with the software; the Admin changes their format and reset period.
    """

    class Reset(models.TextChoices):
        DAILY = "daily", "Every day"
        MONTHLY = "monthly", "Every month"
        YEARLY = "yearly", "Every year"
        NEVER = "never", "Never"

    document_type = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)

    class WhenFull(models.TextChoices):
        STOP = "stop", "Stop and ask the Admin to widen it"
        GROW = "grow", "Carry on with more digits"

    format = models.CharField(max_length=60)
    reset_period = models.CharField(max_length=10, choices=Reset.choices)
    # When the running number has used all its digits: vouchers stop (P0-08); tax invoices
    # carry on (26SEP_W1_99, then 26SEP_W1_100), because invoicing must never stop.
    when_full = models.CharField(max_length=10, choices=WhenFull.choices, default=WhenFull.STOP)
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


# --- Approval engine (spec 3, backlog P0-17) ---------------------------------------------


class ApprovalRule(models.Model):
    """One cell of the approval matrix: at this level, this role approves documents of this
    type that meet the conditions (amount range, division, sub-type). Level 1 is the person
    who submits; approval levels start at 2 (L2 Accountant, L3 Director for vouchers).

    Rules are never edited: a change is a new rule and the old one switched off, so the
    route of a document already submitted is unaffected (it is copied when submitted)."""

    document_type = models.SlugField(max_length=30)
    level = models.PositiveSmallIntegerField()
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="approval_rules")
    min_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    max_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    division = models.ForeignKey(
        Division, null=True, blank=True, on_delete=models.PROTECT, related_name="approval_rules"
    )
    subtype = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["document_type", "level", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(level__gte=2) & models.Q(level__lte=9),
                name="core_approvalrule_level_range",
            ),
            models.CheckConstraint(
                condition=models.Q(min_amount__isnull=True)
                | models.Q(max_amount__isnull=True)
                | models.Q(min_amount__lte=models.F("max_amount")),
                name="core_approvalrule_amount_range",
            ),
        ]

    def __str__(self):
        return f"{self.document_type} L{self.level}: {self.role.code}"


class ApprovalReminder(models.Model):
    """Reminding approvers again when a document has waited too long at their level
    (spec 4.3, backlog P1-09): once a day, from `after_days` days after the last action on
    it, until someone acts. One setting per document type, kept by the Admin."""

    document_type = models.SlugField(max_length=30, unique=True)
    enabled = models.BooleanField(default=True)
    after_days = models.PositiveSmallIntegerField(default=3)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["document_type"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(after_days__gte=1) & models.Q(after_days__lte=60),
                name="core_approvalreminder_days",
            ),
        ]

    def __str__(self):
        return f"{self.document_type}: after {self.after_days} days"


class ApprovalState(models.Model):
    """Where one document is in its approval: its route (copied when submitted), the level
    waiting, and the result. The document module keeps its own status in step with it."""

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "Waiting for approval"
        APPROVED = "approved", "Approved"
        RETURNED = "returned", "Returned"
        REJECTED = "rejected", "Rejected"
        # Taken out of approval by its module, e.g. a voucher deleted (P1-04b).
        WITHDRAWN = "withdrawn", "Withdrawn"

    document_type = models.SlugField(max_length=30)
    document_id = models.BigIntegerField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    status = models.CharField(max_length=20, choices=Status.choices)
    current_level = models.PositiveSmallIntegerField(null=True, blank=True)
    # [{"level": 2, "role": "accountant"}, {"level": 3, "role": "director"}]
    route = models.JSONField(default=list)
    round = models.PositiveSmallIntegerField(default=1)
    amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    division = models.ForeignKey(
        Division, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    subtype = models.CharField(max_length=30, blank=True)
    # How notifications name the document and where they link to (given by its module).
    title = models.CharField(max_length=200, blank=True)
    link = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document_type", "document_id"], name="core_approvalstate_unique"
            ),
            models.CheckConstraint(
                condition=models.Q(status="in_progress", current_level__isnull=False)
                | (~models.Q(status="in_progress") & models.Q(current_level__isnull=True)),
                name="core_approvalstate_level_when_waiting",
            ),
        ]

    def __str__(self):
        return f"{self.document_type} {self.document_id}: {self.status}"


class ApprovalLog(models.Model):
    """Every approval action on every document (spec 4.5 approval_log). Insert-only:
    nobody, the Admin included, can change or remove a row (rule 7)."""

    class Action(models.TextChoices):
        SUBMIT = "submit", "Submitted"
        APPROVE = "approve", "Approved"
        RETURN = "return", "Returned"
        REJECT = "reject", "Rejected"
        # Changed by a later approver and sent back to the first approval level (P1-04b).
        SEND_DOWN = "send_down", "Changed and sent back"
        WITHDRAW = "withdraw", "Withdrawn"

    document_type = models.SlugField(max_length=30)
    document_id = models.BigIntegerField()
    round = models.PositiveSmallIntegerField()
    level = models.PositiveSmallIntegerField()
    action = models.CharField(max_length=10, choices=Action.choices)
    reason = models.TextField(blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    acted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["acted_at", "id"]
        indexes = [
            models.Index(fields=["document_type", "document_id"], name="core_approvallog_doc"),
        ]
        constraints = [
            # Return and Reject always carry a reason (spec 4.3); so do a change sent back
            # and a withdrawal.
            models.CheckConstraint(
                condition=~models.Q(action__in=["return", "reject", "send_down", "withdraw"])
                | models.Q(reason__regex=r"\S"),
                name="core_approvallog_reason_required",
            ),
        ]

    def __str__(self):
        return f"{self.document_type} {self.document_id} L{self.level} {self.action}"


# --- Notifications (backlog P0-18) -------------------------------------------------------


class Notification(models.Model):
    """One message to one user: shown under the bell and/or sent by email, as the user
    chose for that kind of event."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    event = models.SlugField(max_length=40)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    link = models.CharField(max_length=200, blank=True)
    document_type = models.SlugField(max_length=30, blank=True)
    document_id = models.BigIntegerField(null=True, blank=True)
    in_app = models.BooleanField(default=True)
    email = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "read_at"], name="core_notification_unread"),
        ]

    def __str__(self):
        return f"{self.user} {self.event}: {self.title}"


class NotificationPreference(models.Model):
    """A user's choice for one kind of event. No row means both on."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preferences"
    )
    event = models.SlugField(max_length=40)
    in_app = models.BooleanField(default=True)
    email = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "event"], name="core_notificationpref_unique"),
        ]

    def __str__(self):
        return f"{self.user} {self.event}"


# --- Sending documents by email (spec 3B, backlog P0-19) ---------------------------------


class MailAccount(models.Model):
    """The mailbox documents and reports are sent from (e.g. finance@domain.com). One row,
    id 1. The password is stored encrypted and never leaves the server."""

    class Security(models.TextChoices):
        STARTTLS = "starttls", "STARTTLS (usually port 587)"
        SSL = "ssl", "SSL/TLS (usually port 465)"
        NONE = "none", "None (only for a mail server on the same machine)"

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    from_name = models.CharField(max_length=100, blank=True)
    from_address = models.EmailField(blank=True)
    reply_to = models.EmailField(blank=True)
    copy_to = models.EmailField(blank=True)
    host = models.CharField(max_length=200, blank=True)
    port = models.PositiveIntegerField(default=587)
    security = models.CharField(max_length=10, choices=Security.choices, default=Security.STARTTLS)
    username = models.CharField(max_length=200, blank=True)
    password_encrypted = models.TextField(blank=True)
    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)
    last_test_error = models.CharField(max_length=500, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="core_mailaccount_single_row"),
        ]

    def __str__(self):
        return self.from_address or "(not set up)"

    @classmethod
    def get(cls) -> "MailAccount":
        account, _ = cls.objects.get_or_create(pk=1)
        return account

    @property
    def is_ready(self) -> bool:
        return bool(self.from_address and self.host)


class EmailTemplate(models.Model):
    """The default subject and message for one kind of document or report, with
    placeholders such as {customer_name}. The person sending may edit them each time."""

    document_type = models.SlugField(max_length=30, unique=True)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["document_type"]

    def __str__(self):
        return self.document_type


class SentEmail(models.Model):
    """Every document email sent or attempted, exactly as sent. Insert-only (database)."""

    class Status(models.TextChoices):
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    document_type = models.SlugField(max_length=30)
    document_id = models.BigIntegerField(null=True, blank=True)
    document_label = models.CharField(max_length=200)
    from_address = models.CharField(max_length=300)
    to = models.TextField()
    cc = models.TextField(blank=True)
    bcc = models.TextField(blank=True)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    attachment = models.FileField(upload_to="sent-emails/%Y/%m/", blank=True)
    attachment_name = models.CharField(max_length=200, blank=True)
    attachment_sha256 = models.CharField(max_length=64, blank=True)
    # Further files sent with the document, one per line: name and SHA-256 (e.g. a
    # quotation's product pictures).
    other_attachments = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    error = models.CharField(max_length=500, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    sent_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-sent_at", "-id"]
        indexes = [
            models.Index(fields=["document_type", "document_id"], name="core_sentemail_doc"),
        ]

    def __str__(self):
        return f"{self.document_label} to {self.to} ({self.status})"


class PasswordReset(models.Model):
    """The Admin asks to reset someone's password (and, if their phone is lost, their
    authenticator); the Director approves; then the Admin makes a temporary password, shown
    once (owner's decision, 31 Oct 2026). The temporary password is never stored."""

    APPROVAL_HOURS = 24  # an approval not used within this time lapses

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="password_resets"
    )
    with_authenticator = models.BooleanField(default=False)
    reason = models.TextField()
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    requested_at = models.DateTimeField(default=timezone.now)
    approved = models.BooleanField(null=True, blank=True)  # empty while waiting
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True, default="")
    issued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-requested_at", "-id"]

    def __str__(self):
        return f"Password reset for {self.user} ({self.status})"

    @property
    def status(self) -> str:
        if self.approved is None:
            return "waiting"
        if self.approved is False:
            return "refused"
        if self.issued_at:
            return "done"
        if timezone.now() - self.decided_at > timedelta(hours=self.APPROVAL_HOURS):
            return "lapsed"
        return "approved"
