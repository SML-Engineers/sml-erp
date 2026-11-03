"""Cheque register and deposits (backlog P2-14, spec 6 banking).

- Customers' cheques wait in Undeposited funds once their receipt is posted. A deposit slip
  takes some of them to a bank account: Dr the bank, Cr Undeposited funds.
- A cheque is marked cleared when the bank has paid it (ours) or credited it (the
  customer's). A customer's cheque that comes back unpaid is returned on its receipt (sales).
- All three are insert-only (database guard): a mistake is corrected by another document.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Deposit(models.Model):
    """A deposit slip: customers' cheques taken to the bank together."""

    number = models.CharField(max_length=30, unique=True)
    account = models.ForeignKey(
        "masters.CompanyAccount", on_delete=models.PROTECT, related_name="deposits"
    )
    deposit_date = models.DateField()
    slip_no = models.CharField(max_length=50, blank=True)  # the bank's slip number
    total = models.DecimalField(max_digits=18, decimal_places=2)
    journal_entry = models.OneToOneField(
        "accounting.JournalEntry", on_delete=models.PROTECT, related_name="deposit"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-deposit_date", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(total__gt=0), name="banking_deposit_total"),
        ]

    def __str__(self):
        return self.number


class DepositLine(models.Model):
    deposit = models.ForeignKey(Deposit, on_delete=models.PROTECT, related_name="lines")
    receipt = models.OneToOneField(
        "sales.CustomerReceipt", on_delete=models.PROTECT, related_name="deposit_line"
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)  # LKR

    class Meta:
        ordering = ["deposit", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="banking_line_amount"),
        ]

    def __str__(self):
        return f"{self.deposit} {self.receipt}"


class ChequeClearance(models.Model):
    """The bank paid one of our cheques, or credited a customer's cheque we deposited."""

    leaf = models.OneToOneField(
        "masters.ChequeLeaf",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="clearance",
    )
    deposit_line = models.OneToOneField(
        DepositLine, null=True, blank=True, on_delete=models.PROTECT, related_name="clearance"
    )
    cleared_on = models.DateField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-cleared_on", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(leaf__isnull=False, deposit_line__isnull=True)
                | models.Q(leaf__isnull=True, deposit_line__isnull=False),
                name="banking_clearance_one_cheque",
            ),
        ]

    def __str__(self):
        return f"Cleared {self.cleared_on}"
