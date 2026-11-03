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
    # What it pays of the voucher, in LKR (the voucher's amounts; the payment lock counts this).
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    # What left the account, in the account's currency, and the rate of the payment date
    # (P2-11). For an LKR account: the same as `amount`, at 1. For a foreign-currency payment
    # the difference between the LKR value at this rate and `amount` is an exchange gain or
    # loss.
    currency = models.ForeignKey("masters.Currency", on_delete=models.PROTECT, related_name="+")
    paid_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    notes = models.CharField(max_length=300, blank=True)
    journal_entry = models.OneToOneField(
        "accounting.JournalEntry", on_delete=models.PROTECT, related_name="supplier_payment"
    )
    # Set only when the Director approves its cancellation (P2-11; database guard): a reversing
    # entry is posted and the voucher is open to pay again.
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


class PaymentCancellation(models.Model):
    """A request to cancel a payment (P2-11): the cheque was spoiled, written wrongly or never
    sent, or the transfer failed. The Cashier or the Accountant asks, with a reason; the
    Director approves through the approval engine ("payment_cancellation"). Approval posts the
    reversing entry, marks the payment cancelled and its cheque leaf spoiled, and opens the
    voucher to pay again. Decided requests never change (database guard)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for the Director"
        APPROVED = "approved", "Approved: payment cancelled"
        REJECTED = "rejected", "Rejected"

    payment = models.ForeignKey(
        SupplierPayment, on_delete=models.PROTECT, related_name="cancellations"
    )
    reason = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    requested_at = models.DateTimeField(default=timezone.now)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    reversal_entry = models.OneToOneField(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="payment_cancellation",
    )

    class Meta:
        ordering = ["-requested_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["payment"],
                condition=models.Q(status__in=["pending", "approved"]),
                name="payments_one_open_cancellation",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="approved") | models.Q(reversal_entry__isnull=False),
                name="payments_cancellation_reversed",
            ),
        ]

    def __str__(self):
        return f"Cancel {self.payment}"
