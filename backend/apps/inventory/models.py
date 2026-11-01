"""Items and stores (backlog P16-03, spec 5A.3, 6A).

An item is anything SML buys and keeps or uses: resin, steel, inserts, consumables, spares,
packing. A store is a place stock is held, per division: the main store, the quarantine where
received goods wait for QC (6A), and the rejected store for goods going back to the supplier.
Codes used on documents never change; used records are deactivated, never deleted (rule 9,
database guard masters_code_guard).
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Item(models.Model):
    class Category(models.TextChoices):
        RAW_MATERIAL = "raw_material", "Raw material"
        BOUGHT_OUT = "bought_out", "Bought-out part"
        CONSUMABLE = "consumable", "Consumable"
        SPARE = "spare", "Spare part"
        PACKING = "packing", "Packing material"

    class Unit(models.TextChoices):
        PCS = "pcs", "pcs"
        KG = "kg", "kg"
        G = "g", "g"
        M = "m", "m"
        MM = "mm", "mm"
        L = "l", "l"
        SET = "set", "set"
        BOX = "box", "box"
        ROLL = "roll", "roll"
        SHEET = "sheet", "sheet"
        PAIR = "pair", "pair"

    class PackageType(models.TextChoices):
        """How it arrives, for package-by-package receiving (spec 6A.2)."""

        NONE = "none", "Not by package"
        BAG = "bag", "Bags (resin, masterbatch)"
        BAR = "bar", "Bars, rods, tubes"
        PLATE = "plate", "Plates, sheets"
        COIL = "coil", "Coils"
        COUNTED = "counted", "Counted items (boxes)"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=Category.choices)
    unit = models.CharField(max_length=10, choices=Unit.choices, default=Unit.PCS)
    # Stock items are received into a store and valued (IAS 2); non-stock items are bought
    # and used at once (expensed).
    is_stock = models.BooleanField(default=True)
    package_type = models.CharField(
        max_length=10, choices=PackageType.choices, default=PackageType.NONE
    )
    inspection_required = models.BooleanField(default=True)
    # Package-by-package receiving (spec 6A.2, backlog P16-07): the usual empty bag or coil
    # weight, how far a weight may differ before it is highlighted, and the standards that
    # bars (kg per metre) and plates (density) are checked against.
    package_tare = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    weight_tolerance_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.5")
    )
    standard_kg_per_m = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    density = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True)
    inventory_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="inventory_items",
    )
    expense_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="expense_items",
    )
    # The costing material it is (sales costing, P15-04), if any.
    material = models.ForeignKey(
        "masters.Material", null=True, blank=True, on_delete=models.PROTECT, related_name="items"
    )
    # Empty: used by every division.
    division = models.ForeignKey(
        "core.Division", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    first_used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.name}"


class Store(models.Model):
    class Kind(models.TextChoices):
        MAIN = "main", "Main store"
        QUARANTINE = "quarantine", "Quarantine (waiting for QC)"
        REJECTED = "rejected", "Rejected (to return)"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.MAIN)
    is_active = models.BooleanField(default=True)
    first_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["division__code", "kind", "code"]
        constraints = [
            # One quarantine and one rejected store per division; any number of main stores.
            models.UniqueConstraint(
                fields=["division", "kind"],
                condition=~models.Q(kind="main"),
                name="inventory_one_special_store_per_division",
            )
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


def _qty(**extra):
    return models.DecimalField(max_digits=18, decimal_places=3, **extra)


class GoodsReceipt(models.Model):
    """A goods receiving note (backlog P16-06, spec 5A.2): what a supplier delivered against
    an approved purchase order. Confirmed goods wait in the division's quarantine store for QC
    (P16-08). Once it leaves draft the database refuses changes; a mistake is corrected by a
    reversal the Director approves."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING_APPROVAL = "awaiting_approval", "Excess waiting for the Director"
        CONFIRMED = "confirmed", "Confirmed"
        REVERSAL_REQUESTED = "reversal_requested", "Reversal waiting for the Director"
        REVERSED = "reversed", "Reversed"

    number = models.CharField(max_length=30, unique=True)
    purchase_order = models.ForeignKey(
        "purchasing.PurchaseOrder", on_delete=models.PROTECT, related_name="receipts"
    )
    supplier = models.ForeignKey("masters.Supplier", on_delete=models.PROTECT, related_name="+")
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="receipts")
    receipt_date = models.DateField()
    delivery_note_no = models.CharField(max_length=50, blank=True)
    vehicle_no = models.CharField(max_length=30, blank=True)
    supplier_invoice_no = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.TextField(blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-receipt_date", "-number"]

    def __str__(self):
        return self.number


class GoodsReceiptLine(models.Model):
    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    po_line = models.ForeignKey(
        "purchasing.PurchaseOrderLine", on_delete=models.PROTECT, related_name="receipt_lines"
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="+")
    # What the PO still expected when this GRN was confirmed.
    outstanding_quantity = _qty(default=0)
    received_quantity = _qty(default=0)  # everything that arrived, damaged included
    damaged_quantity = _qty(default=0)
    # Good quantity above what the PO still expected: needs the Director (owner, 31 Oct 2026).
    excess_quantity = _qty(default=0)
    notes = models.CharField(max_length=300, blank=True)
    # The item's checks as they were when the packages were entered (rule 11).
    weight_tolerance_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    standard_kg_per_m = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    density = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True)

    class Meta:
        ordering = ["receipt", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["receipt", "line_no"], name="inventory_grn_line_no"),
            models.CheckConstraint(
                condition=models.Q(received_quantity__gte=0)
                & models.Q(damaged_quantity__gte=0)
                & models.Q(damaged_quantity__lte=models.F("received_quantity")),
                name="inventory_grn_quantities",
            ),
        ]

    def __str__(self):
        return f"{self.receipt} line {self.line_no}"

    @property
    def good_quantity(self):
        return self.received_quantity - self.damaged_quantity


class GoodsReceiptPhoto(models.Model):
    """A photo of the delivery, a damaged bag, or the delivery note (PDF, JPG or PNG)."""

    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.PROTECT, related_name="photos")
    file = models.FileField(upload_to="receipts/%Y/%m/")
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


class ReceiptPackage(models.Model):
    """One bag, bundle, plate, coil or box of a GRN line (spec 6A.2, backlog P16-07), with
    its own lot number printed on a QR label. The line's received and damaged quantities are
    the totals of its packages. Frozen with the GRN once it leaves draft (database guard)."""

    line = models.ForeignKey(GoodsReceiptLine, on_delete=models.CASCADE, related_name="packages")
    package_no = models.PositiveIntegerField()
    lot_no = models.CharField(max_length=40, unique=True)
    supplier_lot = models.CharField(max_length=50, blank=True)  # lot or heat number
    gross_weight = _qty(null=True, blank=True)
    tare_weight = _qty(default=0)
    net_weight = _qty(null=True, blank=True)
    declared_weight = _qty(null=True, blank=True)
    pieces = _qty(null=True, blank=True)  # pieces in a bundle, or quantity in a box
    piece_length = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    length_mm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    width_mm = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    thickness_mm = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    # In the item's unit: net kg, metres or pieces; empty until the package is weighed.
    quantity = _qty(null=True, blank=True)
    damaged = models.BooleanField(default=False)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["line", "package_no"]
        constraints = [
            models.UniqueConstraint(fields=["line", "package_no"], name="inventory_package_no")
        ]

    def __str__(self):
        return self.lot_no
