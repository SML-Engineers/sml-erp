"""Payment vouchers (spec 4). P1-01: voucher types."""

from django.conf import settings
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


class Voucher(models.Model):
    """A request to pay (spec 4.5). Numbered PPYYMMDDXXX when first saved (rule 10), in
    its division. Its approval runs through the shared engine (apps.core.approvals); the
    status here follows the engine's state."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        ACCOUNTANT_APPROVED = "accountant_approved", "Accountant approved"
        DIRECTOR_APPROVED = "director_approved", "Director approved"
        RETURNED = "returned", "Returned"
        REJECTED = "rejected", "Rejected"
        PARTLY_PAID = "partly_paid", "Partly paid"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"
        DELETED = "deleted", "Deleted"

    number = models.CharField(max_length=40, unique=True)
    voucher_type = models.ForeignKey(VoucherType, on_delete=models.PROTECT, related_name="vouchers")
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="vouchers")
    payee = models.ForeignKey(
        "masters.Supplier",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="vouchers",
    )
    # Internal transfers: the company account the money goes to (paid from another one).
    transfer_to = models.ForeignKey(
        "masters.CompanyAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="incoming_vouchers",
    )
    voucher_date = models.DateField()
    description = models.CharField(max_length=500, blank=True)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    revision = models.PositiveIntegerField(default=0)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="revisions"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="vouchers_created"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status="draft") | models.Q(total_amount__gt=0),
                name="vouchers_voucher_total_positive",
            ),
        ]

    def __str__(self):
        return self.number


class VoucherLine(models.Model):
    """One supplier invoice (or receipt) on the voucher. The Clerk enters the invoice,
    amount and tax; the Accountant codes the account and division (P1-03)."""

    voucher = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    invoice_no = models.CharField(max_length=50, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    description = models.CharField(max_length=500, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    tax_code = models.ForeignKey(
        "accounting.TaxCode", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    division = models.ForeignKey(
        "core.Division", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["voucher", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["voucher", "line_no"], name="vouchers_line_unique_no"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="vouchers_line_amount"),
            models.CheckConstraint(condition=models.Q(tax_amount__gte=0), name="vouchers_line_tax"),
        ]

    def __str__(self):
        return f"{self.voucher_id}/{self.line_no}"

    @property
    def total(self):
        return self.amount + self.tax_amount


class VoucherAttachment(models.Model):
    """A scanned invoice, receipt or other file. Added while the voucher is a draft or
    returned; its SHA-256 fingerprint reveals the same file uploaded twice."""

    voucher = models.ForeignKey(Voucher, on_delete=models.PROTECT, related_name="attachments")
    file = models.FileField(upload_to="vouchers/%Y/%m/")
    file_name = models.CharField(max_length=200)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64, db_index=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["uploaded_at", "id"]

    def __str__(self):
        return self.file_name
