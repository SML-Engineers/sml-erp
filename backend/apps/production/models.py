"""Production (Phase 3, spec 7). P3-01: moulds."""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.masters.models import CODE_REGEX


def size(label: str):
    return models.DecimalField(label, max_digits=7, decimal_places=1, null=True, blank=True)


class Mould(models.Model):
    """An injection mould (spec 7.1; backlog P3-01). Company moulds are linked to their fixed
    asset (P2-19) once it is in the register; customer moulds are tracked for shots and
    maintenance but not costed (owner, 7 Nov 2026). The code is fixed once a production
    document uses it, and a used mould is retired, never deleted (rule 9, database)."""

    class Owner(models.TextChoices):
        COMPANY = "company", "Company"
        CUSTOMER = "customer", "Customer"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        MAINTENANCE = "maintenance", "Under maintenance"
        RETIRED = "retired", "Retired"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    owner = models.CharField(max_length=10, choices=Owner.choices, default=Owner.COMPANY)
    customer = models.ForeignKey(
        "masters.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="moulds"
    )
    asset = models.OneToOneField(
        "assets.FixedAsset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="mould",
    )
    cycle_time_s = models.DecimalField("Standard cycle time (s)", max_digits=7, decimal_places=2)
    shot_weight_g = models.DecimalField(
        "Shot weight with runner (g)", max_digits=10, decimal_places=1
    )
    runner_weight_g = models.DecimalField(
        "Runner weight (g)", max_digits=10, decimal_places=1, default=0
    )
    tonnage_t = size("Clamping force needed (t)")
    width_mm = size("Width (mm)")
    height_mm = size("Height (mm)")
    thickness_mm = size("Thickness, closed (mm)")
    machines = models.ManyToManyField(
        "masters.Machine", blank=True, related_name="moulds", verbose_name="Compatible machines"
    )
    pm_interval_shots = models.PositiveIntegerField(
        "Maintenance every (shots)", null=True, blank=True
    )
    shot_count = models.PositiveBigIntegerField(default=0)
    shots_at_last_pm = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code__regex=CODE_REGEX), name="production_mould_code_format"
            ),
            models.CheckConstraint(
                condition=models.Q(owner="company", customer__isnull=True)
                | models.Q(owner="customer", customer__isnull=False, asset__isnull=True),
                name="production_mould_owner",
            ),
            models.CheckConstraint(
                condition=models.Q(cycle_time_s__gt=0, shot_weight_g__gt=0),
                name="production_mould_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(shots_at_last_pm__lte=models.F("shot_count")),
                name="production_mould_shots",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def is_active(self) -> bool:
        return self.status != self.Status.RETIRED


class MouldPart(models.Model):
    """A part the mould makes and its cavities; a family mould makes several parts."""

    mould = models.ForeignKey(Mould, on_delete=models.CASCADE, related_name="parts")
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="moulds")
    cavities = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["mould", "item__code"]
        constraints = [
            models.UniqueConstraint(fields=["mould", "item"], name="production_mouldpart_once"),
            models.CheckConstraint(
                condition=models.Q(cavities__gte=1), name="production_mouldpart_cavities"
            ),
        ]

    def __str__(self):
        return f"{self.mould_id}: {self.item_id} x {self.cavities}"


