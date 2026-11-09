"""Production (Phase 3, spec 7). P3-01: moulds."""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.masters.models import CODE_REGEX


def size(label: str):
    return models.DecimalField(label, max_digits=7, decimal_places=1, null=True, blank=True)


class Mould(models.Model):
    """An injection mould (spec 7.1; backlog P3-01). Company moulds are linked to their fixed
    asset (P2-19) once it is in the register; customer moulds are tracked for shots and
    maintenance but not costed (owner, 7 Nov 2026). The code is fixed once a production
    document uses it, and a used mould is retired, never deleted (rule 9, database)."""

    class Owner(models.TextChoices):
        COMPANY = "company", "Company"
        CUSTOMER = "customer", "Customer"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        MAINTENANCE = "maintenance", "Under maintenance"
        RETIRED = "retired", "Retired"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    owner = models.CharField(max_length=10, choices=Owner.choices, default=Owner.COMPANY)
    customer = models.ForeignKey(
        "masters.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="moulds"
    )
    asset = models.OneToOneField(
        "assets.FixedAsset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="mould",
    )
    cycle_time_s = models.DecimalField("Standard cycle time (s)", max_digits=7, decimal_places=2)
    shot_weight_g = models.DecimalField(
        "Shot weight with runner (g)", max_digits=10, decimal_places=1
    )
    runner_weight_g = models.DecimalField(
        "Runner weight (g)", max_digits=10, decimal_places=1, default=0
    )
    tonnage_t = size("Clamping force needed (t)")
    width_mm = size("Width (mm)")
    height_mm = size("Height (mm)")
    thickness_mm = size("Thickness, closed (mm)")
    machines = models.ManyToManyField(
        "masters.Machine", blank=True, related_name="moulds", verbose_name="Compatible machines"
    )
    pm_interval_shots = models.PositiveIntegerField(
        "Maintenance every (shots)", null=True, blank=True
    )
    shot_count = models.PositiveBigIntegerField(default=0)
    shots_at_last_pm = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code__regex=CODE_REGEX), name="production_mould_code_format"
            ),
            models.CheckConstraint(
                condition=models.Q(owner="company", customer__isnull=True)
                | models.Q(owner="customer", customer__isnull=False, asset__isnull=True),
                name="production_mould_owner",
            ),
            models.CheckConstraint(
                condition=models.Q(cycle_time_s__gt=0, shot_weight_g__gt=0),
                name="production_mould_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(shots_at_last_pm__lte=models.F("shot_count")),
                name="production_mould_shots",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def is_active(self) -> bool:
        return self.status != self.Status.RETIRED


class MouldPart(models.Model):
    """A part the mould makes and its cavities; a family mould makes several parts."""

    mould = models.ForeignKey(Mould, on_delete=models.CASCADE, related_name="parts")
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="moulds")
    cavities = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["mould", "item__code"]
        constraints = [
            models.UniqueConstraint(fields=["mould", "item"], name="production_mouldpart_once"),
            models.CheckConstraint(
                condition=models.Q(cavities__gte=1), name="production_mouldpart_cavities"
            ),
        ]

    def __str__(self):
        return f"{self.mould_id}: {self.item_id} x {self.cavities}"


class ReasonCode(models.Model):
    """A reason a part is rejected or a machine stops, per division (spec 7.1, 7.4; backlog
    P3-02). Downtime reasons are planned (a planned stop is not lost time in OEE) or
    unplanned. The Admin adds, renames and deactivates them; the code is fixed once a shift
    report uses it, and a used reason is deactivated, never deleted (rule 9, database)."""

    class Kind(models.TextChoices):
        REJECT = "reject", "Reject"
        DOWNTIME = "downtime", "Downtime"

    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    planned = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["division", "kind", "sort_order", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["division", "kind", "code"], name="production_reason_once"
            ),
            models.CheckConstraint(
                condition=models.Q(code__regex=CODE_REGEX), name="production_reason_code_format"
            ),
            models.CheckConstraint(
                condition=models.Q(kind="downtime") | models.Q(planned=False),
                name="production_reason_planned_downtime",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class ProductionSetting(models.Model):
    """The production limits from a date (rule 11; backlog P3-02; owner, 7 Nov 2026: set in
    a control panel by an authorised person, not in code). A setting in force is never
    changed; a new one with a later date replaces it (database)."""

    effective_from = models.DateField(unique=True)
    grace_hours = models.DecimalField(
        "Entry grace period after a shift (hours)", max_digits=4, decimal_places=1
    )
    reject_alert_pct = models.DecimalField("Reject % alert", max_digits=5, decimal_places=2)
    overrun_alert_pct = models.DecimalField("Cost overrun % alert", max_digits=5, decimal_places=2)
    # Blank: the minimum margin of the order's quotation.
    min_margin_pct = models.DecimalField(
        "Minimum margin %", max_digits=5, decimal_places=2, null=True, blank=True
    )
    reason = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-effective_from"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    grace_hours__gte=0,
                    grace_hours__lte=48,
                    reject_alert_pct__gt=0,
                    reject_alert_pct__lte=100,
                    overrun_alert_pct__gt=0,
                    overrun_alert_pct__lte=100,
                ),
                name="production_setting_ranges",
            ),
        ]

    def __str__(self):
        return f"Production settings from {self.effective_from}"


