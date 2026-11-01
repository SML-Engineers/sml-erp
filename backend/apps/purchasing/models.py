"""Purchase orders (backlog P16-04, spec 5A.1).

Raised by the Purchasing Officer, approved by the Director, then sent to the supplier. Once it
leaves draft, the database refuses any change to what was ordered (supplier, prices,
quantities, terms, totals); only its status moves on and goods receipts (P16-06) record the
quantity received per line. A change after approval is a revision (Rev 1, 2, …) that goes
through approval again.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


def money(**extra):
    return models.DecimalField(max_digits=18, decimal_places=2, **extra)


def quantity(**extra):
    return models.DecimalField(max_digits=18, decimal_places=3, **extra)


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING_APPROVAL = "awaiting_approval", "Waiting for the Director"
        APPROVED = "approved", "Approved"
        PARTLY_RECEIVED = "partly_received", "Partly received"
        RECEIVED = "received", "Received"
        CLOSED = "closed", "Closed short"
        CANCELLED = "cancelled", "Cancelled"
        REVISED = "revised", "Replaced by a revision"

    class PayMode(models.TextChoices):
        ONLINE = "online", "Online"
        CHEQUE = "cheque", "Cheque"
        CASH = "cash", "Cash"

    number = models.CharField(max_length=30, db_index=True)
    revision = models.PositiveSmallIntegerField(default=0)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="revisions"
    )
    supplier = models.ForeignKey(
        "masters.Supplier", on_delete=models.PROTECT, related_name="purchase_orders"
    )
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    po_date = models.DateField()
    delivery_date = models.DateField(null=True, blank=True)
    deliver_to = models.TextField(blank=True)
    pay_mode = models.CharField(max_length=10, choices=PayMode.choices, default=PayMode.ONLINE)
    payment_terms = models.CharField(max_length=100, blank=True)
    currency = models.ForeignKey("masters.Currency", on_delete=models.PROTECT, related_name="+")
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    rate_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    subtotal = money(default=0)
    tax_total = money(default=0)
    total_amount = money(default=0)
    total_lkr = money(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    approved_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.TextField(blank=True)  # why it was closed short or cancelled

    class Meta:
        ordering = ["-po_date", "-number", "-revision"]
        constraints = [
            models.UniqueConstraint(fields=["number", "revision"], name="purchasing_po_revision")
        ]

    def __str__(self):
        return self.label

    @property
    def label(self) -> str:
        return self.number if self.revision == 0 else f"{self.number} Rev {self.revision}"


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="+")
    description = models.CharField(max_length=300)
    unit = models.CharField(max_length=10)
    quantity = quantity()
    unit_price = money()
    amount = money()
    tax_code = models.ForeignKey(
        "accounting.TaxCode", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    tax_amount = money(default=0)
    total = money()
    # Filled by goods receipts (P16-06); never typed.
    received_quantity = quantity(default=0)

    class Meta:
        ordering = ["order", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["order", "line_no"], name="purchasing_line_no"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="purchasing_qty_pos"),
            models.CheckConstraint(
                condition=models.Q(received_quantity__gte=0), name="purchasing_received_pos"
            ),
        ]

    def __str__(self):
        return f"{self.order} line {self.line_no}"
