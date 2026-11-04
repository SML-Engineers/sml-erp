"""Chart of accounts (spec 3, backlog P0-15).

Works like QuickBooks: every account has a fixed account type and an editable detail type,
sub-accounts go to any depth, account numbers are optional. The database refuses deleting an
account that has been used or that the system needs, and keeps a merge final (migration 0001).
"""

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.core.models import Division

from .catalogue import SYSTEM_ROLE_CHOICES, TYPE_CHOICES

NUMBER_REGEX = r"^[A-Z0-9][A-Z0-9.-]{0,19}$"


class DetailType(models.Model):
    """Refines an account type (e.g. Fixed asset → Moulds and tooling). Editable list."""

    is_structure = True

    account_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["account_type", "name"]
        constraints = [
            models.UniqueConstraint(
                "account_type", Lower("name"), name="accounting_detailtype_unique_name"
            ),
        ]

    def __str__(self):
        return self.name


class Account(models.Model):
    # A ledger account is not a document: having accounts does not fix a division's code.
    is_structure = True

    number = models.CharField(max_length=20, blank=True)
    name = models.CharField(max_length=100)
    account_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    detail_type = models.ForeignKey(DetailType, on_delete=models.PROTECT, related_name="accounts")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    description = models.CharField(max_length=500, blank=True)
    default_division = models.ForeignKey(
        Division,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="default_accounts",
    )
    # The tax code proposed when this account is chosen on a document line (P0-20).
    default_tax_code = models.ForeignKey(
        "TaxCode", null=True, blank=True, on_delete=models.PROTECT, related_name="default_for"
    )
    # Set on the accounts the system posts to; such accounts cannot be removed.
    system_role = models.CharField(max_length=30, choices=SYSTEM_ROLE_CHOICES, blank=True)
    is_active = models.BooleanField(default=True)
    # A merged account keeps its posted history (rule 3) and points at the account that
    # replaced it; reports show that history under the remaining account.
    merged_into = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="merged_accounts"
    )
    merged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["number", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["number"],
                condition=~models.Q(number=""),
                name="accounting_account_unique_number",
            ),
            models.CheckConstraint(
                condition=models.Q(number="") | models.Q(number__regex=NUMBER_REGEX),
                name="accounting_account_number_format",
            ),
            # Names are unique within the same parent (spec 3).
            models.UniqueConstraint(
                Lower("name"),
                "parent",
                condition=models.Q(parent__isnull=False),
                name="accounting_account_unique_sub_name",
            ),
            models.UniqueConstraint(
                Lower("name"),
                condition=models.Q(parent__isnull=True),
                name="accounting_account_unique_top_name",
            ),
            models.UniqueConstraint(
                fields=["system_role"],
                condition=~models.Q(system_role=""),
                name="accounting_account_one_per_system_role",
            ),
            models.CheckConstraint(
                condition=~models.Q(parent=models.F("id")), name="accounting_account_not_own_parent"
            ),
            models.CheckConstraint(
                condition=models.Q(merged_into__isnull=True)
                | (
                    models.Q(is_active=False, merged_at__isnull=False, system_role="")
                    & ~models.Q(merged_into=models.F("id"))
                ),
                name="accounting_account_merged_is_inactive",
            ),
        ]

    def __str__(self):
        return f"{self.number} {self.name}".strip()


# --- Journal and periods (backlog P0-16) -------------------------------------------------


class AccountingPeriod(models.Model):
    """One calendar month. A month with no row is open; the Director closes and reopens."""

    is_structure = True

    month = models.DateField(unique=True)  # the first day of the month
    is_closed = models.BooleanField(default=False)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["month"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(month__day=1), name="accounting_period_first_of_month"
            ),
        ]

    def __str__(self):
        return self.month.strftime("%Y-%m")


class JournalEntry(models.Model):
    """A posted journal entry. Only posted entries are stored, and they never change:
    corrections are reversing entries (rule 3). Drafts live on their source documents."""

    number = models.CharField(max_length=40, unique=True)
    entry_date = models.DateField()
    # Where the entry comes from: "manual", "voucher", "payment", "reversal", …
    source_type = models.CharField(max_length=30)
    source_id = models.CharField(max_length=40, blank=True)
    narration = models.CharField(max_length=500)
    reversal_of = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by"
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    posted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-entry_date", "-id"]
        verbose_name_plural = "journal entries"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(reversal_of=models.F("id")),
                name="accounting_entry_not_own_reversal",
            ),
        ]

    def __str__(self):
        return self.number