class Routing(models.Model):
    """The operations that make a machined part (spec 7.1; backlog P3-03), one revision at a
    time: the Production Planner prepares a draft and submits it, the Production Manager
    approves it (approval engine, "routing"), and it replaces the part's routing in force,
    which becomes obsolete. Approved and obsolete routings never change and are never deleted
    (database); a change is a new revision."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING = "awaiting", "Waiting for approval"
        APPROVED = "approved", "Approved"
        OBSOLETE = "obsolete", "Obsolete"

    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="routings")
    revision = models.PositiveSmallIntegerField()
    drawing_revision = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["item__code", "-revision"]
        constraints = [
            models.UniqueConstraint(fields=["item", "revision"], name="production_routing_rev"),
            models.UniqueConstraint(
                fields=["item"],
                condition=models.Q(status="approved"),
                name="production_routing_one_in_force",
            ),
            models.UniqueConstraint(
                fields=["item"],
                condition=models.Q(status__in=["draft", "awaiting"]),
                name="production_routing_one_open",
            ),
        ]

    def __str__(self):
        return f"{self.item_id} rev {self.revision}"


class RoutingOperation(models.Model):
    """One operation: in a section (the machining method, e.g. manual milling) and optionally
    on one machine, with standard setup and run times; or sent out to a supplier."""

    routing = models.ForeignKey(Routing, on_delete=models.CASCADE, related_name="operations")
    seq = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=100)
    section = models.ForeignKey(
        "masters.Section", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    machine = models.ForeignKey(
        "masters.Machine", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    setup_min = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    run_min = models.DecimalField(
        "Run minutes per piece", max_digits=10, decimal_places=3, default=0
    )
    subcontract = models.BooleanField(default=False)
    supplier = models.ForeignKey(
        "masters.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    subcontract_cost = models.DecimalField(
        "Cost per piece", max_digits=18, decimal_places=2, null=True, blank=True
    )
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["routing", "seq"]
        constraints = [
            models.UniqueConstraint(fields=["routing", "seq"], name="production_operation_seq"),
            models.CheckConstraint(
                condition=models.Q(subcontract=True, supplier__isnull=False)
                | models.Q(subcontract=False, section__isnull=False),
                name="production_operation_where",
            ),
            models.CheckConstraint(
                condition=models.Q(setup_min__gte=0, run_min__gte=0),
                name="production_operation_times",
            ),
        ]

    def __str__(self):
        return f"{self.seq} {self.name}"


class Bom(models.Model):
    """A bill of materials (spec 7.1B; backlog P3-04): what makes `base_quantity` of an item
    (a finished part, sub-assembly, mould or tool); for a family mould, one mould run (a
    shot) with each part as an output. Revisions as routings: the Production Planner
    prepares, the Production Manager approves (approval engine, "bom"), the approved one
    replaces the item's BOM in force; approved and obsolete BOMs never change and are never
    deleted (database). Orders copy the BOM in force when released (P3-06, P3-11)."""

    class Kind(models.TextChoices):
        GENERAL = "general", "General"
        MACHINING = "machining", "Machining"
        MOULDING = "moulding", "Moulding"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING = "awaiting", "Waiting for approval"
        APPROVED = "approved", "Approved"
        OBSOLETE = "obsolete", "Obsolete"

    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="boms")
    revision = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.GENERAL)
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    drawing_revision = models.CharField(max_length=20, blank=True)
    effective_from = models.DateField(default=timezone.localdate)
    base_quantity = models.DecimalField(max_digits=14, decimal_places=4, default=1)
    # Moulding: the mould, and the part data the resin is worked out from.
    mould = models.ForeignKey(
        Mould, null=True, blank=True, on_delete=models.PROTECT, related_name="boms"
    )
    reject_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    max_regrind_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["item__code", "-revision"]
        constraints = [
            models.UniqueConstraint(fields=["item", "revision"], name="production_bom_rev"),
            models.UniqueConstraint(
                fields=["item"],
                condition=models.Q(status="approved"),
                name="production_bom_one_in_force",
            ),
            models.UniqueConstraint(
                fields=["item"],
                condition=models.Q(status__in=["draft", "awaiting"]),
                name="production_bom_one_open",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    base_quantity__gt=0,
                    reject_pct__gte=0,
                    reject_pct__lt=100,
                ),
                name="production_bom_quantities",
            ),
        ]

    def __str__(self):
        return f"BOM {self.item_id} rev {self.revision}"


class BomLine(models.Model):
    """One component of a BOM (spec 7.1B): its type, the quantity for the BOM's base
    quantity in the component's unit, scrap allowance, the operation it is used at, how it is
    issued, and whether the customer supplies it. A subcontract service has a description and
    supplier instead of an item."""

    class Type(models.TextChoices):
        RAW = "raw", "Raw material"
        MASTERBATCH = "masterbatch", "Masterbatch or additive"
        BOUGHT = "bought", "Bought-out part"
        SUB_ASSEMBLY = "sub_assembly", "Sub-assembly"
        SUBCONTRACT = "subcontract", "Subcontract service"
        PACKING = "packing", "Packing"

    class Issue(models.TextChoices):
        MANUAL = "manual", "Manual issue"
        BACKFLUSH = "backflush", "Backflush"

    bom = models.ForeignKey(Bom, on_delete=models.CASCADE, related_name="lines")
    seq = models.PositiveSmallIntegerField()
    line_type = models.CharField(max_length=15, choices=Type.choices)
    component = models.ForeignKey(
        "inventory.Item", null=True, blank=True, on_delete=models.PROTECT, related_name="used_in"
    )
    description = models.CharField(max_length=150, blank=True)
    supplier = models.ForeignKey(
        "masters.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=6)
    unit = models.CharField(max_length=10)
    scrap_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    # Masterbatch and additives: % of the resin's weight (the quantity follows from it).
    pct_of_resin = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    operation_seq = models.PositiveSmallIntegerField(null=True, blank=True)
    issue_method = models.CharField(max_length=10, choices=Issue.choices, default=Issue.MANUAL)
    customer_supplied = models.BooleanField(default=False)
    unit_cost = models.DecimalField(
        "Subcontract cost per unit", max_digits=18, decimal_places=2, null=True, blank=True
    )
    # Machining: the stock and how each piece is cut from it (mm).
    stock_size = models.CharField(max_length=50, blank=True)
    bar_length_mm = models.DecimalField(max_digits=9, decimal_places=1, null=True, blank=True)
    cut_length_mm = models.DecimalField(max_digits=9, decimal_places=1, null=True, blank=True)
    facing_mm = models.DecimalField(max_digits=7, decimal_places=1, null=True, blank=True)
    saw_mm = models.DecimalField(max_digits=7, decimal_places=1, null=True, blank=True)
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["bom", "seq"]
        constraints = [
            models.UniqueConstraint(fields=["bom", "seq"], name="production_bomline_seq"),
            models.CheckConstraint(
                condition=models.Q(line_type="subcontract", supplier__isnull=False)
                | (~models.Q(line_type="subcontract") & models.Q(component__isnull=False)),
                name="production_bomline_what",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0, scrap_pct__gte=0, scrap_pct__lt=100),
                name="production_bomline_quantities",
            ),
        ]

    def __str__(self):
        return f"{self.seq} {self.component_id or self.description}"


class BomOutput(models.Model):
    """A part made by one run of a family mould's BOM, with its cavities and part weight; a
    single-part moulding BOM has one output (the item itself)."""

    bom = models.ForeignKey(Bom, on_delete=models.CASCADE, related_name="outputs")
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="+")
    cavities = models.PositiveSmallIntegerField()
    part_weight_g = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["bom", "item__code"]
        constraints = [
            models.UniqueConstraint(fields=["bom", "item"], name="production_bomoutput_once"),
            models.CheckConstraint(
                condition=models.Q(cavities__gte=1, part_weight_g__gt=0),
                name="production_bomoutput_values",
            ),
        ]

    def __str__(self):
        return f"{self.item_id} x {self.cavities}"


class CostRate(models.Model):
    """A dated production cost rate kept by the Accountant (spec 7.7 `cost_rate`; backlog
    P3-05; rule 11):

    - **labour**: LKR per hour for a section (by default accepted from the latest approved
      payroll's labour cost per hour, P2B-13);
    - **overhead**: LKR per machine hour for a section, or for one machine (which then
      beats its section's); 0 until set;
    - **regrind**: LKR per kg of regrind of a material, overriding the owner's rule of 100%
      of the material's cost;
    - **mould**: LKR per shot for a company mould, the mould's cost ÷ its expected life in
      shots (customer moulds are never amortised).

    A rate in force never changes and is never deleted; a later rate replaces it (database).
    """

    class Kind(models.TextChoices):
        LABOUR = "labour", "Labour per hour"
        OVERHEAD = "overhead", "Overhead per machine hour"
        REGRIND = "regrind", "Regrind credit per kg"
        MOULD = "mould", "Mould amortisation per shot"

    class Source(models.TextChoices):
        MANUAL = "manual", "Entered"
        PAYROLL = "payroll", "Accepted from the payroll"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    section = models.ForeignKey(
        "masters.Section", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    machine = models.ForeignKey(
        "masters.Machine", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    material = models.ForeignKey(
        "inventory.Item", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    mould = models.ForeignKey(
        Mould, null=True, blank=True, on_delete=models.PROTECT, related_name="cost_rates"
    )
    effective_from = models.DateField()
    rate = models.DecimalField("Rate (LKR)", max_digits=18, decimal_places=4)
    # Mould amortisation: what the rate was worked out from.
    mould_cost = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    life_shots = models.PositiveBigIntegerField(null=True, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    payroll_run = models.ForeignKey(
        "payroll.PayrollRun", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reason = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["kind", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "section", "machine", "material", "mould", "effective_from"],
                name="production_costrate_once",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=models.Q(rate__gte=0), name="production_costrate_rate"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    kind="labour",
                    section__isnull=False,
                    machine__isnull=True,
                    material__isnull=True,
                    mould__isnull=True,
                )
                | models.Q(
                    kind="overhead",
                    section__isnull=False,
                    material__isnull=True,
                    mould__isnull=True,
                )
                | models.Q(
                    kind="regrind",
                    section__isnull=True,
                    machine__isnull=True,
                    material__isnull=False,
                    mould__isnull=True,
                )
                | models.Q(
                    kind="mould",
                    section__isnull=True,
                    machine__isnull=True,
                    material__isnull=True,
                    mould__isnull=False,
                    mould_cost__gte=0,
                    life_shots__gt=0,
                ),
                name="production_costrate_target",
            ),
            models.CheckConstraint(
                condition=models.Q(source="manual", payroll_run__isnull=True)
                | models.Q(source="payroll", kind="labour", payroll_run__isnull=False),
                name="production_costrate_source",
            ),
        ]

    def __str__(self):
        return f"{self.kind} {self.effective_from} {self.rate}"


class ProductionOrder(models.Model):
    """A moulding production order (spec 7.7; backlog P3-06): a part and quantity with due
    dates, for a sales order line's delivery schedule or for stock; numbered from the number
    series. On release the BOM in force is copied to the order (`OrderBomLine`), so later
    BOM changes never alter it. Draft → Released → Completed → Closed, or Cancelled before
    completion; an order is never deleted and moves only forward (database)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        RELEASED = "released", "Released"
        COMPLETED = "completed", "Completed"
        CLOSED = "closed", "Closed"
        CANCELLED = "cancelled", "Cancelled"

    class Purpose(models.TextChoices):
        SALES = "sales", "For a sales order"
        STOCK = "stock", "For stock"

    number = models.CharField(max_length=30, unique=True)
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    item = models.ForeignKey(
        "inventory.Item", on_delete=models.PROTECT, related_name="production_orders"
    )
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    purpose = models.CharField(max_length=5, choices=Purpose.choices, default=Purpose.STOCK)
    sales_line = models.ForeignKey(
        "sales.SalesOrderLine",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="production_orders",
    )
    # Filled on release: the BOM copied, its mould, and the shots a family mould needs.
    bom = models.ForeignKey(
        Bom, null=True, blank=True, on_delete=models.PROTECT, related_name="production_orders"
    )
    mould = models.ForeignKey(
        Mould, null=True, blank=True, on_delete=models.PROTECT, related_name="production_orders"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    end_reason = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    released_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="production_order_quantity"
            ),
            models.CheckConstraint(
                condition=models.Q(purpose="sales", sales_line__isnull=False)
                | models.Q(purpose="stock", sales_line__isnull=True),
                name="production_order_purpose",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["draft", "cancelled"])
                | models.Q(bom__isnull=False, released_at__isnull=False),
                name="production_order_released",
            ),
        ]

    def __str__(self):
        return self.number


