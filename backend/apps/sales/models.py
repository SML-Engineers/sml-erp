"""Sales documents (spec 5; Phase 1.5): quotations first (backlog P15-03).

A quotation is made for one customer and one production division, in the customer's
currency with the exchange rate of its date. Money is Decimal (rule 1); the number comes from
the number series in the saving transaction (rule 10). Revisions keep the number and count
up (Rev 0, Rev 1, ...; P15-06).
"""

from decimal import ROUND_HALF_UP, Decimal

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


class QuotationImage(models.Model):
    """A picture of the product for the customer (owner's request, 4 Nov 2026): at most three
    per quotation, JPG or PNG of at most 1 MB each. Added by the person who makes the
    quotation while it is a draft, seen by the approver and emailed with the quotation. It
    changes only while the quotation is a draft (database guard)."""

    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="images")
    file = models.FileField(upload_to="quotation-images/%Y/%m/")
    file_name = models.CharField(max_length=200)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["uploaded_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(size__gt=0) & models.Q(size__lte=1024 * 1024),
                name="sales_quotationimage_size",
            ),
        ]

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
    proforma = models.ForeignKey(
        "ProformaInvoice",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="advances",
    )
    sales_order = models.ForeignKey(
        "SalesOrder",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="advances",
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


# --- Proforma invoices and packing list (P15-08, spec 5.2, 5.5) ---------------------------


class ProformaInvoice(models.Model):
    """A proforma made from an accepted quotation, with its prices and terms carried over:
    for the customer's advance payment, import, LC or bank documents. It records no sale and
    no receivable: nothing is posted (spec 5.2). Numbered PI{YY}{MM}{DD}-{XX} (owner, 31 Oct
    2026). A packing list (cartons, weights, carton sizes) prints as its own page."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=30, unique=True)
    quotation = models.ForeignKey(Quotation, on_delete=models.PROTECT, related_name="proformas")
    customer = models.ForeignKey(
        "masters.Customer", on_delete=models.PROTECT, related_name="proformas"
    )
    contact = models.ForeignKey(
        "masters.CustomerContact", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    issue_date = models.DateField()
    currency = models.ForeignKey("masters.Currency", on_delete=models.PROTECT, related_name="+")
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    rate_date = models.DateField(null=True, blank=True)
    customer_po = models.CharField("Customer's PO no.", max_length=50, blank=True)
    payment_terms = models.CharField(max_length=200, blank=True)
    delivery_lead_time = models.CharField(max_length=100, blank=True)
    incoterm = models.CharField("Delivery term", max_length=3, blank=True)
    port_of_loading = models.CharField(max_length=100, blank=True)
    port_of_destination = models.CharField(max_length=100, blank=True)
    # Where the customer pays the advance: printed with its bank details.
    bank_account = models.ForeignKey(
        "masters.CompanyAccount", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    advance_pct = models.DecimalField("Advance %", max_digits=5, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    discount_pct = models.DecimalField("Discount %", max_digits=5, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_lkr = models.DecimalField("Total (LKR)", max_digits=18, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    cancel_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    issued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-issue_date", "-number"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(exchange_rate__gt=0)
                & models.Q(advance_pct__gte=0)
                & models.Q(advance_pct__lte=100)
                & models.Q(discount_pct__gte=0)
                & models.Q(discount_pct__lt=100),
                name="sales_proforma_figures",
            ),
        ]

    def __str__(self):
        return self.number

    @property
    def advance_amount(self):
        """The advance asked for, in the proforma's currency."""
        return (self.total_amount * self.advance_pct / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)


class ProformaLine(models.Model):
    """A line of the proforma, from a quotation line at the quotation's price for the
    quantity (the quantity break that applies), with its packing."""

    is_structure = True

    proforma = models.ForeignKey(ProformaInvoice, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    quotation_line = models.ForeignKey(
        QuotationLine, on_delete=models.PROTECT, related_name="proforma_lines"
    )
    description = models.TextField()
    drawing_no = models.CharField(max_length=50, blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    unit = models.CharField(max_length=20, default="pcs")
    unit_price = models.DecimalField(max_digits=18, decimal_places=2)
    is_tooling = models.BooleanField(default=False)
    tax_code = models.ForeignKey(
        "accounting.TaxCode", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    discount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2)
    # Packing list (owner, 31 Oct 2026): cartons, quantity per carton, net and gross weight
    # of the line, and the size of one carton.
    cartons = models.PositiveIntegerField(null=True, blank=True)
    qty_per_carton = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)
    net_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    gross_weight_kg = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    carton_length_cm = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    carton_width_cm = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)
    carton_height_cm = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)

    class Meta:
        ordering = ["proforma", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["proforma", "line_no"], name="sales_proforma_line_no"),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0) & models.Q(unit_price__gte=0),
                name="sales_proforma_line_figures",
            ),
        ]

    def __str__(self):
        return f"{self.proforma.number} line {self.line_no}"

    @property
    def net(self):
        return self.amount - self.discount