class ReasonCode(models.Model):
    """A reason a part is rejected or a machine stops, per division (spec 7.1, 7.4; backlog
    P3-02). Downtime reasons are planned (a planned stop is not lost time in OEE) or
    unplanned. The Admin adds, renames and deactivates them; the code is fixed once a shift
    report uses it, and a used reason is deactivated, never deleted (rule 9, database)."""

    class Kind(models.TextChoices):
        REJECT = "reject", "Reject"
        DOWNTIME = "downtime", "Downtime"

    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    planned = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["division", "kind", "sort_order", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["division", "kind", "code"], name="production_reason_once"
            ),
            models.CheckConstraint(
                condition=models.Q(code__regex=CODE_REGEX), name="production_reason_code_format"
            ),
            models.CheckConstraint(
                condition=models.Q(kind="downtime") | models.Q(planned=False),
                name="production_reason_planned_downtime",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class ProductionSetting(models.Model):
    """The production limits from a date (rule 11; backlog P3-02; owner, 7 Nov 2026: set in
    a control panel by an authorised person, not in code). A setting in force is never
    changed; a new one with a later date replaces it (database)."""

    effective_from = models.DateField(unique=True)
    grace_hours = models.DecimalField(
        "Entry grace period after a shift (hours)", max_digits=4, decimal_places=1
    )
    reject_alert_pct = models.DecimalField("Reject % alert", max_digits=5, decimal_places=2)
    overrun_alert_pct = models.DecimalField("Cost overrun % alert", max_digits=5, decimal_places=2)
    # Blank: the minimum margin of the order's quotation.
    min_margin_pct = models.DecimalField(
        "Minimum margin %", max_digits=5, decimal_places=2, null=True, blank=True
    )
    reason = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-effective_from"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    grace_hours__gte=0,
                    grace_hours__lte=48,
                    reject_alert_pct__gt=0,
                    reject_alert_pct__lte=100,
                    overrun_alert_pct__gt=0,
                    overrun_alert_pct__lte=100,
                ),
                name="production_setting_ranges",
            ),
        ]

    def __str__(self):
        return f"Production settings from {self.effective_from}"


class Routing(models.Model):
    """The operations that make a machined part (spec 7.1; backlog P3-03), one revision at a
    time: the Production Planner prepares a draft and submits it, the Production Manager
    approves it (approval engine, "routing"), and it replaces the part's routing in force,
    which becomes obsolete. Approved and obsolete routings never change and are never deleted
    (database); a change is a new revision."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING = "awaiting", "Waiting for approval"
        APPROVED = "approved", "Approved"
        OBSOLETE = "obsolete", "Obsolete"

    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="routings")
    revision = models.PositiveSmallIntegerField()
    drawing_revision = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["item__code", "-revision"]
        constraints = [
            models.UniqueConstraint(fields=["item", "revision"], name="production_routing_rev"),
            models.UniqueConstraint(
                fields=["item"],
                condition=models.Q(status="approved"),
                name="production_routing_one_in_force",
            ),
            models.UniqueConstraint(
                fields=["item"],
                condition=models.Q(status__in=["draft", "awaiting"]),
                name="production_routing_one_open",
            ),
        ]

    def __str__(self):
        return f"{self.item_id} rev {self.revision}"


class RoutingOperation(models.Model):
    """One operation: in a section (the machining method, e.g. manual milling) and optionally
    on one machine, with standard setup and run times; or sent out to a supplier."""

    routing = models.ForeignKey(Routing, on_delete=models.CASCADE, related_name="operations")
    seq = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=100)
    section = models.ForeignKey(
        "masters.Section", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    machine = models.ForeignKey(
        "masters.Machine", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    setup_min = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    run_min = models.DecimalField(
        "Run minutes per piece", max_digits=10, decimal_places=3, default=0
    )
    subcontract = models.BooleanField(default=False)
    supplier = models.ForeignKey(
        "masters.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    subcontract_cost = models.DecimalField(
        "Cost per piece", max_digits=18, decimal_places=2, null=True, blank=True
    )
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["routing", "seq"]
        constraints = [
            models.UniqueConstraint(fields=["routing", "seq"], name="production_operation_seq"),
            models.CheckConstraint(
                condition=models.Q(subcontract=True, supplier__isnull=False)
                | models.Q(subcontract=False, section__isnull=False),
                name="production_operation_where",
            ),
            models.CheckConstraint(
                condition=models.Q(setup_min__gte=0, run_min__gte=0),
                name="production_operation_times",
            ),
        ]

    def __str__(self):
        return f"{self.seq} {self.name}"