class ProductionOrderDue(models.Model):
    """A due date and quantity of a production order; the quantities add up to the order's."""

    order = models.ForeignKey(ProductionOrder, on_delete=models.CASCADE, related_name="dues")
    due_date = models.DateField()
    quantity = models.DecimalField(max_digits=18, decimal_places=3)

    class Meta:
        ordering = ["order", "due_date", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="production_orderdue_quantity"
            ),
        ]

    def __str__(self):
        return f"{self.quantity} by {self.due_date}"


class OrderBomLine(models.Model):
    """The BOM copied to a production order on release (spec 7.1B `order_bom_line`): each
    line with the quantity the whole order needs. Never changed once copied (database)."""

    order = models.ForeignKey(ProductionOrder, on_delete=models.PROTECT, related_name="bom_lines")
    seq = models.PositiveSmallIntegerField()
    line_type = models.CharField(max_length=15, choices=BomLine.Type.choices)
    component = models.ForeignKey(
        "inventory.Item", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    description = models.CharField(max_length=150, blank=True)
    supplier = models.ForeignKey(
        "masters.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    per_base = models.DecimalField("Quantity for the BOM's base", max_digits=14, decimal_places=6)
    scrap_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    required = models.DecimalField("Needed for the order", max_digits=18, decimal_places=6)
    unit = models.CharField(max_length=10)
    operation_seq = models.PositiveSmallIntegerField(null=True, blank=True)
    issue_method = models.CharField(max_length=10, choices=BomLine.Issue.choices)
    customer_supplied = models.BooleanField(default=False)
    unit_cost = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["order", "seq"]
        constraints = [
            models.UniqueConstraint(fields=["order", "seq"], name="production_orderbomline_seq"),
            models.CheckConstraint(
                condition=models.Q(per_base__gt=0, required__gt=0),
                name="production_orderbomline_quantities",
            ),
        ]

    def __str__(self):
        return f"{self.order_id}/{self.seq}"


class PlanEntry(models.Model):
    """One run in the moulding production plan (spec 7.3, 7.5 `production_plan`; backlog
    P3-07): a released production order's mould on a machine for a shift of a date (a night
    shift belongs to the date it starts), for some minutes of the shift. The planned
    quantity follows from the mould's cycle time and the part's cavities. Past days never
    change (database)."""

    day = models.DateField()
    shift = models.ForeignKey("masters.Shift", on_delete=models.PROTECT, related_name="+")
    machine = models.ForeignKey(
        "masters.Machine", on_delete=models.PROTECT, related_name="plan_entries"
    )
    order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="plan_entries"
    )
    mould = models.ForeignKey(Mould, on_delete=models.PROTECT, related_name="plan_entries")
    minutes = models.PositiveSmallIntegerField("Planned minutes")
    quantity = models.DecimalField("Planned quantity", max_digits=18, decimal_places=3)
    notes = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["day", "shift__start_time", "machine__code", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(minutes__gt=0, quantity__gte=0),
                name="production_planentry_figures",
            ),
        ]

    def __str__(self):
        return f"{self.day} {self.shift_id} {self.machine_id}: {self.order_id}"


