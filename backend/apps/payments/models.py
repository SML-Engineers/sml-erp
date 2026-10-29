"""Supplier payments (spec 4.5 supplier_payment, 4.6 the payment lock; backlog P1-07)."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class SupplierPayment(models.Model):
    """Money paid against a Director-approved voucher, never from a blank form. Its journal
    entry is posted in the same transaction. Insert-only: a database trigger refuses any
    payment for a voucher not approved by the Director, or beyond the approved amount."""

    class Method(models.TextChoices):
        CHEQUE = "cheque", "Cheque"
        TRANSFER = "transfer", "Bank transfer"
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        QR = "qr", "QR code (LankaQR)"

    number = models.CharField(max_length=40, unique=True)
    voucher = models.ForeignKey(
        "vouchers.Voucher", on_delete=models.PROTECT, related_name="payments"
    )
    # Paid from: a company bank account, cash box or petty cash float.
    account = models.ForeignKey(
        "masters.CompanyAccount", on_delete=models.PROTECT, related_name="supplier_payments"
    )
    method = models.CharField(max_length=10, choices=Method.choices)
    # Cheque number, transfer reference, card or QR transaction reference.
    reference = models.CharField(max_length=50, blank=True)
    cheque = models.OneToOneField(
        "masters.ChequeLeaf",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment",
    )
    cheque_date = models.DateField(null=True, blank=True)
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    notes = models.CharField(max_length=300, blank=True)
    journal_entry = models.OneToOneField(
        "accounting.JournalEntry", on_delete=models.PROTECT, related_name="supplier_payment"
    )
    # Kept for the spec's payment lock; cancelling a payment comes later (a reversing entry).
    cancelled = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-payment_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="payments_amount_positive"
            ),
            models.CheckConstraint(
                condition=~models.Q(method="cheque") | models.Q(cheque__isnull=False),
                name="payments_cheque_has_leaf",
            ),
        ]

    def __str__(self):
        return self.number