# --- Sales orders (P15-10, spec 5.3) -----------------------------------------------------


class SalesOrder(models.Model):
    """The customer's confirmed order: made from an accepted quotation or an issued proforma
    (prices carried over), or entered directly for a repeat order (then approved by the
    Director before it is confirmed). Holds the customer's PO number and a delivery schedule
    per line (several dates and quantities for moulding call-offs). In Phase 3 a line makes
    a job order or a moulding production requirement; in Phase 2 deliveries and invoices."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING_APPROVAL = "awaiting_approval", "Awaiting approval"
        OPEN = "open", "Open"
        PARTLY_DELIVERED = "partly_delivered", "Partly delivered"
        DELIVERED = "delivered", "Delivered"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class Source(models.TextChoices):
        QUOTATION = "quotation", "Quotation"
        PROFORMA = "proforma", "Proforma invoice"
        DIRECT = "direct", "Repeat order, entered directly"

    number = models.CharField(max_length=30, unique=True)
    source = models.CharField(max_length=10, choices=Source.choices)
    quotation = models.ForeignKey(
        Quotation, null=True, blank=True, on_delete=models.PROTECT, related_name="sales_orders"
    )
    proforma = models.ForeignKey(
        ProformaInvoice,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sales_orders",
    )
    customer = models.ForeignKey(
        "masters.Customer", on_delete=models.PROTECT, related_name="sales_orders"
    )
    contact = models.ForeignKey(
        "masters.CustomerContact", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    order_date = models.DateField()
    customer_po = models.CharField("Customer's PO no.", max_length=50, blank=True)
    po_date = models.DateField("Customer's PO date", null=True, blank=True)
    currency = models.ForeignKey("masters.Currency", on_delete=models.PROTECT, related_name="+")
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    rate_date = models.DateField(null=True, blank=True)
    payment_terms = models.CharField(max_length=200, blank=True)
    incoterm = models.CharField("Delivery term", max_length=3, blank=True)
    delivery_address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    discount_pct = models.DecimalField("Discount %", max_digits=5, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_lkr = models.DecimalField("Total (LKR)", max_digits=18, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    cancel_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-order_date", "-number"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(exchange_rate__gt=0)
                & models.Q(discount_pct__gte=0)
                & models.Q(discount_pct__lt=100),
                name="sales_order_figures",
            ),
        ]

    def __str__(self):
        return self.number


class SalesOrderLine(models.Model):
    is_structure = True

    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    quotation_line = models.ForeignKey(
        QuotationLine,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sales_order_lines",
    )
    description = models.TextField()
    drawing_no = models.CharField(max_length=50, blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    unit = models.CharField(max_length=20, default="pcs")
    unit_price = models.DecimalField(max_digits=18, decimal_places=2)
    is_tooling = models.BooleanField(default=False)
    tax_code = models.ForeignKey(
        "accounting.TaxCode", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    discount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["order", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["order", "line_no"], name="sales_order_line_no"),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0) & models.Q(unit_price__gte=0),
                name="sales_order_line_figures",
            ),
        ]

    def __str__(self):
        return f"{self.order.number} line {self.line_no}"

    @property
    def net(self):
        return self.amount - self.discount


class DeliverySchedule(models.Model):
    """When a line is to be delivered: one date for the whole quantity, or several (moulding
    call-offs). The quantities add up to the line's quantity."""

    is_structure = True

    line = models.ForeignKey(SalesOrderLine, on_delete=models.CASCADE, related_name="schedule")
    seq = models.PositiveSmallIntegerField()
    due_date = models.DateField()
    quantity = models.DecimalField(max_digits=18, decimal_places=3)

    class Meta:
        ordering = ["line", "due_date", "seq"]
        constraints = [
            models.UniqueConstraint(fields=["line", "seq"], name="sales_schedule_seq"),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="sales_schedule_quantity"
            ),
        ]

    def __str__(self):
        return f"{self.quantity} by {self.due_date}"


