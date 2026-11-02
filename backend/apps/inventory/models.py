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
    # The exchange rate on the receipt date: the goods are valued at it (IAS 21, P16-19).
    # Empty on GRNs confirmed before then, which were valued at the PO's rate.
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    rate_date = models.DateField(null=True, blank=True)
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


# --- Incoming inspection (backlog P16-08, spec 6A.3, 6A.4) -----------------------------------


class InspectionPlan(models.Model):
    """What QC checks on an item, or on every item of a category without its own plan."""

    class Sampling(models.TextChoices):
        ALL = "all", "Every package"
        FIXED = "fixed", "A fixed number of packages"
        PERCENT = "percent", "A percentage of the packages"

    name = models.CharField(max_length=100)
    item = models.ForeignKey(
        Item, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    category = models.CharField(max_length=20, choices=Item.Category.choices, blank=True)
    sampling = models.CharField(max_length=10, choices=Sampling.choices, default=Sampling.ALL)
    sample_value = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(item__isnull=False) & models.Q(category=""))
                | (models.Q(item__isnull=True) & ~models.Q(category="")),
                name="inventory_plan_item_or_category",
            ),
            models.UniqueConstraint(
                fields=["item"],
                condition=models.Q(is_active=True, item__isnull=False),
                name="inventory_one_plan_per_item",
            ),
            models.UniqueConstraint(
                fields=["category"],
                condition=models.Q(is_active=True, item__isnull=True),
                name="inventory_one_plan_per_category",
            ),
        ]

    def __str__(self):
        return self.name


class InspectionParameter(models.Model):
    class Kind(models.TextChoices):
        NUMBER = "number", "Measured (min and max)"
        PASS_FAIL = "pass_fail", "Pass or fail"

    plan = models.ForeignKey(InspectionPlan, on_delete=models.CASCADE, related_name="parameters")
    position = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    minimum = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    maximum = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    critical = models.BooleanField(default=False)

    class Meta:
        ordering = ["plan", "position"]

    def __str__(self):
        return self.name


