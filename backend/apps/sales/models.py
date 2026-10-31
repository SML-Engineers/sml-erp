"""Sales documents (spec 5; Phase 1.5): quotations first (backlog P15-03).

A quotation is made for one customer and one production division, in the customer's
currency with the exchange rate of its date. Money is Decimal (rule 1); the number comes from
the number series in the saving transaction (rule 10). Revisions keep the number and count
up (Rev 0, Rev 1, ...; P15-06).
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class OutcomeReason(models.TextChoices):
    """Why a quotation was won or lost, for the sales reports (P15-06, P15-11)."""

    PRICE = "price", "Price"
    LEAD_TIME = "lead_time", "Delivery time"
    QUALITY = "quality", "Quality or specification"
    RELATIONSHIP = "relationship", "Customer relationship"
    COMPETITOR = "competitor", "Went to a competitor"
    CANCELLED = "cancelled", "Customer cancelled the need"
    NO_RESPONSE = "no_response", "No response from the customer"
    OTHER = "other", "Other"


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
    # A discount on every line, before taxes (owner, 31 Oct 2026; P15-07b). The subtotal is
    # after the discount.
    discount_pct = models.DecimalField("Discount %", max_digits=5, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_lkr = models.DecimalField("Total (LKR)", max_digits=18, decimal_places=2, default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    # Approval, sending and the outcome (P15-06). Who approved is in the approval log.
    approved_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    outcome_reason = models.CharField(
        "Why won or lost", max_length=30, choices=OutcomeReason.choices, blank=True
    )
    outcome_note = models.TextField(blank=True)
    outcome_at = models.DateTimeField(null=True, blank=True)
    outcome_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

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
            models.CheckConstraint(
                condition=models.Q(discount_pct__gte=0) & models.Q(discount_pct__lt=100),
                name="sales_quotation_discount_range",
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
    # The mould or other tooling, charged once rather than per piece (P15-05, spec 5.1).
    is_tooling = models.BooleanField("Tooling (charged once)", default=False)
    tax_code = models.ForeignKey(
        "accounting.TaxCode", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # Quantity × unit price; the quotation's discount on it; taxes on what is left.
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    discount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
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

    @property
    def net(self):
        """What the line is worth after the quotation's discount, before taxes."""
        return self.amount - self.discount


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


# --- Costing (P15-04, spec 5.1): internal only, never on the customer's copy -------------


