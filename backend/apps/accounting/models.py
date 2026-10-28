"""Chart of accounts (spec 3, backlog P0-15).

Works like QuickBooks: every account has a fixed account type and an editable detail type,
sub-accounts go to any depth, account numbers are optional. The database refuses deleting an
account that has been used or that the system needs, and keeps a merge final (migration 0001).
"""

from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.core.models import Division

from .catalogue import SYSTEM_ROLE_CHOICES, TYPE_CHOICES

NUMBER_REGEX = r"^[A-Z0-9][A-Z0-9.-]{0,19}$"


class DetailType(models.Model):
    """Refines an account type (e.g. Fixed asset → Moulds and tooling). Editable list."""

    is_structure = True

    account_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["account_type", "name"]
        constraints = [
            models.UniqueConstraint(
                "account_type", Lower("name"), name="accounting_detailtype_unique_name"
            ),
        ]

    def __str__(self):
        return self.name


class Account(models.Model):
    # A ledger account is not a document: having accounts does not fix a division's code.
    is_structure = True

    number = models.CharField(max_length=20, blank=True)
    name = models.CharField(max_length=100)
    account_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    detail_type = models.ForeignKey(DetailType, on_delete=models.PROTECT, related_name="accounts")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    description = models.CharField(max_length=500, blank=True)
    default_division = models.ForeignKey(
        Division,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="default_accounts",
    )
    # Set on the accounts the system posts to; such accounts cannot be removed.
    system_role = models.CharField(max_length=30, choices=SYSTEM_ROLE_CHOICES, blank=True)
    is_active = models.BooleanField(default=True)
    # A merged account keeps its posted history (rule 3) and points at the account that
    # replaced it; reports show that history under the remaining account.
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="merged_accounts"
    )
    merged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["number", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["number"],
                condition=~models.Q(number=""),
                name="accounting_account_unique_number",
            ),
            models.CheckConstraint(
                condition=models.Q(number="") | models.Q(number__regex=NUMBER_REGEX),
                name="accounting_account_number_format",
            ),
            # Names are unique within the same parent (spec 3).
            models.UniqueConstraint(
                Lower("name"),
                "parent",
                condition=models.Q(parent__isnull=False),
                name="accounting_account_unique_sub_name",
            ),
            models.UniqueConstraint(
                Lower("name"),
                condition=models.Q(parent__isnull=True),
                name="accounting_account_unique_top_name",
            ),
            models.UniqueConstraint(
                fields=["system_role"],
                condition=~models.Q(system_role=""),
                name="accounting_account_one_per_system_role",
            ),
            models.CheckConstraint(
                condition=~models.Q(parent=models.F("id")), name="accounting_account_not_own_parent"
            ),
            models.CheckConstraint(
                condition=models.Q(merged_into__isnull=True)
                | (
                    models.Q(is_active=False, merged_at__isnull=False, system_role="")
                    & ~models.Q(merged_into=models.F("id"))
                ),
                name="accounting_account_merged_is_inactive",
            ),
        ]

    def __str__(self):
        return f"{self.number} {self.name}".strip()