class ShiftReport(models.Model):
    """A supervisor's report of one section's shift (spec 7.4, 7.5 `shift_report`; backlog
    P3-08): moulding runs per machine with their rejects, downtime, material issued, returned
    and regrind, and manpower. Entered during the shift and the grace period after it, then
    submitted; a submitted report is locked (database). The Production Manager approves or
    returns it (P3-09)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        RETURNED = "returned", "Returned"
        APPROVED = "approved", "Approved"

    section = models.ForeignKey("masters.Section", on_delete=models.PROTECT, related_name="+")
    day = models.DateField()
    shift = models.ForeignKey("masters.Shift", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    # P3-09: the Production Manager's decision and what approval posted.
    return_reason = models.CharField(max_length=300, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    stock_issue = models.ForeignKey(
        "inventory.StockIssue", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    receipt_entry = models.ForeignKey(
        "accounting.JournalEntry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    # A correction (P3-09) reopens a report whose entry time is over until this moment.
    reopened_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-day", "shift__start_time", "section__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["section", "day", "shift"], name="production_shiftreport_once"
            ),
        ]

    def __str__(self):
        return f"{self.section_id} {self.day} {self.shift_id}"


class MouldingRun(models.Model):
    """One machine's run in a shift report (`production_entry`): the production order and its
    mould, the material batch, the operator, the times and the shot counter at start and end.
    Good quantity = shots × cavities − rejects."""

    report = models.ForeignKey(ShiftReport, on_delete=models.CASCADE, related_name="runs")
    machine = models.ForeignKey("masters.Machine", on_delete=models.PROTECT, related_name="+")
    order = models.ForeignKey(
        ProductionOrder, on_delete=models.PROTECT, related_name="moulding_runs"
    )
    mould = models.ForeignKey(Mould, on_delete=models.PROTECT, related_name="runs")
    plan_entry = models.ForeignKey(
        PlanEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name="runs"
    )
    material = models.ForeignKey(
        "inventory.Item", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    material_lot = models.CharField(max_length=40, blank=True)
    operator = models.ForeignKey(
        "payroll.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    start_counter = models.PositiveBigIntegerField()
    end_counter = models.PositiveBigIntegerField()
    cavities = models.PositiveSmallIntegerField()
    good_quantity = models.DecimalField(max_digits=18, decimal_places=3)
    actual_cycle_s = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["report", "machine__code", "started_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_counter__gte=models.F("start_counter")),
                name="production_run_counter",
            ),
            models.CheckConstraint(
                condition=models.Q(ended_at__gt=models.F("started_at")),
                name="production_run_times",
            ),
            models.CheckConstraint(
                condition=models.Q(cavities__gt=0, good_quantity__gte=0),
                name="production_run_figures",
            ),
        ]

    def __str__(self):
        return f"{self.report_id}/{self.machine_id}"

    @property
    def shots(self) -> int:
        return self.end_counter - self.start_counter


class RejectEntry(models.Model):
    run = models.ForeignKey(MouldingRun, on_delete=models.CASCADE, related_name="rejects")
    reason = models.ForeignKey(ReasonCode, on_delete=models.PROTECT, related_name="+")
    quantity = models.PositiveIntegerField()

    class Meta:
        ordering = ["run", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="production_reject_quantity"
            ),
        ]

    def __str__(self):
        return f"{self.run_id}: {self.quantity}"


class DowntimeEntry(models.Model):
    report = models.ForeignKey(ShiftReport, on_delete=models.CASCADE, related_name="downtime")
    machine = models.ForeignKey("masters.Machine", on_delete=models.PROTECT, related_name="+")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    reason = models.ForeignKey(ReasonCode, on_delete=models.PROTECT, related_name="+")
    remarks = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["report", "machine__code", "started_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ended_at__gt=models.F("started_at")),
                name="production_downtime_times",
            ),
        ]

    def __str__(self):
        return f"{self.machine_id} {self.started_at}"


class MaterialEntry(models.Model):
    """Material drawn from stores for the shift, returned to stores, or regrind made."""

    class Kind(models.TextChoices):
        ISSUE = "issue", "Issued"
        RETURN = "return", "Returned"
        REGRIND = "regrind", "Regrind made"

    report = models.ForeignKey(ShiftReport, on_delete=models.CASCADE, related_name="materials")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="+")
    lot_no = models.CharField(max_length=40, blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)

    class Meta:
        ordering = ["report", "kind", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="production_material_quantity"
            ),
        ]

    def __str__(self):
        return f"{self.kind} {self.item_id} {self.quantity}"


class ManpowerEntry(models.Model):
    """People working the shift, per machine (or the section as a whole), and overtime."""

    report = models.ForeignKey(ShiftReport, on_delete=models.CASCADE, related_name="manpower")
    machine = models.ForeignKey(
        "masters.Machine", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    people = models.PositiveSmallIntegerField()
    overtime_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    class Meta:
        ordering = ["report", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(people__gt=0, overtime_hours__gte=0),
                name="production_manpower_figures",
            ),
        ]

    def __str__(self):
        return f"{self.report_id}: {self.people}"


class ProductionReceipt(models.Model):
    """What an approved shift report put into stock (P3-09), each with its stock movement:
    the good pieces of a run's part (and of a family mould's other parts), valued at the
    material they used less their share of the regrind credit (labour and overhead are added
    by order costing, P3-16), and the regrind made, at its credit value."""

    report = models.ForeignKey(ShiftReport, on_delete=models.PROTECT, related_name="receipts")
    # The run is let go when a corrected report's runs are entered again (the receipt stays,
    # undone, with its order and quantity).
    run = models.ForeignKey(
        MouldingRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="receipts"
    )
    order = models.ForeignKey(
        ProductionOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="receipts"
    )
    item = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="+")
    is_regrind = models.BooleanField(default=False)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    material_value = models.DecimalField(max_digits=18, decimal_places=2)
    regrind_credit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    value = models.DecimalField(max_digits=18, decimal_places=2)
    movement = models.OneToOneField(
        "inventory.StockMovement",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="production_receipt",
    )
    undone = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["report", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0, value__gte=0),
                name="production_receipt_figures",
            ),
            models.CheckConstraint(
                condition=models.Q(is_regrind=True) | models.Q(order__isnull=False),
                name="production_receipt_order",
            ),
        ]

    def __str__(self):
        return f"{self.item_id} × {self.quantity}"


class ShiftCorrection(models.Model):
    """A request to change a shift report after its entry time (P3-09): approved by the
    Production Manager, the Director, or a person the Admin gives the authority (the
    Director confirming), never the person who asked. The original stays on record."""

    class Status(models.TextChoices):
        AWAITING = "awaiting", "Waiting for approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    report = models.ForeignKey(ShiftReport, on_delete=models.PROTECT, related_name="corrections")
    reason = models.CharField(max_length=300)
    original = models.JSONField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.AWAITING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    requested_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["report", "-requested_at"]

    def __str__(self):
        return f"{self.report_id}: {self.status}"


class MouldMaintenance(models.Model):
    """A maintenance record of a mould (spec 7.5 `mould_maintenance`; backlog P3-10):
    preventive (planned) maintenance, which restarts the count of shots towards the next
    one, or a repair; with the date, the shot count then, the work done, its cost and who
    did it. Records are never changed or deleted (database); a mistake is put right with a
    new record."""

    class Kind(models.TextChoices):
        PLANNED = "planned", "Preventive maintenance"
        REPAIR = "repair", "Repair"

    mould = models.ForeignKey(Mould, on_delete=models.PROTECT, related_name="maintenance")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    done_on = models.DateField()
    shot_count = models.PositiveBigIntegerField()
    work_done = models.TextField()
    cost = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    done_by = models.CharField("Done by", max_length=100)
    by_workshop = models.BooleanField("Done by our workshop", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["mould", "-done_on", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cost__gte=0), name="production_mouldmaintenance_cost"
            ),
        ]

    def __str__(self):
        return f"{self.mould_id} {self.kind} {self.done_on}"


class JobOrder(models.Model):
    """A machining job order (spec 7.2; backlog P3-11): a part, drawing revision, quantity and
    due date for a sales order line, or an internal job (a new mould, a mould repair, tools,
    other work). Numbered from the number series ("JO"). The approved routing and BOM of the
    part are copied to the job when it is made and can be changed for this job while it is a
    draft; on release they are fixed. Draft → Released → Completed → Closed, or Cancelled
    before completion; never deleted, and only moves forward (database)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        RELEASED = "released", "Released"
        COMPLETED = "completed", "Completed"
        CLOSED = "closed", "Closed"
        CANCELLED = "cancelled", "Cancelled"

    class Purpose(models.TextChoices):
        SALES = "sales", "For a sales order"
        NEW_MOULD = "new_mould", "Mould making"
        MOULD_REPAIR = "mould_repair", "Mould repair"
        TOOLS = "tools", "Tools and fixtures"
        INTERNAL = "internal", "Other internal work"

    number = models.CharField(max_length=30, unique=True)
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    purpose = models.CharField(max_length=15, choices=Purpose.choices)
    sales_line = models.ForeignKey(
        "sales.SalesOrderLine",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="job_orders",
    )
    item = models.ForeignKey(
        "inventory.Item", null=True, blank=True, on_delete=models.PROTECT, related_name="job_orders"
    )
    mould = models.ForeignKey(
        Mould, null=True, blank=True, on_delete=models.PROTECT, related_name="job_orders"
    )
    description = models.CharField(max_length=200)
    drawing_no = models.CharField(max_length=50, blank=True)
    drawing_revision = models.CharField(max_length=20, blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    due_date = models.DateField()
    # Where the operations and materials were copied from (none for a job entered by hand).
    routing = models.ForeignKey(
        Routing, null=True, blank=True, on_delete=models.PROTECT, related_name="job_orders"
    )
    bom = models.ForeignKey(
        Bom, null=True, blank=True, on_delete=models.PROTECT, related_name="job_orders"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    end_reason = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    released_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="production_job_quantity"
            ),
            models.CheckConstraint(
                condition=models.Q(purpose="sales", sales_line__isnull=False, item__isnull=False)
                | (~models.Q(purpose="sales") & models.Q(sales_line__isnull=True)),
                name="production_job_purpose",
            ),
            models.CheckConstraint(
                condition=~models.Q(purpose="mould_repair") | models.Q(mould__isnull=False),
                name="production_job_repair_mould",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["draft", "cancelled"])
                | models.Q(released_at__isnull=False),
                name="production_job_released",
            ),
        ]

    def __str__(self):
        return self.number