# --- Delivery notes (P2-04, spec 5.3 and 6) --------------------------------------------------


class DeliveryNote(models.Model):
    """What leaves the factory against an open sales order: the quantity of each order line
    delivered now, the vehicle and driver; printed for the customer to sign. Issuing it
    moves the order to Partly delivered or Delivered. Until finished-goods stock exists
    (Phase 3, owner's question 4), a delivery note records what was delivered and posts
    nothing. The signed copy is kept with it when it comes back."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"
        RECEIVED = "received", "Signed by the customer"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=30, unique=True)
    order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="deliveries")
    delivery_date = models.DateField()
    vehicle_no = models.CharField("Vehicle no.", max_length=30, blank=True)
    driver = models.CharField(max_length=100, blank=True)
    delivery_address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    issued_at = models.DateTimeField(null=True, blank=True)
    received_by = models.CharField("Received by (name)", max_length=100, blank=True)
    received_on = models.DateField(null=True, blank=True)
    signed_copy = models.FileField(upload_to="delivery-notes/%Y/%m/", blank=True)
    signed_copy_name = models.CharField(max_length=200, blank=True)
    signed_copy_type = models.CharField(max_length=100, blank=True)
    signed_copy_sha256 = models.CharField(max_length=64, blank=True)
    cancel_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-delivery_date", "-number"]

    def __str__(self):
        return self.number


class DeliveryNoteLine(models.Model):
    note = models.ForeignKey(DeliveryNote, on_delete=models.CASCADE, related_name="lines")
    order_line = models.ForeignKey(
        SalesOrderLine, on_delete=models.PROTECT, related_name="delivered"
    )
    quantity = models.DecimalField(max_digits=18, decimal_places=3)

    class Meta:
        ordering = ["note", "order_line__line_no"]
        constraints = [
            models.UniqueConstraint(fields=["note", "order_line"], name="sales_dn_line_once"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sales_dn_line_qty"),
        ]

    def __str__(self):
        return f"{self.note.number}: {self.quantity}"


# --- Tax invoices (P2-05, spec 6.1) ----------------------------------------------------------


class SalesAccount(models.Model):
    """The income account a division's invoice lines are credited to: one for goods and
    services, one for tooling (moulds charged once). Kept by the Accountant."""

    is_structure = True

    division = models.OneToOneField(
        "core.Division", on_delete=models.PROTECT, related_name="sales_account"
    )
    account = models.ForeignKey("accounting.Account", on_delete=models.PROTECT, related_name="+")
    tooling_account = models.ForeignKey(
        "accounting.Account", on_delete=models.PROTECT, related_name="+"
    )

    def __str__(self):
        return f"{self.division.code}: {self.account}"


class TaxInvoice(models.Model):
    """The tax invoice in the Inland Revenue's format (Gazette 2481/22): made from delivered
    quantities of one sales order, numbered YYMMM_QQQQ_XX per division when issued, and then
    never changed or deleted (a credit note corrects it, P2-06). Issuing posts Dr Accounts
    receivable (the customer), Cr Sales per division, Cr each tax's payable account.

    The supplier's and the customer's details are copied onto the invoice when it is issued,
    so a later change of address or TIN does not change an issued invoice."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"

    number = models.CharField(max_length=40, blank=True)  # given when issued
    order = models.ForeignKey(SalesOrder, on_delete=models.PROTECT, related_name="invoices")
    customer = models.ForeignKey(
        "masters.Customer", on_delete=models.PROTECT, related_name="tax_invoices"
    )
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    invoice_date = models.DateField()
    supply_date = models.DateField()
    due_date = models.DateField()
    place_of_supply = models.CharField(max_length=200, blank=True)
    terms = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    # Copied when issued (as printed).
    supplier_name = models.CharField(max_length=200, blank=True)
    supplier_tin = models.CharField(max_length=50, blank=True)
    supplier_address = models.TextField(blank=True)
    supplier_phone = models.CharField(max_length=50, blank=True)
    supplier_email = models.CharField(max_length=254, blank=True)
    customer_name = models.CharField(max_length=200, blank=True)
    customer_tin = models.CharField(max_length=50, blank=True)
    customer_address = models.TextField(blank=True)
    customer_po = models.CharField(max_length=50, blank=True)
    # In the order's (the customer's) currency (P2-09), at the rate of the invoice date; the
    # ledger carries the LKR value (rule 11).
    currency = models.ForeignKey("masters.Currency", on_delete=models.PROTECT, related_name="+")
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    rate_date = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    # What the receivable is booked at in LKR (the sum of the converted sales and taxes).
    total_lkr = models.DecimalField("Total (LKR)", max_digits=18, decimal_places=2, default=0)
    amount_in_words = models.CharField(max_length=400, blank=True)
    journal_entry = models.OneToOneField(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="tax_invoice",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    issued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-invoice_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["number"],
                condition=~models.Q(number=""),
                name="sales_invoice_number_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(status="draft") | ~models.Q(number=""),
                name="sales_invoice_issued_numbered",
            ),
        ]

    def __str__(self):
        return self.number or f"Draft invoice {self.pk}"


