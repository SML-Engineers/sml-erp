"""Production (Phase 3, spec 7). P3-01: moulds."""

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