class QuotationCosting(models.Model):
    """How a line's price is built up, in LKR (spec 5.5: costing stays in LKR).

    The rates used are copied here from the tables in force on the quotation's date, so a
    later change of rate never alters the costing (rule 11). The results (cost per piece,
    suggested price, margin of the price quoted) are worked out from these figures and the
    line's quantity (services.costing_results), for the line and for each quantity break.
    """

    class Method(models.TextChoices):
        MACHINING = "machining", "Machining"
        MOULDING = "moulding", "Moulding"

    class PackingPer(models.TextChoices):
        PIECE = "piece", "Per piece"
        CARTON = "carton", "Per carton"

    class Tooling(models.TextChoices):
        NONE = "none", "No tooling"
        SEPARATE = "separate", "Charged once, as its own line"
        AMORTISED = "amortised", "Spread over a quantity"
        CUSTOMER = "customer", "Owned by the customer"

    line = models.OneToOneField(QuotationLine, on_delete=models.CASCADE, related_name="costing")
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.MACHINING)
    rates_date = models.DateField()

    # Material: chosen from the rate table, its weight worked out from the stock size (bars,
    # plates, tubes) or entered directly.
    material = models.ForeignKey(
        "masters.Material", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    material_rate = models.DecimalField(
        "Material price per kg (LKR)", max_digits=18, decimal_places=2, null=True, blank=True
    )
    density = models.DecimalField(
        "Density (g/cm³)", max_digits=6, decimal_places=3, null=True, blank=True
    )
    form = models.CharField(max_length=20, blank=True)
    size_a_mm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    size_b_mm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    length_mm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cutting_allowance_mm = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    entered_weight_kg = models.DecimalField(
        "Weight per piece entered (kg)", max_digits=12, decimal_places=4, null=True, blank=True
    )
    weight_kg = models.DecimalField(
        "Weight per piece used (kg)", max_digits=12, decimal_places=4, default=0
    )

    setup_hours = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    setup_rate = models.DecimalField("Setup rate per hour (LKR)", max_digits=18, decimal_places=2)
    overhead_pct = models.DecimalField("Overhead %", max_digits=5, decimal_places=2)
    margin_pct = models.DecimalField("Margin %", max_digits=5, decimal_places=2)
    notes = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    updated_at = models.DateTimeField(default=timezone.now)

    # Moulding (P15-05): resin is `material` (its price in `material_rate`), plus masterbatch
    # as a % of the resin weight; one press with its hourly rate on the quotation's date.
    masterbatch = models.ForeignKey(
        "masters.Material", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    masterbatch_rate = models.DecimalField(
        "Masterbatch price per kg (LKR)", max_digits=18, decimal_places=2, null=True, blank=True
    )
    masterbatch_pct = models.DecimalField(
        "Masterbatch %", max_digits=5, decimal_places=2, default=0
    )
    part_weight_g = models.DecimalField(
        "Part weight (g)", max_digits=12, decimal_places=3, null=True, blank=True
    )
    runner_weight_g = models.DecimalField(
        "Runner weight per shot (g)", max_digits=12, decimal_places=3, null=True, blank=True
    )
    cavities = models.PositiveSmallIntegerField(null=True, blank=True)
    machine = models.ForeignKey(
        "masters.Machine", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    machine_rate = models.DecimalField(
        "Machine hourly rate (LKR)", max_digits=18, decimal_places=2, null=True, blank=True
    )
    cycle_time_s = models.DecimalField(
        "Cycle time (s)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    reject_pct = models.DecimalField("Reject %", max_digits=5, decimal_places=2, default=0)
    packing_amount = models.DecimalField(
        "Packing (LKR)", max_digits=18, decimal_places=2, default=0
    )
    packing_per = models.CharField(
        max_length=10, choices=PackingPer.choices, default=PackingPer.PIECE
    )
    pcs_per_carton = models.PositiveIntegerField("Pieces per carton", null=True, blank=True)
    tooling = models.CharField(max_length=10, choices=Tooling.choices, default=Tooling.NONE)
    tooling_cost = models.DecimalField(
        "Tooling cost (LKR)", max_digits=18, decimal_places=2, default=0
    )
    tooling_qty = models.DecimalField(
        "Tooling spread over (pieces)", max_digits=18, decimal_places=3, null=True, blank=True
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(masterbatch_pct__gte=0)
                & models.Q(reject_pct__gte=0)
                & models.Q(reject_pct__lt=100)
                & models.Q(packing_amount__gte=0)
                & models.Q(tooling_cost__gte=0),
                name="sales_costing_moulding_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(setup_hours__gte=0)
                & models.Q(setup_rate__gte=0)
                & models.Q(overhead_pct__gte=0)
                & models.Q(margin_pct__gte=0)
                & models.Q(weight_kg__gte=0)
                & models.Q(cutting_allowance_mm__gte=0),
                name="sales_costing_not_negative",
            ),
        ]

    def __str__(self):
        return f"Costing of {self.line}"


class QuotationCostingOperation(models.Model):
    """One machining operation: a machine, its minutes per piece and its hourly rate on the
    quotation's date."""

    costing = models.ForeignKey(
        QuotationCosting, on_delete=models.CASCADE, related_name="operations"
    )
    seq = models.PositiveSmallIntegerField()
    machine = models.ForeignKey("masters.Machine", on_delete=models.PROTECT, related_name="+")
    description = models.CharField(max_length=100, blank=True)
    minutes = models.DecimalField("Minutes per piece", max_digits=10, decimal_places=3)
    rate = models.DecimalField("Hourly rate (LKR)", max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["costing", "seq"]
        constraints = [
            models.UniqueConstraint(fields=["costing", "seq"], name="sales_costing_op_seq"),
            models.CheckConstraint(
                condition=models.Q(minutes__gt=0) & models.Q(rate__gte=0),
                name="sales_costing_op_positive",
            ),
        ]

    def __str__(self):
        return f"{self.seq}. {self.machine_id} {self.minutes} min"


class QuotationCostingExtra(models.Model):
    """Subcontract work and other bought-in costs: heat treatment, plating, transport. An
    amount per piece, or for the whole order (then shared over the quantity)."""

    costing = models.ForeignKey(QuotationCosting, on_delete=models.CASCADE, related_name="extras")
    seq = models.PositiveSmallIntegerField()
    description = models.CharField(max_length=100)
    amount = models.DecimalField("Amount (LKR)", max_digits=18, decimal_places=2)
    per_order = models.BooleanField(default=False)

    class Meta:
        ordering = ["costing", "seq"]
        constraints = [
            models.UniqueConstraint(fields=["costing", "seq"], name="sales_costing_extra_seq"),
            models.CheckConstraint(
                condition=models.Q(amount__gte=0), name="sales_costing_extra_amount"
            ),
        ]

    def __str__(self):
        return f"{self.description} {self.amount}"


# --- Customer advances (P15-09, spec 5.2) -----------------------------------------------


class CustomerAdvance(models.Model):
    """Money received from a customer before the goods are invoiced: recorded by the Cashier,
    approved by the Accountant (owner, 31 Oct 2026), then posted Dr Bank, Cr Customer
    advances (a liability). It waits for set-off against the tax invoice (Phase 2).

    Received in the account's currency; the LKR value uses the rate of the receipt date and
    is what the ledger carries (rule 11)."""

    class Status(models.TextChoices):
        AWAITING_APPROVAL = "awaiting_approval", "Awaiting approval"
        APPROVED = "approved", "Approved and posted"
        REJECTED = "rejected", "Rejected"

    class Method(models.TextChoices):
        TRANSFER = "transfer", "Bank transfer"
        CHEQUE = "cheque", "Cheque"
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        QR = "qr", "QR (LankaQR)"

    number = models.CharField(max_length=30, unique=True)
    customer = models.ForeignKey(
        "masters.Customer", on_delete=models.PROTECT, related_name="advances"
    )
    quotation = models.ForeignKey(
        Quotation, null=True, blank=True, on_delete=models.PROTECT, related_name="advances"
    )
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    receipt_date = models.DateField()
    account = models.ForeignKey(
        "masters.CompanyAccount", on_delete=models.PROTECT, related_name="customer_advances"
    )
    method = models.CharField(max_length=10, choices=Method.choices)
    reference = models.CharField(max_length=50, blank=True)
    currency = models.ForeignKey("masters.Currency", on_delete=models.PROTECT, related_name="+")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    rate_date = models.DateField(null=True, blank=True)
    amount_lkr = models.DecimalField("Amount (LKR)", max_digits=18, decimal_places=2)
    # Taken off a tax invoice in Phase 2; what is left is still owed to the customer.
    set_off_lkr = models.DecimalField("Set off (LKR)", max_digits=18, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.AWAITING_APPROVAL
    )
    journal_entry = models.OneToOneField(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="customer_advance",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-receipt_date", "-number"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0)
                & models.Q(amount_lkr__gt=0)
                & models.Q(exchange_rate__gt=0)
                & models.Q(set_off_lkr__gte=0)
                & models.Q(set_off_lkr__lte=models.F("amount_lkr")),
                name="sales_advance_amounts",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="approved") | models.Q(journal_entry__isnull=False),
                name="sales_advance_posted_when_approved",
            ),
        ]

    def __str__(self):
        return self.number
