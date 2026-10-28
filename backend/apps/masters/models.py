"""Factory structure: Division → Section → Machine (spec 3A.1, backlog P0-09).

Codes are fixed once a transaction has used them, and anything with history is made
inactive rather than deleted (rule 9); the database enforces both (migration 0002).
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import Division

CODE_REGEX = r"^[A-Z0-9][A-Z0-9-]{0,19}$"


class Section(models.Model):
    # Factory structure, not a document: having sections does not fix a division's code.
    is_structure = True

    class Category(models.TextChoices):
        MANUAL = "manual", "Manual"
        CNC = "cnc", "CNC"

    class Type(models.TextChoices):
        MACHINING = "machining", "Machining"
        MOULDING = "moulding", "Moulding"
        SUPPORT = "support", "Support"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    division = models.ForeignKey(Division, on_delete=models.PROTECT, related_name="sections")
    # Manual or CNC for machining sections; empty for moulding and support.
    category = models.CharField(max_length=10, choices=Category.choices, blank=True)
    section_type = models.CharField(max_length=20, choices=Type.choices)
    supervisors = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="supervised_sections"
    )
    # Section scope (spec 1.1): users limited to particular sections. Users whose
    # `all_sections` is set see every section of their divisions.
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="sections")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["division__code", "code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code__regex=CODE_REGEX), name="masters_section_code_format"
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class Machine(models.Model):
    # Factory structure, not a document: having machines does not fix a section's code.
    is_structure = True

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        MAINTENANCE = "maintenance", "Under maintenance"
        RETIRED = "retired", "Retired"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name="machines")
    make = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    serial_no = models.CharField("Serial no.", max_length=100, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    # Retired machines are hidden from entry pages; their history stays.
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    photo = models.FileField(upload_to="machines/", blank=True)
    notes = models.TextField(blank=True)

    # Moulding machines: used to warn when a mould is planned on a machine too small for it.
    clamping_force_t = models.DecimalField(
        "Clamping force (t)", max_digits=8, decimal_places=1, null=True, blank=True
    )
    max_shot_weight_g = models.DecimalField(
        "Maximum shot weight (g)", max_digits=10, decimal_places=1, null=True, blank=True
    )
    screw_diameter_mm = models.DecimalField(
        "Screw diameter (mm)", max_digits=7, decimal_places=1, null=True, blank=True
    )
    tie_bar_h_mm = models.DecimalField(
        "Tie-bar spacing, horizontal (mm)", max_digits=7, decimal_places=1, null=True, blank=True
    )
    tie_bar_v_mm = models.DecimalField(
        "Tie-bar spacing, vertical (mm)", max_digits=7, decimal_places=1, null=True, blank=True
    )
    max_mould_height_mm = models.DecimalField(
        "Maximum mould height (mm)", max_digits=7, decimal_places=1, null=True, blank=True
    )
    max_mould_thickness_mm = models.DecimalField(
        "Maximum mould thickness (mm)", max_digits=7, decimal_places=1, null=True, blank=True
    )

    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code__regex=CODE_REGEX), name="masters_machine_code_format"
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def is_active(self) -> bool:
        return self.status != self.Status.RETIRED


class MachineRate(models.Model):
    """Hourly machine rate in LKR from a date (rule 11). Earlier jobs keep the old rate.

    Once its date has arrived a rate can no longer be changed or removed; a new rate with a
    later date replaces it (migration 0002).
    """

    # A setting with its own history, not a transaction: rates do not fix a machine's code.
    is_structure = True

    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="rates")
    effective_from = models.DateField()
    rate = models.DecimalField("Hourly rate (LKR)", max_digits=18, decimal_places=2)
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["machine", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["machine", "effective_from"], name="masters_machinerate_one_per_day"
            ),
            models.CheckConstraint(
                condition=models.Q(rate__gte=0), name="masters_rate_not_negative"
            ),
        ]

    def __str__(self):
        return f"{self.machine.code} {self.rate} from {self.effective_from}"


# --- Shifts and rosters (spec 3A.2, 7.1A; backlog P0-10) --------------------------------


class Shift(models.Model):
    """A working shift. One that ends at or before its start time runs past midnight and
    belongs to the date it started (for production, OEE, costing and payroll)."""

    code = models.CharField(max_length=5, unique=True)
    name = models.CharField(max_length=50, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    break_minutes = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["start_time", "code"]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def crosses_midnight(self) -> bool:
        return self.end_time <= self.start_time

    @property
    def length_minutes(self) -> int:
        start = self.start_time.hour * 60 + self.start_time.minute
        end = self.end_time.hour * 60 + self.end_time.minute
        return end - start + (24 * 60 if self.crosses_midnight else 0)

    @property
    def working_minutes(self) -> int:
        return self.length_minutes - self.break_minutes


class RosterPattern(models.Model):
    """A repeating cycle of shifts and days off, e.g. Day, Day, Night, Night, Off, Off."""

    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RosterPatternDay(models.Model):
    # Part of its pattern: saved and changed together with it.
    is_structure = True

    pattern = models.ForeignKey(RosterPattern, on_delete=models.CASCADE, related_name="days")
    position = models.PositiveSmallIntegerField()  # 0 = first day of the cycle
    # Empty = a day off.
    shift = models.ForeignKey(
        Shift, null=True, blank=True, on_delete=models.PROTECT, related_name="pattern_days"
    )

    class Meta:
        ordering = ["pattern", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["pattern", "position"], name="masters_patternday_unique_position"
            ),
        ]

    def __str__(self):
        return f"{self.pattern.name} day {self.position + 1}: {self.shift or 'Off'}"


class Crew(models.Model):
    """A team that works the same rotation (A, B, C…). Members come from the employee
    register when the HR module is added."""

    # Factory organisation, not a document: crews do not fix a division's code.
    is_structure = True

    code = models.CharField(max_length=10)
    name = models.CharField(max_length=100, blank=True)
    division = models.ForeignKey(Division, on_delete=models.PROTECT, related_name="crews")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["division__code", "code"]
        constraints = [
            models.UniqueConstraint(fields=["division", "code"], name="masters_crew_unique_code"),
        ]

    def __str__(self):
        return f"{self.division.code} crew {self.code}"


class RosterAssignment(models.Model):
    """A pattern in force for a division (or one section of it) over a date range.

    A seasonal change is a new assignment from a date; once an assignment has started,
    only its end date can be set, so past days never change."""

    is_structure = True

    pattern = models.ForeignKey(RosterPattern, on_delete=models.PROTECT, related_name="assignments")
    division = models.ForeignKey(
        Division, on_delete=models.PROTECT, related_name="roster_assignments"
    )
    # Empty = the whole division.
    section = models.ForeignKey(
        Section, null=True, blank=True, on_delete=models.PROTECT, related_name="roster_assignments"
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)  # empty = until changed
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["division__code", "-start_date"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="masters_roster_dates_in_order",
            ),
        ]

    def __str__(self):
        where = self.section.code if self.section else self.division.code
        return f"{self.pattern.name} for {where} from {self.start_date}"


class RosterCrew(models.Model):
    """A crew on an assignment, with the day of the cycle it starts on."""

    is_structure = True

    assignment = models.ForeignKey(RosterAssignment, on_delete=models.CASCADE, related_name="crews")
    crew = models.ForeignKey(Crew, on_delete=models.PROTECT, related_name="rosters")
    start_position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["assignment", "crew__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "crew"], name="masters_rostercrew_unique"
            ),
        ]

    def __str__(self):
        return f"{self.crew} from cycle day {self.start_position + 1}"


# --- Currencies and exchange rates (spec 3A.4; backlog P0-11) ---------------------------


class Currency(models.Model):
    """A currency documents can be issued in. LKR is the base and always active."""

    # Settings, not a document.
    is_structure = True

    code = models.CharField(max_length=3, unique=True)  # ISO 4217, e.g. USD
    name = models.CharField(max_length=60)
    symbol = models.CharField(max_length=8, blank=True)
    decimal_places = models.PositiveSmallIntegerField(default=2)
    is_base = models.BooleanField(default=False, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-is_base", "code"]
        verbose_name_plural = "currencies"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code__regex=r"^[A-Z]{3}$"), name="masters_currency_code_format"
            ),
            models.CheckConstraint(
                condition=models.Q(decimal_places__lte=4), name="masters_currency_decimals"
            ),
            models.UniqueConstraint(
                fields=["is_base"],
                condition=models.Q(is_base=True),
                name="masters_currency_one_base",
            ),
        ]

    def __str__(self):
        return self.code


class ExchangeRate(models.Model):
    """LKR for one unit of a currency on a date (rule 11: documents keep the rate of their
    date). `rate` is the one used for conversion; buying and selling are kept when the bank
    quotes both. Once a document has used a rate it cannot change (migration 0005)."""

    is_structure = True

    class Source(models.TextChoices):
        MANUAL = "manual", "Entered"
        IMPORT = "import", "Imported"

    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="rates")
    date = models.DateField()
    rate = models.DecimalField("Rate (LKR)", max_digits=18, decimal_places=6)
    buying = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    selling = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-date", "currency__code"]
        constraints = [
            models.UniqueConstraint(fields=["currency", "date"], name="masters_rate_one_per_day"),
            models.CheckConstraint(condition=models.Q(rate__gt=0), name="masters_rate_positive"),
        ]

    def __str__(self):
        return f"{self.currency.code} {self.rate} on {self.date}"


# --- Quotation approval limits (spec 3A.3; backlog P0-12) -------------------------------


class QuotationLimit(models.Model):
    """A division's quotation limits from a date: a quotation below the minimum margin, or
    above the value, needs the Director's approval before it is sent.

    These are financial controls: a change entered by the Admin takes effect only after the
    Director confirms it. A confirmed limit is never changed or deleted (migration 0006);
    a new limit from a later date replaces it."""

    is_structure = True

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for the Director"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    division = models.ForeignKey(
        Division, on_delete=models.PROTECT, related_name="quotation_limits"
    )
    effective_from = models.DateField()
    min_margin_pct = models.DecimalField("Minimum margin %", max_digits=5, decimal_places=2)
    director_above_lkr = models.DecimalField(
        "Director approves above (LKR)", max_digits=18, decimal_places=2
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        ordering = ["division__code", "-effective_from", "-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(min_margin_pct__gte=0) & models.Q(min_margin_pct__lt=100),
                name="masters_limit_margin_range",
            ),
            models.CheckConstraint(
                condition=models.Q(director_above_lkr__gt=0), name="masters_limit_value_positive"
            ),
            models.UniqueConstraint(
                fields=["division", "effective_from"],
                condition=models.Q(status="confirmed"),
                name="masters_limit_one_confirmed_per_day",
            ),
            models.UniqueConstraint(
                fields=["division"],
                condition=models.Q(status="pending"),
                name="masters_limit_one_pending",
            ),
        ]

    def __str__(self):
        return (
            f"{self.division.code} from {self.effective_from}: margin {self.min_margin_pct}%, "
            f"Director above LKR {self.director_above_lkr}"
        )


# --- Suppliers and payees (spec 4.1; backlog P0-13) -------------------------------------


class Supplier(models.Model):
    """A payee: anyone a voucher can pay (spec 4.1). Its code comes from the number series.

    Bank details live in SupplierBankAccount and only people with the "change bank details"
    action may enter or change them; every change is flagged to the Accountant on the
    payee's next voucher."""

    class Category(models.TextChoices):
        SUPPLIER = "supplier", "Supplier"
        UTILITY = "utility", "Utility"
        BANK_CARD = "bank_card", "Bank or credit card"
        GOVERNMENT = "government", "Government"
        EMPLOYEE = "employee", "Employee"
        OTHER = "other", "Other"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.SUPPLIER)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    contact_person = models.CharField(max_length=100, blank=True)
    contact_phone = models.CharField(max_length=50, blank=True)
    vat_no = models.CharField("VAT registration no.", max_length=50, blank=True)
    tin = models.CharField("TIN", max_length=20, blank=True)
    payment_terms_days = models.PositiveSmallIntegerField(default=30)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="suppliers")
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    # Set whenever bank details change; the Accountant sees it on the next voucher and
    # acknowledges it there (P1-03).
    bank_changed_at = models.DateTimeField(null=True, blank=True, editable=False)
    bank_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    bank_change_acknowledged_at = models.DateTimeField(null=True, blank=True, editable=False)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["vat_no"], name="masters_supplier_vat")]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def bank_change_pending(self) -> bool:
        """Bank details changed since the Accountant last acknowledged them."""
        return self.bank_changed_at is not None and (
            self.bank_change_acknowledged_at is None
            or self.bank_change_acknowledged_at < self.bank_changed_at
        )