class JobOperation(models.Model):
    """An operation of a job, copied from the routing (or entered for this job); changed only
    while the job is a draft (database)."""

    job = models.ForeignKey(JobOrder, on_delete=models.CASCADE, related_name="operations")
    seq = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=100)
    section = models.ForeignKey(
        "masters.Section", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    machine = models.ForeignKey(
        "masters.Machine", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    setup_min = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    run_min = models.DecimalField(
        "Run minutes per piece", max_digits=10, decimal_places=3, default=0
    )
    subcontract = models.BooleanField(default=False)
    supplier = models.ForeignKey(
        "masters.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    subcontract_cost = models.DecimalField(
        "Cost per piece", max_digits=18, decimal_places=2, null=True, blank=True
    )
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["job", "seq"]
        constraints = [
            models.UniqueConstraint(fields=["job", "seq"], name="production_joboperation_seq"),
            models.CheckConstraint(
                condition=models.Q(subcontract=True, supplier__isnull=False)
                | models.Q(subcontract=False, section__isnull=False),
                name="production_joboperation_where",
            ),
            models.CheckConstraint(
                condition=models.Q(setup_min__gte=0, run_min__gte=0),
                name="production_joboperation_times",
            ),
        ]

    def __str__(self):
        return f"{self.job_id}/{self.seq} {self.name}"


class JobMaterial(models.Model):
    """A material of a job with the quantity per piece, copied from the BOM (or entered for
    this job); changed only while the job is a draft (database). Stores issues up to that
    quantity times the job's; more needs the Production Manager's approval (`JobExcess`)."""

    job = models.ForeignKey(JobOrder, on_delete=models.CASCADE, related_name="materials")
    seq = models.PositiveSmallIntegerField()
    line_type = models.CharField(max_length=15, choices=BomLine.Type.choices)
    component = models.ForeignKey(
        "inventory.Item", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    description = models.CharField(max_length=150, blank=True)
    supplier = models.ForeignKey(
        "masters.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # Per piece of the job, with the scrap allowance; the job may use this × its quantity.
    per_piece = models.DecimalField(max_digits=14, decimal_places=6)
    unit = models.CharField(max_length=10)
    operation_seq = models.PositiveSmallIntegerField(null=True, blank=True)
    customer_supplied = models.BooleanField(default=False)
    unit_cost = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    stock_size = models.CharField(max_length=50, blank=True)
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["job", "seq"]
        constraints = [
            models.UniqueConstraint(fields=["job", "seq"], name="production_jobmaterial_seq"),
            models.CheckConstraint(
                condition=models.Q(line_type="subcontract", supplier__isnull=False)
                | (~models.Q(line_type="subcontract") & models.Q(component__isnull=False)),
                name="production_jobmaterial_what",
            ),
            models.CheckConstraint(
                condition=models.Q(per_piece__gt=0), name="production_jobmaterial_per_piece"
            ),
        ]

    def __str__(self):
        return f"{self.job_id}/{self.seq}"


class JobIssue(models.Model):
    """A stock issue to a job, or a return from it, by the stores person (inventory
    `StockIssue`). Insert-only (database)."""

    job = models.ForeignKey(JobOrder, on_delete=models.PROTECT, related_name="issues")
    stock_issue = models.OneToOneField(
        "inventory.StockIssue", on_delete=models.PROTECT, related_name="job_link"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["job", "id"]

    def __str__(self):
        return f"{self.job_id} {self.stock_issue_id}"


class JobExcess(models.Model):
    """A request to issue more of a material than the job allows (or one not on it), with a
    reason; the Production Manager approves it (approval engine, "job_excess"). An approved
    request adds its quantity to what Stores may issue. Never deleted; only a waiting request
    changes, and then only its decision (database)."""

    class Status(models.TextChoices):
        AWAITING = "awaiting", "Waiting for approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    job = models.ForeignKey(JobOrder, on_delete=models.PROTECT, related_name="excess")
    component = models.ForeignKey("inventory.Item", on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    reason = models.CharField(max_length=300)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.AWAITING)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["job", "-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="production_jobexcess_quantity"
            ),
        ]

    def __str__(self):
        return f"{self.job_id} +{self.quantity} {self.component_id}"


class JobCardEntry(models.Model):
    """Work on one operation of a job in a machining shift report (spec 7.4 `production_entry`;
    backlog P3-12), entered by scanning the job card: the machine, operator, start and end,
    pieces completed, rejected (by reason) and sent for rework. Locked with its report."""

    report = models.ForeignKey(ShiftReport, on_delete=models.CASCADE, related_name="job_entries")
    job = models.ForeignKey(JobOrder, on_delete=models.PROTECT, related_name="entries")
    operation = models.ForeignKey(JobOperation, on_delete=models.PROTECT, related_name="entries")
    machine = models.ForeignKey("masters.Machine", on_delete=models.PROTECT, related_name="+")
    operator = models.ForeignKey(
        "payroll.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    completed = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    rejected = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    rework = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    setup = models.BooleanField("Includes the setup", default=False)
    # Minutes worked less the machine's downtime in them, per piece (completed + rejected).
    minutes_per_piece = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["report", "machine__code", "started_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ended_at__gt=models.F("started_at")),
                name="production_jobentry_times",
            ),
            models.CheckConstraint(
                condition=models.Q(completed__gte=0, rejected__gte=0, rework__gte=0),
                name="production_jobentry_quantities",
            ),
        ]

    def __str__(self):
        return f"{self.report_id}/{self.job_id}/{self.operation_id}"


class JobCardReject(models.Model):
    entry = models.ForeignKey(JobCardEntry, on_delete=models.CASCADE, related_name="rejects")
    reason = models.ForeignKey(ReasonCode, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=18, decimal_places=3)

    class Meta:
        ordering = ["entry", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="production_jobreject_quantity"
            ),
        ]

    def __str__(self):
        return f"{self.entry_id} {self.reason_id} {self.quantity}"


class SubcontractDispatch(models.Model):
    """Parts of a job sent out to a supplier for a subcontract operation (backlog P3-13; spec
    7.2), numbered from the number series ("SC") with a printed note. Never changed or
    deleted (database); a mistake is put right by receiving the parts back."""

    number = models.CharField(max_length=30, unique=True)
    job = models.ForeignKey(JobOrder, on_delete=models.PROTECT, related_name="dispatches")
    operation = models.ForeignKey(JobOperation, on_delete=models.PROTECT, related_name="dispatches")
    supplier = models.ForeignKey("masters.Supplier", on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    sent_on = models.DateField()
    expected_on = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["job", "sent_on", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="production_dispatch_quantity"
            ),
        ]

    def __str__(self):
        return self.number


class SubcontractReturn(models.Model):
    """Parts received back from the supplier against a dispatch, counted: good, and rejected
    (with the reason). Together never more than is still out (service and database). Never
    changed or deleted (database)."""

    dispatch = models.ForeignKey(
        SubcontractDispatch, on_delete=models.PROTECT, related_name="returns"
    )
    received_on = models.DateField()
    good = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    rejected = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    reason = models.CharField(max_length=300, blank=True)
    notes = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["dispatch", "received_on", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(good__gte=0, rejected__gte=0)
                & (models.Q(good__gt=0) | models.Q(rejected__gt=0)),
                name="production_subreturn_quantities",
            ),
            models.CheckConstraint(
                condition=models.Q(rejected=0) | ~models.Q(reason=""),
                name="production_subreturn_reason",
            ),
        ]

    def __str__(self):
        return f"{self.dispatch_id} back {self.good}+{self.rejected}"


class JobInspection(models.Model):
    """QC's inspection of a job (backlog P3-14; spec 7.2): first-article, in-process or final,
    after one of its operations, with measurements on the pieces checked. The checks are
    copied from the part's inspection plan (Phase 1.6) when it starts, and the inspector may
    add more. A failed inspection **holds the job** until the Production Manager decides:
    rework or scrap a number of pieces, or accept under deviation (the Director approves
    when a critical check failed). Decided inspections never change (database)."""

    class Stage(models.TextChoices):
        FIRST_ARTICLE = "first_article", "First article"
        IN_PROCESS = "in_process", "In process"
        FINAL = "final", "Final"

    class Status(models.TextChoices):
        DRAFT = "draft", "Being inspected"
        PASSED = "passed", "Passed"
        ON_HOLD = "on_hold", "Failed: job on hold"
        DEVIATION_REQUESTED = "deviation_requested", "Deviation waiting for the Director"
        DECIDED = "decided", "Decided"

    class Decision(models.TextChoices):
        REWORK = "rework", "Rework"
        SCRAP = "scrap", "Scrap"
        DEVIATION = "deviation", "Accept under deviation"

    job = models.ForeignKey(JobOrder, on_delete=models.PROTECT, related_name="inspections")
    operation = models.ForeignKey(
        JobOperation, on_delete=models.PROTECT, related_name="inspections"
    )
    stage = models.CharField(max_length=15, choices=Stage.choices)
    plan = models.ForeignKey(
        "inventory.InspectionPlan",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="+",
    )
    pieces = models.PositiveSmallIntegerField("Pieces checked", default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField(blank=True)
    inspector = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    inspected_at = models.DateTimeField(null=True, blank=True)
    decision = models.CharField(max_length=10, choices=Decision.choices, blank=True)
    decision_quantity = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    decision_reason = models.CharField(max_length=300, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["job", "created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(pieces__gte=1, pieces__lte=50, decision_quantity__gte=0),
                name="production_jobinspection_figures",
            ),
            models.CheckConstraint(
                condition=~models.Q(status="decided") | ~models.Q(decision=""),
                name="production_jobinspection_decided",
            ),
        ]

    def __str__(self):
        return f"{self.job_id} {self.stage} {self.operation_id}"


class JobInspectionResult(models.Model):
    """One check on one piece, copied from the plan (or added by the inspector)."""

    inspection = models.ForeignKey(JobInspection, on_delete=models.CASCADE, related_name="results")
    position = models.PositiveSmallIntegerField()
    piece = models.PositiveSmallIntegerField(default=1)
    name = models.CharField(max_length=100)
    kind = models.CharField(
        max_length=10, choices=[("number", "Measured"), ("pass_fail", "Pass or fail")]
    )
    minimum = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    maximum = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    critical = models.BooleanField(default=False)
    value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    passed = models.BooleanField(null=True, blank=True)
    within_limits = models.BooleanField(null=True, blank=True)
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["inspection", "position", "piece"]
        constraints = [
            models.UniqueConstraint(
                fields=["inspection", "position", "piece"], name="production_jobresult_once"
            ),
        ]

    def __str__(self):
        return f"{self.inspection_id} {self.name} #{self.piece}"


class InterDivisionTransfer(models.Model):
    """A workshop job done for another division, transferred at cost (backlog P3-15; spec
    3.1, 7.3): a **new company mould** is capitalised to the mould's fixed asset (Dr the
    moulds' cost account), a **mould repair** is charged to the mould's division (Dr
    Inter-division charges); Cr Inter-division sales in the workshop. One per job, posted
    by the Accountant when the job is completed, with the cost it is made of; never changed
    or deleted (database). Repairs are eliminated in the company total."""

    class Kind(models.TextChoices):
        NEW_MOULD = "new_mould", "New mould capitalised"
        REPAIR = "repair", "Mould repair charged"

    job = models.OneToOneField(JobOrder, on_delete=models.PROTECT, related_name="transfer")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    mould = models.ForeignKey(Mould, on_delete=models.PROTECT, related_name="transfers")
    from_division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    to_division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    transfer_date = models.DateField()
    material = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    bills = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    labour = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    overhead = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    fixed_asset = models.OneToOneField(
        "assets.FixedAsset", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    journal_entry = models.OneToOneField(
        "accounting.JournalEntry", on_delete=models.PROTECT, related_name="+"
    )
    notes = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-transfer_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    amount__gt=0, material__gte=0, bills__gte=0, labour__gte=0, overhead__gte=0
                )
                & models.Q(
                    amount=models.F("material")
                    + models.F("bills")
                    + models.F("labour")
                    + models.F("overhead")
                ),
                name="production_transfer_amounts",
            ),
            models.CheckConstraint(
                condition=models.Q(kind="new_mould", fixed_asset__isnull=False)
                | models.Q(kind="repair", fixed_asset__isnull=True),
                name="production_transfer_asset",
            ),
            models.CheckConstraint(
                condition=~models.Q(from_division=models.F("to_division")),
                name="production_transfer_divisions",
            ),
        ]

    def __str__(self):
        return f"{self.job_id} {self.kind} {self.amount}"


class OrderCost(models.Model):
    """One cost of a job order or a moulding production order (backlog P3-16; spec 7.7 "Where
    each cost comes from"), collected from what was approved: material, labour, overhead,
    setup and mould change, mould amortisation, subcontract and direct bills. Each entry
    names its source (e.g. an issue line, a job card, a moulding run, a voucher line) and
    keeps the rate it used. Insert-only (database): when a source changes or is undone, an
    adjusting entry with the same source is added, so the history stays."""

    class Element(models.TextChoices):
        MATERIAL = "material", "Material"
        LABOUR = "labour", "Labour"
        OVERHEAD = "overhead", "Machine time and overhead"
        SETUP = "setup", "Setup and mould change"
        MOULD = "mould", "Mould amortisation"
        SUBCONTRACT = "subcontract", "Subcontract"
        DIRECT = "direct", "Direct expenses"

    job = models.ForeignKey(
        JobOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="costs"
    )
    production_order = models.ForeignKey(
        ProductionOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="costs"
    )
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    element = models.CharField(max_length=12, choices=Element.choices)
    day = models.DateField()
    source = models.CharField(max_length=60)
    quantity = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    unit = models.CharField(max_length=10, blank=True)
    rate = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    description = models.CharField(max_length=200)
    adjusts = models.BooleanField("Adjusts an earlier entry of the same source", default=False)

    # P3-16 part 2, the ledger: where the cost went (Work in progress until a job is
    # completed; a moulding order's finished parts; cost of sales once none are left in
    # stock; or nowhere: a moulding order's material is in its parts already, and jobs
    # without a stock part leave their costs where they are), the account it came out of,
    # and the journal.
    class Ledger(models.TextChoices):
        NONE = "none", "Not posted"
        WIP = "wip", "Work in progress"
        FINISHED = "finished", "Finished goods"
        SOLD = "sold", "Cost of finished goods sold"

    ledger = models.CharField(max_length=10, choices=Ledger.choices, blank=True)
    credit_account = models.ForeignKey(
        "accounting.Account", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    credit_division = models.ForeignKey(
        "core.Division", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["day", "id"]
        indexes = [models.Index(fields=["source"], name="production_ordercost_source")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(job__isnull=False, production_order__isnull=True)
                | models.Q(job__isnull=True, production_order__isnull=False),
                name="production_ordercost_one_order",
            ),
        ]

    def __str__(self):
        return f"{self.job_id or self.production_order_id} {self.element} {self.amount}"


class JobCompletion(models.Model):
    """A job's finished parts received into stock when it is completed (backlog P3-16 part
    2): its Work in progress moved to finished goods (Dr finished goods, Cr Work in
    progress), lot = the job's number. Never changed or deleted (database)."""

    job = models.OneToOneField(JobOrder, on_delete=models.PROTECT, related_name="completion")
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    value = models.DecimalField(max_digits=18, decimal_places=2)
    movement = models.OneToOneField(
        "inventory.StockMovement", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0, value__gte=0),
                name="production_completion_values",
            ),
        ]

    def __str__(self):
        return f"{self.job_id} {self.quantity} {self.value}"
