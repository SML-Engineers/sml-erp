"""Payment vouchers (spec 4). P1-01: voucher types."""

from django.db import models
from django.utils import timezone

TYPE_CODE_REGEX = r"^[A-Z][A-Z0-9]{1,9}$"


class VoucherType(models.Model):
    """What kind of payment a voucher is (spec 4.1). Master data: the Admin adds types with
    no code change. The type is a field and a list filter, not part of the voucher number,
    and every type passes the same three approval levels (rule 6)."""

    is_structure = True

    class Method(models.TextChoices):
        CHEQUE = "cheque", "Cheque"
        TRANSFER = "transfer", "Bank transfer"
        CHEQUE_OR_TRANSFER = "cheque_or_transfer", "Cheque or bank transfer"
        CASH = "cash", "Cash"
        INTERNAL = "internal", "Between the company's own accounts"
        ANY = "any", "Any"

    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=50, unique=True)
    payment_method = models.CharField(max_length=20, choices=Method.choices)
    # Internal transfers have no payee: both sides are company bank or cash accounts.
    needs_payee = models.BooleanField(default=True)
    # Only payees of this category, e.g. Employee for staff reimbursements; empty: any.
    payee_category = models.CharField(max_length=20, blank=True)
    # Paid before the invoice and set off against it later (supplier advances).
    is_advance = models.BooleanField(default=False)
    notes = models.CharField(max_length=300, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["sort_order", "name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code__regex=TYPE_CODE_REGEX), name="vouchers_type_code_format"
            ),
            models.CheckConstraint(
                condition=models.Q(needs_payee=True) | models.Q(payee_category=""),
                name="vouchers_type_no_payee_no_category",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"