class TaxInvoiceLine(models.Model):
    """One delivered line: each delivery note line is invoiced once."""

    invoice = models.ForeignKey(TaxInvoice, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    delivery_line = models.OneToOneField(
        DeliveryNoteLine, on_delete=models.PROTECT, related_name="invoice_line"
    )
    product_code = models.CharField(max_length=50, blank=True)
    description = models.TextField()
    po_no = models.CharField(max_length=50, blank=True)
    unit = models.CharField(max_length=20, default="pcs")
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    rate = models.DecimalField(max_digits=18, decimal_places=2)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    discount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_code = models.ForeignKey(
        "accounting.TaxCode", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    account = models.ForeignKey("accounting.Account", on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["invoice", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["invoice", "line_no"], name="sales_invoice_line_no"),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0) & models.Q(rate__gte=0),
                name="sales_invoice_line_figures",
            ),
        ]

    def __str__(self):
        return f"{self.invoice} line {self.line_no}"

    @property
    def net(self):
        return self.amount - self.discount


class TaxInvoiceTax(models.Model):
    """The invoice's taxes by component and rate, as printed: those on the net amount (SSCL)
    before the subtotal, those on net plus tax (VAT) after it."""

    invoice = models.ForeignKey(TaxInvoice, on_delete=models.CASCADE, related_name="taxes")
    seq = models.PositiveSmallIntegerField()
    component = models.ForeignKey(
        "accounting.TaxComponent", on_delete=models.PROTECT, related_name="+"
    )
    label = models.CharField(max_length=20)
    rate = models.DecimalField(max_digits=7, decimal_places=4)
    on_tax = models.BooleanField(default=False)
    amount = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["invoice", "seq"]

    def __str__(self):
        return f"{self.label} {self.rate}%"


# --- Credit notes (P2-06) --------------------------------------------------------------------


