"""Payroll and people (Phase 2b, docs/backlog/phase-2b.md)."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Employee(models.Model):
    """A person employed by the company (P2B-01). The employee number never changes; an
    employee who leaves is deactivated, never deleted, so their payroll history stays. The
    salary bank account, like a supplier's, is checked by a second person whenever it changes:
    until then it is not paid to (spec 4.6, 7A)."""

    class Type(models.TextChoices):
        PERMANENT = "permanent", "Permanent"
        PROBATION = "probation", "On probation"
        CONTRACT = "contract", "Contract"
        CASUAL = "casual", "Casual"
        TRAINEE = "trainee", "Trainee"

    number = models.CharField(max_length=20, unique=True)
    full_name = models.CharField(max_length=200)
    name_with_initials = models.CharField(max_length=100, blank=True)
    nic = models.CharField("NIC", max_length=12, unique=True)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.CharField(max_length=300, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    epf_no = models.CharField("EPF number", max_length=20, blank=True)
    etf_no = models.CharField("ETF number", max_length=20, blank=True)
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    section = models.ForeignKey(
        "masters.Section", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    designation = models.CharField(max_length=100, blank=True)
    grade = models.CharField(max_length=30, blank=True)
    employment_type = models.CharField(max_length=12, choices=Type.choices)
    join_date = models.DateField()
    confirmation_date = models.DateField(null=True, blank=True)
    leaving_date = models.DateField(null=True, blank=True)
    leaving_reason = models.CharField(max_length=200, blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="employee",
    )
    # Salary bank account, and its second check.
    bank_name = models.CharField(max_length=100, blank=True)
    bank_branch = models.CharField(max_length=100, blank=True)
    account_name = models.CharField(max_length=200, blank=True)
    account_number = models.CharField(max_length=34, blank=True)
    bank_changed_at = models.DateTimeField(null=True, blank=True)
    bank_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    bank_checked_at = models.DateTimeField(null=True, blank=True)
    bank_checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(leaving_date__isnull=True)
                | models.Q(leaving_date__gte=models.F("join_date")),
                name="payroll_employee_dates",
            ),
        ]

    def __str__(self):
        return f"{self.number} {self.full_name}"

    @property
    def bank_check_pending(self) -> bool:
        return bool(self.bank_changed_at) and (
            self.bank_checked_at is None or self.bank_checked_at < self.bank_changed_at
        )