class IncomingInspection(models.Model):
    """QC's inspection of one GRN line. The checks are copied from the plan when it starts,
    so a later change to the plan does not change it (rule 11). Once decided it never
    changes (database guard)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Being inspected"
        DEVIATION_REQUESTED = "deviation_requested", "Deviation waiting for the Director"
        DECIDED = "decided", "Decided"

    class Decision(models.TextChoices):
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        DEVIATION = "deviation", "Accepted under deviation"

    line = models.OneToOneField(
        GoodsReceiptLine, on_delete=models.PROTECT, related_name="inspection"
    )
    plan = models.ForeignKey(
        InspectionPlan, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    sample_size = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    decision = models.CharField(max_length=10, choices=Decision.choices, blank=True)
    # Of the good quantity (received less damaged): accepted + rejected = good.
    accepted_quantity = _qty(default=0)
    rejected_quantity = _qty(default=0)
    notes = models.TextField(blank=True)
    reason = models.TextField(blank=True)  # for rejecting or for the deviation
    # No inspection needed for the item: accepted when the GRN was confirmed.
    automatic = models.BooleanField(default=False)
    inspector = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    started_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Inspection of {self.line}"


class InspectionResult(models.Model):
    inspection = models.ForeignKey(
        IncomingInspection, on_delete=models.CASCADE, related_name="results"
    )
    position = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=InspectionParameter.Kind.choices)
    minimum = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    maximum = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    critical = models.BooleanField(default=False)
    value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    passed = models.BooleanField(null=True, blank=True)  # pass/fail checks
    within_limits = models.BooleanField(null=True, blank=True)  # worked out; None: not entered
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["inspection", "position"]

    def __str__(self):
        return self.name


class RejectedPackage(models.Model):
    """A bag, bundle or box QC rejected while accepting the rest of the line (owner, 1 Nov
    2026: decisions per package)."""

    inspection = models.ForeignKey(
        IncomingInspection, on_delete=models.CASCADE, related_name="rejected_packages"
    )
    package = models.OneToOneField(
        ReceiptPackage, on_delete=models.PROTECT, related_name="rejection"
    )

    def __str__(self):
        return f"{self.package} rejected"


class InspectionAttachment(models.Model):
    """A certificate of analysis, mill test certificate or photo (PDF, JPG or PNG)."""

    inspection = models.ForeignKey(
        IncomingInspection, on_delete=models.PROTECT, related_name="attachments"
    )
    file = models.FileField(upload_to="inspections/%Y/%m/")
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


# --- Stock (backlog P16-09, spec 5A.3, IAS 2) ----------------------------------------------


class StockMovement(models.Model):
    """One movement of one lot of an item into (+) or out of (−) a store, with its value in
    LKR. Balances are always the sum of the movements, never typed. Rows are never changed or
    deleted (database guard); a mistake is corrected by another movement.

    Goods wait in quarantine at no value; when QC accepts them they move to the main store at
    the PO price (Dr Inventory, Cr Goods received not invoiced). Rejected and damaged goods
    wait in the rejected store, at no value, to go back to the supplier."""

    class Kind(models.TextChoices):
        RECEIVED = "received", "Received into quarantine"
        DAMAGED = "damaged", "Received damaged"
        ACCEPTED = "accepted", "Accepted by QC"
        REJECTED = "rejected", "Rejected by QC"
        REVERSED = "reversed", "GRN reversed"
        RETURNED = "returned", "Returned to the supplier"
        OPENING = "opening", "Opening stock"
        # Value only: the supplier's invoice price differs from the PO price (IAS 2, P16-18).
        PRICE = "price_diff", "Invoice price difference"

    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="movements")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="movements")
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    lot_no = models.CharField(max_length=40)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    movement_date = models.DateField()
    quantity = _qty()  # + into the store, − out of it
    value = models.DecimalField(max_digits=18, decimal_places=2, default=0)  # LKR, signed
    receipt_line = models.ForeignKey(
        GoodsReceiptLine, null=True, blank=True, on_delete=models.PROTECT, related_name="movements"
    )
    opening_line = models.ForeignKey(
        "OpeningStockLine",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="movements",
    )
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["movement_date", "id"]
        indexes = [models.Index(fields=["item", "store", "lot_no"], name="inventory_mv_balance")]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(quantity=0)
                | (models.Q(kind="price_diff") & ~models.Q(value=0)),
                name="inventory_movement_not_zero",
            )
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.quantity} {self.item.code} @ {self.store.code}"


# --- Opening stock (backlog P16-15, owner's decision of 2 Nov 2026) --------------------------


class OpeningStock(models.Model):
    """The stores counted at go-live, with the cost of each item, loaded from Excel. It is a
    draft until the Director approves it; approval puts the quantities into the main stores
    and posts their value (Dr Inventory, Cr Opening balance equity). Once sent it never
    changes, and only a draft is deleted (database guard)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING_APPROVAL = "awaiting_approval", "Waiting for the Director"
        POSTED = "posted", "Approved and in stock"
        REJECTED = "rejected", "Rejected"

    number = models.CharField(max_length=30, unique=True)
    count_date = models.DateField()
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    journal_entry = models.OneToOneField(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="opening_stock",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-count_date", "-number"]

    def __str__(self):
        return self.number


class OpeningStockLine(models.Model):
    opening = models.ForeignKey(OpeningStock, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveIntegerField()
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="+")
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="+")
    lot_no = models.CharField(max_length=40)
    quantity = _qty()
    unit_cost = models.DecimalField(max_digits=18, decimal_places=4)
    value = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["opening", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["opening", "line_no"], name="inventory_os_line_no"),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0) & models.Q(unit_cost__gt=0),
                name="inventory_os_line_positive",
            ),
        ]

    def __str__(self):
        return f"{self.opening_id}/{self.line_no}"