class CreditNote(models.Model):
    """A correction of an issued tax invoice: goods returned, a price corrected, or another
    reason. It credits part or all of the invoice's lines, never more than is left of them
    after earlier credit notes, with the taxes worked out at the invoice's rates. Approved
    through the approval engine ("credit_note": the Director, or a person given the right);
    approval numbers it and posts the reverse of the invoice: Dr Sales, Dr SSCL and VAT
    payable, Cr Accounts receivable (the customer). Approved notes never change."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING_APPROVAL = "awaiting_approval", "Waiting for approval"
        APPROVED = "approved", "Approved and posted"
        REJECTED = "rejected", "Rejected"

    class Kind(models.TextChoices):
        RETURN = "return", "Goods returned"
        PRICE = "price", "Price correction"
        OTHER = "other", "Other"

    number = models.CharField(max_length=40, blank=True)  # given when approved
    invoice = models.ForeignKey(TaxInvoice, on_delete=models.PROTECT, related_name="credit_notes")
    customer = models.ForeignKey(
        "masters.Customer", on_delete=models.PROTECT, related_name="credit_notes"
    )
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    reason = models.TextField()
    credit_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    # The receivable it takes off, in LKR at the invoice's rate (P2-09).
    total_lkr = models.DecimalField("Total (LKR)", max_digits=18, decimal_places=2, default=0)
    amount_in_words = models.CharField(max_length=400, blank=True)
    journal_entry = models.OneToOneField(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credit_note",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-credit_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["number"],
                condition=~models.Q(number=""),
                name="sales_credit_number_unique",
            ),
        ]

    def __str__(self):
        return self.number or f"Draft credit note {self.pk}"


class CreditNoteLine(models.Model):
    """The part of one invoice line credited: the quantity returned (for returned goods) and
    the amount before tax."""

    note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="lines")
    invoice_line = models.ForeignKey(
        TaxInvoiceLine, on_delete=models.PROTECT, related_name="credits"
    )
    quantity = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        ordering = ["note", "invoice_line__line_no"]
        constraints = [
            models.UniqueConstraint(fields=["note", "invoice_line"], name="sales_cn_line_once"),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0) & models.Q(quantity__gte=0),
                name="sales_cn_line_figures",
            ),
        ]

    def __str__(self):
        return f"{self.note}: {self.amount}"


class CreditNoteTax(models.Model):
    note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="taxes")
    seq = models.PositiveSmallIntegerField()
    component = models.ForeignKey(
        "accounting.TaxComponent", on_delete=models.PROTECT, related_name="+"
    )
    label = models.CharField(max_length=20)
    rate = models.DecimalField(max_digits=7, decimal_places=4)
    on_tax = models.BooleanField(default=False)
    amount = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["note", "seq"]

    def __str__(self):
        return f"{self.label} {self.rate}%"


# --- Customer receipts and advance set-off (P2-07) -----------------------------------------


class CustomerReceipt(models.Model):
    """Money received from a customer for issued tax invoices: recorded by the Cashier,
    split across one or more of the customer's invoices (never more than is open on each),
    and approved by the Accountant. Approval posts Dr the bank or cash account (Undeposited
    funds for a cheque, until it is deposited, P2-14), Cr Accounts receivable (the customer)
    per invoice. A post-dated cheque waits: it is posted on its date. In LKR (export invoices
    in other currencies come with P2-09). Numbered from the receipts series (RC…), shared with
    customer advances."""

    class Status(models.TextChoices):
        AWAITING_APPROVAL = "awaiting_approval", "Awaiting approval"
        POST_DATED = "post_dated", "Approved, cheque not yet due"
        POSTED = "posted", "Approved and posted"
        REJECTED = "rejected", "Rejected"
        # The customer's cheque came back unpaid (P2-14): the receipt is reversed and the
        # invoices are open again.
        RETURNED = "returned", "Cheque returned"

    Method = CustomerAdvance.Method

    number = models.CharField(max_length=30, unique=True)
    customer = models.ForeignKey(
        "masters.Customer", on_delete=models.PROTECT, related_name="receipts"
    )
    receipt_date = models.DateField()
    method = models.CharField(max_length=10, choices=Method.choices)
    # The bank or cash account; none for a cheque, which waits in Undeposited funds.
    account = models.ForeignKey(
        "masters.CompanyAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="customer_receipts",
    )
    reference = models.CharField(max_length=50, blank=True)
    cheque_date = models.DateField(null=True, blank=True)
    cheque_bank = models.CharField(max_length=100, blank=True)
    # In the invoices' currency (P2-09), at the rate of the receipt date.
    currency = models.ForeignKey("masters.Currency", on_delete=models.PROTECT, related_name="+")
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, default=1)
    rate_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    amount_lkr = models.DecimalField("Amount (LKR)", max_digits=18, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.AWAITING_APPROVAL
    )
    journal_entry = models.OneToOneField(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="customer_receipt",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    # A returned cheque (P2-14): when, why, and the entry that put the money back on the
    # customer's account.
    returned_on = models.DateField(null=True, blank=True)
    return_reason = models.TextField(blank=True)
    return_entry = models.OneToOneField(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="returned_receipt",
    )

    class Meta:
        ordering = ["-receipt_date", "-number"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="sales_receipt_amount"),
            models.CheckConstraint(
                condition=models.Q(method="cheque", cheque_date__isnull=False)
                | (~models.Q(method="cheque") & models.Q(account__isnull=False)),
                name="sales_receipt_account_or_cheque",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="posted") | models.Q(journal_entry__isnull=False),
                name="sales_receipt_posted_has_entry",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="returned")
                | models.Q(
                    method="cheque",
                    journal_entry__isnull=False,
                    return_entry__isnull=False,
                    returned_on__isnull=False,
                ),
                name="sales_receipt_returned_cheque",
            ),
        ]

    def __str__(self):
        return self.number


class ReceiptAllocation(models.Model):
    """The part of a receipt paid towards one tax invoice."""

    receipt = models.ForeignKey(
        CustomerReceipt, on_delete=models.PROTECT, related_name="allocations"
    )
    invoice = models.ForeignKey(
        TaxInvoice, on_delete=models.PROTECT, related_name="receipt_allocations"
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)  # the invoice's currency
    # The receivable it takes off, in LKR at the invoice's rate (P2-09).
    carrying_lkr = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        ordering = ["receipt", "id"]
        constraints = [
            models.UniqueConstraint(fields=["receipt", "invoice"], name="sales_allocation_once"),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="sales_allocation_amount"
            ),
        ]

    def __str__(self):
        return f"{self.receipt}: {self.invoice} {self.amount}"


class AdvanceSetOff(models.Model):
    """Part of an approved customer advance taken off a tax invoice: Dr Customer advances,
    Cr Accounts receivable (the customer). Made automatically when an invoice of the
    advance's order is issued, or by the Accountant. Never changed (database guard); the
    advance's "set off" total is kept by the database."""

    advance = models.ForeignKey(CustomerAdvance, on_delete=models.PROTECT, related_name="set_offs")
    invoice = models.ForeignKey(TaxInvoice, on_delete=models.PROTECT, related_name="set_offs")
    amount = models.DecimalField(max_digits=18, decimal_places=2)  # in both documents' currency
    # In LKR: what leaves Customer advances (at the advance's rate) and what leaves the
    # receivable (at the invoice's rate); any difference is an exchange gain or loss (P2-09).
    amount_lkr = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    carrying_lkr = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    set_off_date = models.DateField()
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry", on_delete=models.PROTECT, related_name="advance_set_offs"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["set_off_date", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="sales_set_off_amount"),
        ]

    def __str__(self):
        return f"{self.advance} -> {self.invoice}: {self.amount}"


