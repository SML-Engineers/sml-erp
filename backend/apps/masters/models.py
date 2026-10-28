"""Factory structure: Division → Section → Machine (spec 3A.1, backlog P0-09).

Codes are fixed once a transaction has used them, and anything with history is made
inactive rather than deleted (rule 9); the database enforces both (migration 0002).
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import Division

CODE_REGEX = r"^[A-Z0-9][A-Z0-9-]{0,19}$"


class Section(models.Model):
    # Factory structure, not a document: having sections does not fix a division's code.
    is_structure = True

    class Category(models.TextChoices):
        MANUAL = "manual", "Manual"
        CNC = "cnc", "CNC"

    class Type(models.TextChoices):
        MACHINING = "machining", "Machining"
        MOULDING = "moulding", "Moulding"
        SUPPORT = "support", "Support"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    division = models.ForeignKey(Division, on_delete=models.PROTECT, related_name="sections")
    # Manual or CNC for machining sections; empty for moulding and support.
    category = models.CharField(max_length=10, choices=Category.choices, blank=True)
    section_type = models.CharField(max_length=20, choices=Type.choices)
    supervisors = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="supervised_sections"
    )
    # Section scope (spec 1.1): users limited to particular sections. Users whose
    # `all_sections` is set see every section of their divisions.
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="sections")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["division__code", "code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code__regex=CODE_REGEX), name="masters_section_code_format"
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class Machine(models.Model):
    # Factory structure, not a document: having machines does not fix a section's code.
    is_structure = True

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        MAINTENANCE = "maintenance", "Under maintenance"
        RETIRED = "retired", "Retired"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name="machines")
    make = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    serial_no = models.CharField("Serial no.", max_length=100, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    # Retired machines are hidden from entry pages; their history stays.
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    photo = models.FileField(upload_to="machines/", blank=True)
    notes = models.TextField(blank=True)

    # Moulding machines: used to warn when a mould is planned on a machine too small for it.
    clamping_force_t = models.DecimalField(
        "Clamping force (t)", max_digits=8, decimal_places=1, null=True, blank=True
    )
    max_shot_weight_g = models.DecimalField(
        "Maximum shot weight (g)", max_digits=10, decimal_places=1, null=True, blank=True
    )
    screw_diameter_mm = models.DecimalField(
        "Screw diameter (mm)", max_digits=7, decimal_places=1, null=True, blank=True
    )
    tie_bar_h_mm = models.DecimalField(
        "Tie-bar spacing, horizontal (mm)", max_digits=7, decimal_places=1, null=True, blank=True
    )
    tie_bar_v_mm = models.DecimalField(
        "Tie-bar spacing, vertical (mm)", max_digits=7, decimal_places=1, null=True, blank=True
    )
    max_mould_height_mm = models.DecimalField(
        "Maximum mould height (mm)", max_digits=7, decimal_places=1, null=True, blank=True
    )
    max_mould_thickness_mm = models.DecimalField(
        "Maximum mould thickness (mm)", max_digits=7, decimal_places=1, null=True, blank=True
    )

    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code__regex=CODE_REGEX), name="masters_machine_code_format"
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def is_active(self) -> bool:
        return self.status != self.Status.RETIRED


class MachineRate(models.Model):
    """Hourly machine rate in LKR from a date (rule 11). Earlier jobs keep the old rate.

    Once its date has arrived a rate can no longer be changed or removed; a new rate with a
    later date replaces it (migration 0002).
    """

    # A setting with its own history, not a transaction: rates do not fix a machine's code.
    is_structure = True

    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="rates")
    effective_from = models.DateField()
    rate = models.DecimalField("Hourly rate (LKR)", max_digits=18, decimal_places=2)
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["machine", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["machine", "effective_from"], name="masters_machinerate_one_per_day"
            ),
            models.CheckConstraint(
                condition=models.Q(rate__gte=0), name="masters_rate_not_negative"
            ),
        ]

    def __str__(self):
        return f"{self.machine.code} {self.rate} from {self.effective_from}"
