"""Sales documents (spec 5; Phase 1.5): quotations first (backlog P15-03).

A quotation is made for one customer and one production division, in the customer's
currency with the exchange rate of its date. Money is Decimal (rule 1); the number comes from
the number series in the saving transaction (rule 10). Revisions keep the number and count
up (Rev 0, Rev 1, ...; P15-06).
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Quotation(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING_APPROVAL = "awaiting_approval", "Awaiting approval"
        APPROVED = "approved", "Approved"
        SENT = "sent", "Sent"
        ACCEPTED = "accepted", "Accepted"
        LOST = "lost", "Lost"
        EXPIRED = "expired", "Expired"
        REVISED = "revised", "Replaced by a revision"

    number = models.CharField(max_length=30, db_index=True)
    revision = models.PositiveSmallIntegerField(default=0)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="revisions"
    )
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    customer = models.ForeignKey(
        "masters.Customer", on_delete=models.PROTECT, related_name="quotations"
    )
    contact = models.ForeignKey(
        "masters.CustomerContact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    enquiry_ref = models.CharField("Enquiry reference", max_length=100, blank=True)
    quote_date = models.DateField()
    valid_until = models.DateField()
    currency = models.ForeignKey("masters.Currency", on_delete=models.PROTECT, related_name="+")
    # LKR for one unit of the currency on the quotation date (1 for LKR); kept so the
    # quotation never changes when rates are updated later (rule 11).
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    rate_date = models.DateField(null=True, blank=True)
    payment_terms = models.CharField(max_length=200, blank=True)
    delivery_lead_time = models.CharField(max_length=100, blank=True)
    incoterm = models.CharField("Delivery term", max_length=3, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_lkr = models.DecimalField("Total (LKR)", max_digits=18, decimal_places=2, default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-quote_date", "-number", "-revision"]
        constraints = [
            models.UniqueConstraint(
                fields=["number", "revision"], name="sales_quotation_number_revision"
            ),
            models.CheckConstraint(
                condition=models.Q(valid_until__gte=models.F("quote_date")),
                name="sales_quotation_valid_after_date",
            ),
            models.CheckConstraint(
                condition=models.Q(exchange_rate__gt=0), name="sales_quotation_rate_positive"
            ),
        ]

    def __str__(self):
        return self.label

    @property
    def label(self) -> str:
        return f"{self.number} Rev {self.revision}"


class QuotationLine(models.Model):
    """A line offered to the customer. Drawings are files tagged with the line number."""

    is_structure = True

    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    description = models.TextField()
    drawing_no = models.CharField("Drawing no.", max_length=50, blank=True)
    drawing_rev = models.CharField("Drawing revision", max_length=20, blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    unit = models.CharField(max_length=20, default="pcs")
    min_order_qty = models.DecimalField(
        "Minimum order quantity", max_digits=18, decimal_places=3, null=True, blank=True
    )
    unit_price = models.DecimalField(max_digits=18, decimal_places=2)
    tax_code = models.ForeignKey(
        "accounting.TaxCode", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["quotation", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["quotation", "line_no"], name="sales_line_no_unique"),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0) & models.Q(unit_price__gte=0),
                name="sales_line_quantity_price",
            ),
        ]

    def __str__(self):
        return f"{self.quotation.number} line {self.line_no}"


class QuotationQtyBreak(models.Model):
    """The unit price for another quantity of the same line (e.g. 10, 50, 100 pieces)."""

    is_structure = True

    line = models.ForeignKey(QuotationLine, on_delete=models.CASCADE, related_name="breaks")
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    unit_price = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["line", "quantity"]
        constraints = [
            models.UniqueConstraint(fields=["line", "quantity"], name="sales_break_unique"),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0) & models.Q(unit_price__gte=0),
                name="sales_break_quantity_price",
            ),
        ]

    def __str__(self):
        return f"{self.quantity} @ {self.unit_price}"


class QuotationFile(models.Model):
    """The customer's drawing or another file, for one line (line_no) or the whole quotation.
    Its SHA-256 fingerprint reveals the same file uploaded twice."""

    quotation = models.ForeignKey(Quotation, on_delete=models.PROTECT, related_name="files")
    line_no = models.PositiveSmallIntegerField(null=True, blank=True)
    file = models.FileField(upload_to="quotations/%Y/%m/")
    file_name = models.CharField(max_length=200)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64, db_index=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["line_no", "uploaded_at", "id"]

    def __str__(self):
        return self.file_name