# --- Credit control and payment reminders (P2-08) ------------------------------------------


class CreditHold(models.Model):
    """A sales order or tax invoice stopped because its customer is over the credit limit or
    has overdue invoices (owner, 3 Nov 2026: block). It waits until the Director allows that
    one document, with a note. Allowed holds never change and no hold is deleted (database
    guard), so every release is on record."""

    class Kind(models.TextChoices):
        SALES_ORDER = "sales_order", "Sales order"
        TAX_INVOICE = "tax_invoice", "Tax invoice"

    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting for the Director"
        ALLOWED = "allowed", "Allowed by the Director"

    document_type = models.CharField(max_length=20, choices=Kind.choices)
    document_id = models.BigIntegerField()
    document_label = models.CharField(max_length=100)
    customer = models.ForeignKey(
        "masters.Customer", on_delete=models.PROTECT, related_name="credit_holds"
    )
    # The figures when it was stopped (LKR).
    amount_lkr = models.DecimalField(max_digits=18, decimal_places=2)
    exposure_lkr = models.DecimalField(max_digits=18, decimal_places=2)
    credit_limit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    overdue_lkr = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    reasons = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.WAITING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    requested_at = models.DateTimeField(default=timezone.now)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status="waiting")
                | (models.Q(decided_by__isnull=False) & models.Q(decided_at__isnull=False)),
                name="sales_credit_hold_decided",
            ),
        ]

    def __str__(self):
        return f"{self.document_label}: {self.get_status_display()}"


