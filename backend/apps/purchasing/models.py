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


def qty_field(**extra):
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
    quantity = qty_field()
    unit_price = money()
    amount = money()
    tax_code = models.ForeignKey(
        "accounting.TaxCode", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    tax_amount = money(default=0)
    total = money()
    # Filled by goods receipts (P16-06); never typed.
    received_quantity = qty_field(default=0)

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


class SupplierInvoice(models.Model):
    """A supplier's invoice for goods received on purchase orders (backlog P16-10, spec 5A.4),
    entered by Accounts with its scan and matched three ways: each line against the GRN line
    it bills (accepted and not yet invoiced) and the PO (price and tax). No tolerance (owner,
    31 Oct 2026): any difference holds the invoice until the Director approves the exception.
    Posting clears Goods received not invoiced into Accounts payable. A posted or cancelled
    invoice never changes (database guard)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        HELD = "held", "Held: discrepancy"
        EXCEPTION_REQUESTED = "exception_requested", "Exception waiting for the Director"
        POSTED = "posted", "Matched and posted"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=30, unique=True)
    supplier = models.ForeignKey("masters.Supplier", on_delete=models.PROTECT, related_name="+")
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    invoice_no = models.CharField(max_length=50)  # the supplier's own number
    invoice_date = models.DateField()
    due_date = models.DateField()
    currency = models.ForeignKey("masters.Currency", on_delete=models.PROTECT, related_name="+")
    stated_total = money(null=True, blank=True)  # as printed on the invoice
    subtotal = money(default=0)
    tax_total = money(default=0)
    total_amount = money(default=0)
    total_lkr = money(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    discrepancies = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    exception_reason = models.TextField(blank=True)
    cancel_reason = models.TextField(blank=True)
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-invoice_date", "-number"]

    def __str__(self):
        return f"{self.number} ({self.invoice_no})"


class SupplierInvoiceLine(models.Model):
    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    grn_line = models.ForeignKey(
        "inventory.GoodsReceiptLine", on_delete=models.PROTECT, related_name="invoice_lines"
    )
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="+")
    quantity = qty_field()
    unit_price = money()  # as on the invoice
    tax_code = models.ForeignKey(
        "accounting.TaxCode", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    amount = money(default=0)
    tax_amount = money(default=0)
    total = money(default=0)
    # The PO's price and tax code the line was matched against.
    po_unit_price = money(default=0)
    po_tax_code = models.ForeignKey(
        "accounting.TaxCode", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["invoice", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["invoice", "line_no"], name="purchasing_si_line_no"),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="purchasing_si_line_quantity"
            ),
        ]

    def __str__(self):
        return f"{self.invoice} line {self.line_no}"


class SupplierInvoiceAttachment(models.Model):
    """The scanned invoice (PDF, JPG or PNG)."""

    invoice = models.ForeignKey(
        SupplierInvoice, on_delete=models.PROTECT, related_name="attachments"
    )
    file = models.FileField(upload_to="supplier-invoices/%Y/%m/")
    file_name = models.CharField(max_length=200)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    uploaded_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.file_name


class AdvanceSetOff(models.Model):
    """A paid advance on a PO set off against the supplier's invoice (backlog P16-11a):
    Dr Accounts payable, Cr Advances to suppliers. Never changed or deleted (database
    guard)."""

    invoice = models.ForeignKey(SupplierInvoice, on_delete=models.PROTECT, related_name="set_offs")
    voucher_line = models.ForeignKey(
        "vouchers.VoucherLine", on_delete=models.PROTECT, related_name="set_offs"
    )
    amount = money()
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry", on_delete=models.PROTECT, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="purchasing_setoff_amount"
            )
        ]

    def __str__(self):
        return f"{self.amount} of {self.voucher_line_id} against {self.invoice}"


class SupplierReturn(models.Model):
    """Goods sent back to the supplier (backlog P16-12), from one GRN, lot by lot:
    - rejected or damaged goods from the rejected store (no value; nothing to post), or
    - goods QC had accepted, from the main store, approved by the Director: their value
      leaves stock against Goods received not invoiced, or, for goods already invoiced,
      against the supplier with a debit note.
    Either way the PO expects the goods again. A confirmed return never changes."""

    class Kind(models.TextChoices):
        REJECTED = "rejected", "Rejected or damaged goods"
        ACCEPTED = "accepted", "Goods QC had accepted"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING_APPROVAL = "awaiting_approval", "Waiting for the Director"
        CONFIRMED = "confirmed", "Returned"

    number = models.CharField(max_length=30, unique=True)
    receipt = models.ForeignKey(
        "inventory.GoodsReceipt", on_delete=models.PROTECT, related_name="returns"
    )
    supplier = models.ForeignKey("masters.Supplier", on_delete=models.PROTECT, related_name="+")
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    return_date = models.DateField()
    reason = models.TextField()
    vehicle_no = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-return_date", "-number"]

    def __str__(self):
        return self.number


class SupplierReturnLine(models.Model):
    supplier_return = models.ForeignKey(
        SupplierReturn, on_delete=models.CASCADE, related_name="lines"
    )
    line_no = models.PositiveSmallIntegerField()
    grn_line = models.ForeignKey(
        "inventory.GoodsReceiptLine", on_delete=models.PROTECT, related_name="return_lines"
    )
    lot_no = models.CharField(max_length=40)
    quantity = qty_field()
    # For goods QC had accepted: the part not yet invoiced (against GRNI) and the part
    # already invoiced (on the debit note), worked out when the return is confirmed.
    uninvoiced_quantity = qty_field(default=0)
    invoiced_quantity = qty_field(default=0)
    value = money(default=0)  # the stock value that left, LKR

    class Meta:
        ordering = ["supplier_return", "line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["supplier_return", "line_no"], name="purchasing_return_line_no"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="purchasing_return_quantity"
            ),
        ]

    def __str__(self):
        return f"{self.supplier_return} line {self.line_no}"


class DebitNote(models.Model):
    """What the supplier owes back for invoiced goods returned (backlog P16-12): Dr Accounts
    payable, Cr Inventory at the PO price, Cr the recoverable tax, Dr/Cr any price
    difference. It reduces what is still to pay on the invoice. Never changed (database
    guard)."""

    number = models.CharField(max_length=30, unique=True)
    supplier_return = models.ForeignKey(
        SupplierReturn, on_delete=models.PROTECT, related_name="debit_notes"
    )
    invoice = models.ForeignKey(
        SupplierInvoice, on_delete=models.PROTECT, related_name="debit_notes"
    )
    return_line = models.ForeignKey(
        SupplierReturnLine, on_delete=models.PROTECT, related_name="debit_notes"
    )
    quantity = qty_field()
    amount = money()  # net, at the invoice price
    tax_amount = money(default=0)
    total_lkr = money()
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry", on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return self.number