class SupplierBankAccount(models.Model):
    # Part of the payee's details, not a document.
    is_structure = True

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="bank_accounts")
    bank_name = models.CharField(max_length=100)
    branch = models.CharField(max_length=100, blank=True)
    account_name = models.CharField(max_length=200)
    account_number = models.CharField(max_length=34)
    swift_code = models.CharField("SWIFT / BIC", max_length=11, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["supplier", "-is_default", "bank_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["supplier"],
                condition=models.Q(is_default=True),
                name="masters_supplier_one_default_account",
            ),
        ]

    def __str__(self):
        return f"{self.bank_name} {self.account_number}"


# --- Company bank and cash accounts, cheque books (backlog P0-14) -----------------------


class CompanyAccount(models.Model):
    """A company bank account, cash box or petty cash float, with its ledger account in the
    chart of accounts (a Bank-type account, P0-15)."""

    is_structure = True

    class Kind(models.TextChoices):
        CURRENT = "current", "Bank current account"
        SAVINGS = "savings", "Bank savings account"
        CASH = "cash", "Cash"
        PETTY_CASH = "petty_cash", "Petty cash"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    bank_name = models.CharField(max_length=100, blank=True)
    branch = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=34, blank=True)
    currency = models.ForeignKey(
        Currency, on_delete=models.PROTECT, related_name="company_accounts"
    )
    # Petty cash: who holds it and the float it is topped up to.
    custodian = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    float_amount = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    division = models.ForeignKey(
        Division, null=True, blank=True, on_delete=models.PROTECT, related_name="company_accounts"
    )
    ledger_account = models.OneToOneField(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="company_account",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["bank_name", "account_number"],
                condition=~models.Q(account_number=""),
                name="masters_companyaccount_unique_number",
            ),
            models.CheckConstraint(
                condition=models.Q(float_amount__isnull=True) | models.Q(float_amount__gt=0),
                name="masters_companyaccount_float_positive",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"

    @property
    def is_bank(self) -> bool:
        return self.kind in (self.Kind.CURRENT, self.Kind.SAVINGS)


class DivisionBankDefault(models.Model):
    """The bank account a division's payments are made from unless another is chosen."""

    is_structure = True

    division = models.OneToOneField(Division, on_delete=models.PROTECT, related_name="bank_default")
    account = models.ForeignKey(
        CompanyAccount, on_delete=models.PROTECT, related_name="default_for"
    )

    def __str__(self):
        return f"{self.division.code}: {self.account.code}"


class ChequeBook(models.Model):
    """A cheque book: the leaf numbers it holds."""

    is_structure = True

    account = models.ForeignKey(
        CompanyAccount, on_delete=models.PROTECT, related_name="cheque_books"
    )
    first_number = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField()
    digits = models.PositiveSmallIntegerField(default=6)  # cheque numbers print with leading zeros
    received_on = models.DateField(default=timezone.localdate)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["account", "first_number"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(last_number__gte=models.F("first_number")),
                name="masters_chequebook_range_in_order",
            ),
        ]

    def __str__(self):
        return f"{self.account.code} {self.first_number}-{self.last_number}"


class ChequeLeaf(models.Model):
    """A cheque number that has been used: issued on a payment, or spoiled. Kept for good."""

    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        SPOILED = "spoiled", "Spoiled"

    book = models.ForeignKey(ChequeBook, on_delete=models.PROTECT, related_name="leaves")
    account = models.ForeignKey(CompanyAccount, on_delete=models.PROTECT, related_name="cheques")
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices)
    reason = models.TextField(blank=True)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    used_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["account", "number"]
        constraints = [
            models.UniqueConstraint(fields=["account", "number"], name="masters_cheque_once"),
        ]

    def __str__(self):
        return f"{self.account.code} cheque {self.number} ({self.status})"