class ReminderPlan(models.Model):
    """Automatic payment reminders for one customer: when switched on, the customer's
    statement is emailed from the finance mailbox every `every_days` days while it has
    overdue invoices, and stops once they are paid. The emails go in the name of the person
    who switched them on."""

    customer = models.OneToOneField(
        "masters.Customer", on_delete=models.PROTECT, related_name="reminder_plan"
    )
    is_on = models.BooleanField(default=False)
    every_days = models.PositiveSmallIntegerField(default=7)
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(every_days__gte=1) & models.Q(every_days__lte=90),
                name="sales_reminder_every_days",
            ),
        ]

    def __str__(self):
        return f"Reminders for {self.customer}"


class ReminderSent(models.Model):
    """One automatic reminder, sent or attempted (the email itself is in the sent emails).
    Insert-only (database guard)."""

    customer = models.ForeignKey(
        "masters.Customer", on_delete=models.PROTECT, related_name="reminders_sent"
    )
    email = models.OneToOneField("core.SentEmail", on_delete=models.PROTECT, related_name="+")
    amount_due_lkr = models.DecimalField(max_digits=18, decimal_places=2)
    overdue_lkr = models.DecimalField(max_digits=18, decimal_places=2)
    sent_on = models.DateField()

    class Meta:
        ordering = ["-sent_on", "-id"]

    def __str__(self):
        return f"Reminder to {self.customer} on {self.sent_on}"


# --- Invoice tracking (backlog P2-27) ----------------------------------------------------------


class InvoiceLink(models.Model):
    """The secret link to an issued tax invoice sent to the customer by email: a page showing
    the invoice, its PDF and the bank transfer details, with no sign-in. Opening it is
    recorded as "viewed"."""

    invoice = models.OneToOneField(TaxInvoice, on_delete=models.PROTECT, related_name="link")
    token = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Link to {self.invoice_id}"


class InvoiceView(models.Model):
    """The customer opened the invoice's link (the page or its PDF). Insert-only (database)."""

    class What(models.TextChoices):
        PAGE = "page", "Opened the invoice page"
        PDF = "pdf", "Downloaded the PDF"

    invoice = models.ForeignKey(TaxInvoice, on_delete=models.PROTECT, related_name="views")
    what = models.CharField(max_length=10, choices=What.choices)
    viewed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["viewed_at", "id"]

    def __str__(self):
        return f"{self.invoice_id} {self.what} {self.viewed_at:%Y-%m-%d %H:%M}"


class CardPaymentLink(models.Model):
    """A OnePay card payment link SML sent the customer for an invoice (owner, 3 Nov 2026: no
    gateway account; links are made in OnePay and sent by hand). Recorded for the invoice's
    history; the money is recorded as a card receipt when it arrives. Insert-only (database)."""

    invoice = models.ForeignKey(TaxInvoice, on_delete=models.PROTECT, related_name="card_links")
    url = models.URLField(max_length=500)
    amount = models.DecimalField(max_digits=18, decimal_places=2)  # in the invoice's currency
    sent_on = models.DateField()
    note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["sent_on", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="sales_cardlink_amount_positive"
            ),
        ]

    def __str__(self):
        return f"OnePay link {self.amount} for {self.invoice_id}"
