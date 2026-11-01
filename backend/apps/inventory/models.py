"""Items and stores (backlog P16-03, spec 5A.3, 6A).

An item is anything SML buys and keeps or uses: resin, steel, inserts, consumables, spares,
packing. A store is a place stock is held, per division: the main store, the quarantine where
received goods wait for QC (6A), and the rejected store for goods going back to the supplier.
Codes used on documents never change; used records are deactivated, never deleted (rule 9,
database guard masters_code_guard).
"""

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