class JournalLine(models.Model):
    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="journal_lines")
    division = models.ForeignKey(
        Division, null=True, blank=True, on_delete=models.PROTECT, related_name="journal_lines"
    )
    supplier = models.ForeignKey(
        "masters.Supplier",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="journal_lines",
    )
    # The customer on an accounts receivable line (P2-05): customer balances, statements
    # and aging are read from these lines.
    customer = models.ForeignKey(
        "masters.Customer",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="journal_lines",
    )
    description = models.CharField(max_length=500, blank=True)
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        ordering = ["entry", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["entry", "line_no"], name="accounting_line_unique_no"),
            # One side only, never negative (rule 1 and 2).
            models.CheckConstraint(
                condition=(models.Q(debit__gt=0) & models.Q(credit=0))
                | (models.Q(debit=0) & models.Q(credit__gt=0)),
                name="accounting_line_one_side_positive",
            ),
        ]

    def __str__(self):
        return f"{self.entry_id}/{self.line_no}"


# --- Manual journals (backlog P2-01) ------------------------------------------------------


class ManualJournal(models.Model):
    """A journal the Accountant types in. It is a draft until approved; approval posts it as
    a journal entry (above), which never changes. Once sent for approval the database refuses
    changing it, and only a draft is deleted (migration 0008)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING_APPROVAL = "awaiting_approval", "Waiting for approval"
        POSTED = "posted", "Approved and posted"
        REJECTED = "rejected", "Rejected"

    number = models.CharField(max_length=30, unique=True)
    entry_date = models.DateField()
    narration = models.CharField(max_length=500)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    journal_entry = models.OneToOneField(
        JournalEntry,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manual_journal",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    # Made from a recurring journal (P2-02), and an accrual reversed on this date.
    recurring = models.ForeignKey(
        "RecurringJournal",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="journals",
    )
    reverse_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-entry_date", "-number"]

    def __str__(self):
        return self.number


class ManualJournalLine(models.Model):
    journal = models.ForeignKey(ManualJournal, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+")
    division = models.ForeignKey(
        Division, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    supplier = models.ForeignKey(
        "masters.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    description = models.CharField(max_length=500, blank=True)
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        ordering = ["journal", "line_no"]
        constraints = [
            models.UniqueConstraint(fields=["journal", "line_no"], name="accounting_mj_line_no"),
            models.CheckConstraint(
                condition=models.Q(debit__gte=0) & models.Q(credit__gte=0),
                name="accounting_mj_line_not_negative",
            ),
        ]

    def __str__(self):
        return f"{self.journal_id}/{self.line_no}"


class ManualJournalAttachment(models.Model):
    """A supporting document (PDF, JPG or PNG)."""

    journal = models.ForeignKey(ManualJournal, on_delete=models.PROTECT, related_name="attachments")
    file = models.FileField(upload_to="journals/%Y/%m/")
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


# --- Recurring journals (backlog P2-02) --------------------------------------------------


class RecurringJournal(models.Model):
    """A journal made again every month, quarter or year: on its date a draft manual journal
    is made from it, which its owner checks and sends for approval as usual."""

    class Frequency(models.TextChoices):
        MONTHLY = "monthly", "Every month"
        QUARTERLY = "quarterly", "Every quarter"
        YEARLY = "yearly", "Every year"

    name = models.CharField(max_length=100)
    narration = models.CharField(max_length=400)
    frequency = models.CharField(max_length=10, choices=Frequency.choices)
    # 1 to 28, or 31 for the last day of the month.
    day_of_month = models.PositiveSmallIntegerField()
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    next_date = models.DateField()
    # An accrual: the journal is reversed on the first day of the next month.
    reverse_next_month = models.BooleanField(default=False)
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
                condition=(models.Q(day_of_month__gte=1) & models.Q(day_of_month__lte=28))
                | models.Q(day_of_month=31),
                name="accounting_recurring_day",
            ),
        ]

    def __str__(self):
        return self.name


class RecurringJournalLine(models.Model):
    recurring = models.ForeignKey(RecurringJournal, on_delete=models.CASCADE, related_name="lines")
    line_no = models.PositiveSmallIntegerField()
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+")
    division = models.ForeignKey(
        Division, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    supplier = models.ForeignKey(
        "masters.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    description = models.CharField(max_length=500, blank=True)
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        ordering = ["recurring", "line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["recurring", "line_no"], name="accounting_recurring_line_no"
            ),
        ]

    def __str__(self):
        return f"{self.recurring_id}/{self.line_no}"


# --- Taxes (backlog P0-20) ---------------------------------------------------------------

TAX_CODE_REGEX = r"^[A-Z0-9][A-Z0-9-]{0,19}$"


class TaxComponent(models.Model):
    """One tax, e.g. VAT, SSCL or withholding tax, with its dated rates and the ledger
    accounts it is recorded in. Kept by the Accountant, as QuickBooks tax items."""

    is_structure = True

    class Kind(models.TextChoices):
        CHARGED = "charged", "Charged on invoices and bills (VAT, SSCL…)"
        WITHHELD = "withheld", "Withheld from payments (WHT…)"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.CHARGED)
    # Sales: the tax collected and owed to the government. Purchases: the tax paid that can
    # be claimed back; empty means it is part of the cost of what was bought.
    sales_account = models.ForeignKey(
        Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    purchase_account = models.ForeignKey(
        Account, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    is_active = models.BooleanField(default=True)
    # The name printed on quotations and invoices when it differs from the code: the SSCL
    # of manufactured goods (SSCL-M) prints as "SSCL" (P16-20).
    printed_as = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code__regex=TAX_CODE_REGEX), name="accounting_taxcomponent_code"
            ),
        ]

    def __str__(self):
        return self.code

    @property
    def label(self) -> str:
        return self.printed_as or self.code


class TaxRate(models.Model):
    """A component's rate from a date (rule 11). A rate in force on a used tax is fixed.

    A change to a tax in use is proposed (by the Admin or the Accountant) and takes effect
    only when the Director confirms it (owner, 2 Nov 2026; P16-20)."""

    is_structure = True

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting for the Director"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    component = models.ForeignKey(TaxComponent, on_delete=models.PROTECT, related_name="rates")
    effective_from = models.DateField()
    rate = models.DecimalField(max_digits=7, decimal_places=4)  # percent, e.g. 18.0000
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED)
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        ordering = ["component", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["component", "effective_from"],
                condition=models.Q(status__in=["pending", "confirmed"]),
                name="accounting_taxrate_one_per_day",
            ),
            models.UniqueConstraint(
                fields=["component"],
                condition=models.Q(status="pending"),
                name="accounting_taxrate_one_pending",
            ),
            models.CheckConstraint(
                condition=models.Q(rate__gte=0) & models.Q(rate__lte=100),
                name="accounting_taxrate_percent",
            ),
        ]

    def __str__(self):
        return f"{self.component_id} {self.rate}% from {self.effective_from}"


class TaxCode(models.Model):
    """What is chosen on a document line, e.g. "VAT 18% + SSCL", "Exempt": the components
    it applies, in order, each on the net amount or on the net plus the taxes before it."""

    is_structure = True

    class Use(models.TextChoices):
        BOTH = "both", "Sales and purchases"
        SALES = "sales", "Sales only"
        PURCHASES = "purchases", "Purchases only"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True)
    use = models.CharField(max_length=10, choices=Use.choices, default=Use.BOTH)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    first_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code__regex=TAX_CODE_REGEX), name="accounting_taxcode_code"
            ),
        ]

    def __str__(self):
        return self.code


class TaxCodeLine(models.Model):
    is_structure = True

    class Base(models.TextChoices):
        NET = "net", "On the net amount"
        NET_AND_TAX = "net_and_tax", "On the net amount plus the taxes above"

    tax_code = models.ForeignKey(TaxCode, on_delete=models.CASCADE, related_name="lines")
    sequence = models.PositiveSmallIntegerField()
    component = models.ForeignKey(TaxComponent, on_delete=models.PROTECT, related_name="in_codes")
    base = models.CharField(max_length=12, choices=Base.choices, default=Base.NET)
    # The share of the base the tax is charged on, e.g. SSCL on 85% of a manufacturer's
    # turnover: 2.5% x 85% = 2.125% (P16-17).
    portion_pct = models.DecimalField(max_digits=5, decimal_places=2, default=100)

    class Meta:
        ordering = ["tax_code", "sequence"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(portion_pct__gt=0) & models.Q(portion_pct__lte=100),
                name="accounting_taxcodeline_portion_range",
            ),
            models.UniqueConstraint(
                fields=["tax_code", "sequence"], name="accounting_taxcodeline_sequence"
            ),
            models.UniqueConstraint(
                fields=["tax_code", "component"], name="accounting_taxcodeline_component_once"
            ),
        ]

    def __str__(self):
        return f"{self.tax_code_id}/{self.sequence}"


# --- Month-end revaluation (backlog P2-21) ---------------------------------------------------


class Revaluation(models.Model):
    """A month's revaluation of what is open in foreign currencies, at the month-end rate:
    worked out as a draft for the Accountant to check, then posted. Receivables and payables
    go to Unrealised exchange gain or loss and are reversed on the first day of the next
    month; bank and cash balances go to Exchange gain or Exchange loss and stay. Posted, it
    never changes (database guard)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Worked out, to check"
        POSTED = "posted", "Posted"

    month_end = models.DateField(unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    # Net differences in LKR: a gain is positive, a loss negative.
    open_items_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    balances_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    journal_entry = models.OneToOneField(
        JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reversal_entry = models.OneToOneField(
        JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    balances_entry = models.OneToOneField(
        JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    prepared_at = models.DateTimeField(default=timezone.now)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-month_end"]

    def __str__(self):
        return f"Revaluation {self.month_end:%B %Y}"


class RevaluationLine(models.Model):
    """One open invoice, or one bank or cash account, revalued: what is open in its currency,
    what the books carry in LKR, the month-end rate and the difference (a gain positive)."""

    class Kind(models.TextChoices):
        RECEIVABLE = "receivable", "Customer invoice"
        PAYABLE = "payable", "Supplier invoice"
        BALANCE = "balance", "Bank or cash balance"

    revaluation = models.ForeignKey(Revaluation, on_delete=models.CASCADE, related_name="lines")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    document = models.CharField(max_length=60)  # invoice number, or the account's code
    link = models.CharField(max_length=100, blank=True)
    customer = models.ForeignKey(
        "masters.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    supplier = models.ForeignKey(
        "masters.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    company_account = models.ForeignKey(
        "masters.CompanyAccount", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    division = models.ForeignKey(Division, on_delete=models.PROTECT, related_name="+")
    currency = models.ForeignKey("masters.Currency", on_delete=models.PROTECT, related_name="+")
    open_amount = models.DecimalField(max_digits=18, decimal_places=2)  # in the currency
    carried_lkr = models.DecimalField(max_digits=18, decimal_places=2)
    rate = models.DecimalField(max_digits=18, decimal_places=6)
    rate_date = models.DateField()
    revalued_lkr = models.DecimalField(max_digits=18, decimal_places=2)
    difference = models.DecimalField(max_digits=18, decimal_places=2)
    # Bank balances: where the balance in the account's currency came from.
    balance_from = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["revaluation", "kind", "document", "id"]

    def __str__(self):
        return f"{self.document} {self.difference}"


# --- Budgets (backlog P2-22) -----------------------------------------------------------------


class Budget(models.Model):
    """A financial year's budget by account, division and month. The Accountant prepares it
    (typed or imported from Excel) and the Director approves it. An approved budget never
    changes: a revision is a new version, which replaces it once approved (database guard)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING_APPROVAL = "awaiting_approval", "Awaiting approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        REPLACED = "replaced", "Replaced by a later version"

    year_start = models.DateField()  # the first day of the financial year
    version = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.CharField(max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-year_start", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["year_start", "version"], name="accounting_budget_version_once"
            ),
            models.UniqueConstraint(
                fields=["year_start"],
                condition=models.Q(status="approved"),
                name="accounting_budget_one_approved",
            ),
            models.UniqueConstraint(
                fields=["year_start"],
                condition=models.Q(status__in=["draft", "awaiting_approval"]),
                name="accounting_budget_one_open",
            ),
        ]

    def __str__(self):
        return f"Budget {self.year_start:%Y-%m} v{self.version}"


class BudgetLine(models.Model):
    """The amount budgeted for an account and division in a month, in LKR, as a positive
    amount for income and costs alike (a negative one only where the account is expected to
    go the other way)."""

    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="+")
    division = models.ForeignKey(Division, on_delete=models.PROTECT, related_name="+")
    month = models.DateField()  # the first day of the month
    amount = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["budget", "account", "division", "month"]
        constraints = [
            models.UniqueConstraint(
                fields=["budget", "account", "division", "month"],
                name="accounting_budgetline_once",
            ),
            models.CheckConstraint(
                condition=~models.Q(amount=0), name="accounting_budgetline_not_zero"
            ),
        ]

    def __str__(self):
        return f"{self.account_id}/{self.division_id} {self.month:%Y-%m} {self.amount}"
