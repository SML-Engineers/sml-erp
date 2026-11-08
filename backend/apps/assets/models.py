"""Fixed asset register and depreciation (backlog P2-19, spec 6).

Each asset belongs to a class (land, buildings, plant and machinery, moulds and tooling,
vehicles, furniture, office and computer equipment) whose method and annual rate are dated
(rule 11) and agreed with the auditors. Depreciation is worked out month by month, checked by
the Accountant and then posted; a posted month never changes. Disposals post the gain or loss.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


def money(**extra):
    return models.DecimalField(max_digits=18, decimal_places=2, **extra)


class Method(models.TextChoices):
    STRAIGHT_LINE = "straight_line", "Straight line (on cost)"
    REDUCING_BALANCE = "reducing_balance", "Reducing balance (on book value)"
    NONE = "none", "Not depreciated (land)"


class AssetClass(models.Model):
    """A class of assets with the accounts it is kept in."""

    is_structure = True

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    cost_account = models.ForeignKey(
        "accounting.Account", on_delete=models.PROTECT, related_name="+"
    )
    accumulated_account = models.ForeignKey(
        "accounting.Account", on_delete=models.PROTECT, related_name="+"
    )
    expense_account = models.ForeignKey(
        "accounting.Account", on_delete=models.PROTECT, related_name="+"
    )
    gain_account = models.ForeignKey(
        "accounting.Account", on_delete=models.PROTECT, related_name="+"
    )
    loss_account = models.ForeignKey(
        "accounting.Account", on_delete=models.PROTECT, related_name="+"
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "code"]

    def __str__(self):
        return self.name


class Approval(models.TextChoices):
    AWAITING = "awaiting", "Waiting for the Director"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class AssetClassRate(models.Model):
    """The default method, annual rate and useful life of a class from a date (rule 11),
    which new assets of the class take. The Accountant sets them and the Director approves
    (owner, 8 Nov 2026); months already posted keep the rate they were worked out at."""

    asset_class = models.ForeignKey(AssetClass, on_delete=models.PROTECT, related_name="rates")
    effective_from = models.DateField()
    method = models.CharField(max_length=20, choices=Method.choices)
    rate = models.DecimalField(max_digits=7, decimal_places=4)  # percent a year
    life_years = models.PositiveSmallIntegerField("Useful life (years)", null=True, blank=True)
    status = models.CharField(max_length=10, choices=Approval.choices, default=Approval.APPROVED)
    reason = models.TextField(blank=True)
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    set_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["asset_class", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["asset_class", "effective_from"],
                condition=~models.Q(status="rejected"),
                name="assets_rate_once_per_day",
            ),
            models.CheckConstraint(
                condition=models.Q(rate__gte=0) & models.Q(rate__lte=100),
                name="assets_rate_percent",
            ),
        ]

    def __str__(self):
        return f"{self.asset_class} {self.rate}% from {self.effective_from}"


class FixedAsset(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "In use"
        DISPOSED = "disposed", "Disposed"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    asset_class = models.ForeignKey(AssetClass, on_delete=models.PROTECT, related_name="assets")
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    machine = models.ForeignKey(
        "masters.Machine", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    serial_no = models.CharField(max_length=100, blank=True)
    supplier = models.CharField(max_length=200, blank=True)
    acquisition_date = models.DateField()
    # The first month depreciated (its first day).
    depreciation_from = models.DateField()
    cost = money()
    residual_value = money(default=0)
    # A register brought in at go-live: the depreciation charged before the ERP.
    opening_accumulated = money(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    disposed_on = models.DateField(null=True, blank=True)
    proceeds = money(default=0)
    disposal_reason = models.TextField(blank=True)
    disposal_entry = models.OneToOneField(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="asset_disposal",
    )
    # Moulds: shots made so far, filled from production in Phase 3.
    shot_count = models.PositiveBigIntegerField(default=0)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cost__gt=0)
                & models.Q(residual_value__gte=0)
                & models.Q(opening_accumulated__gte=0)
                & models.Q(proceeds__gte=0),
                name="assets_amounts",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    residual_value__lte=models.F("cost") - models.F("opening_accumulated")
                ),
                name="assets_residual_within_cost",
            ),
            models.CheckConstraint(
                condition=models.Q(status="active")
                | models.Q(disposed_on__isnull=False, disposal_entry__isnull=False),
                name="assets_disposed_posted",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class DepreciationRun(models.Model):
    """A month's depreciation: worked out as a draft for the Accountant to check, then posted
    (Dr depreciation, Cr accumulated depreciation, per class and division). Posted, it never
    changes (database guard)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Worked out, to check"
        POSTED = "posted", "Posted"

    month_end = models.DateField(unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    total = money(default=0)
    journal_entry = models.OneToOneField(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="depreciation_run",
    )
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    prepared_at = models.DateTimeField(default=timezone.now)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-month_end"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(status="posted") | models.Q(journal_entry__isnull=False),
                name="assets_run_posted_entry",
            ),
        ]

    def __str__(self):
        return f"Depreciation {self.month_end:%B %Y}"


class DepreciationLine(models.Model):
    run = models.ForeignKey(DepreciationRun, on_delete=models.CASCADE, related_name="lines")
    asset = models.ForeignKey(FixedAsset, on_delete=models.PROTECT, related_name="depreciation")
    method = models.CharField(max_length=20, choices=Method.choices)
    rate = models.DecimalField(max_digits=7, decimal_places=4)
    book_value_before = money()
    amount = money()

    class Meta:
        ordering = ["run", "asset__code"]
        constraints = [
            models.UniqueConstraint(fields=["run", "asset"], name="assets_line_once"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="assets_line_amount"),
        ]

    def __str__(self):
        return f"{self.run} {self.asset}"


class AssetTerms(models.Model):
    """One asset's depreciation method, rate and useful life from a month (owner, 8 Nov
    2026): a new asset takes its class's defaults, which the Accountant may change for it;
    the Director approves each before the asset is depreciated with them. A later change is
    new terms from a later month; months already posted keep what they used."""

    asset = models.ForeignKey(FixedAsset, on_delete=models.PROTECT, related_name="terms")
    effective_from = models.DateField()
    method = models.CharField(max_length=20, choices=Method.choices)
    rate = models.DecimalField(max_digits=7, decimal_places=4)  # percent a year
    life_years = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Approval.choices, default=Approval.AWAITING)
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["asset", "-effective_from", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["asset", "effective_from"],
                condition=~models.Q(status="rejected"),
                name="assets_terms_once_per_month",
            ),
            models.CheckConstraint(
                condition=models.Q(rate__gte=0) & models.Q(rate__lte=100),
                name="assets_terms_percent",
            ),
        ]

    def __str__(self):
        return f"{self.asset_id} {self.rate}% from {self.effective_from}"
