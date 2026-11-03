"""Cheque register and deposits (backlog P2-14, spec 6 banking).

- Customers' cheques wait in Undeposited funds once their receipt is posted. A deposit slip
  takes some of them to a bank account: Dr the bank, Cr Undeposited funds.
- A cheque is marked cleared when the bank has paid it (ours) or credited it (the
  customer's). A customer's cheque that comes back unpaid is returned on its receipt (sales).
- All three are insert-only (database guard): a mistake is corrected by another document.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Deposit(models.Model):
    """A deposit slip: customers' cheques taken to the bank together."""

    number = models.CharField(max_length=30, unique=True)
    account = models.ForeignKey(
        "masters.CompanyAccount", on_delete=models.PROTECT, related_name="deposits"
    )
    deposit_date = models.DateField()
    slip_no = models.CharField(max_length=50, blank=True)  # the bank's slip number
    total = models.DecimalField(max_digits=18, decimal_places=2)
    journal_entry = models.OneToOneField(
        "accounting.JournalEntry", on_delete=models.PROTECT, related_name="deposit"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-deposit_date", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(total__gt=0), name="banking_deposit_total"),
        ]

    def __str__(self):
        return self.number


class DepositLine(models.Model):
    deposit = models.ForeignKey(Deposit, on_delete=models.PROTECT, related_name="lines")
    receipt = models.OneToOneField(
        "sales.CustomerReceipt", on_delete=models.PROTECT, related_name="deposit_line"
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)  # LKR

    class Meta:
        ordering = ["deposit", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="banking_line_amount"),
        ]

    def __str__(self):
        return f"{self.deposit} {self.receipt}"


class ChequeClearance(models.Model):
    """The bank paid one of our cheques, or credited a customer's cheque we deposited."""

    leaf = models.OneToOneField(
        "masters.ChequeLeaf",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="clearance",
    )
    deposit_line = models.OneToOneField(
        DepositLine, null=True, blank=True, on_delete=models.PROTECT, related_name="clearance"
    )
    cleared_on = models.DateField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-cleared_on", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(leaf__isnull=False, deposit_line__isnull=True)
                | models.Q(leaf__isnull=True, deposit_line__isnull=False),
                name="banking_clearance_one_cheque",
            ),
        ]

    def __str__(self):
        return f"Cleared {self.cleared_on}"


# --- Bank statements (backlog P2-15) ---------------------------------------------------------


class StatementTemplate(models.Model):
    """How one bank's statement file is laid out, kept by the Accountant (no code change for a
    new bank): the column headings of a spreadsheet, or a PDF read line by line."""

    class Kind(models.TextChoices):
        EXCEL = "excel", "Excel (.xlsx)"
        CSV = "csv", "CSV"
        PDF = "pdf", "PDF with text"

    code = models.CharField(max_length=20, unique=True)
    bank_name = models.CharField(max_length=100)
    file_kind = models.CharField(max_length=10, choices=Kind.choices)
    date_format = models.CharField(max_length=20, default="%d/%m/%Y")
    date_column = models.CharField(max_length=60, blank=True, default="Date")
    description_column = models.CharField(max_length=60, blank=True, default="Description")
    reference_column = models.CharField(max_length=60, blank=True)
    out_column = models.CharField(max_length=60, blank=True, default="Debit")
    in_column = models.CharField(max_length=60, blank=True, default="Credit")
    amount_column = models.CharField(max_length=60, blank=True)
    negative_is_out = models.BooleanField(default=True)
    balance_column = models.CharField(max_length=60, blank=True, default="Balance")
    # Checked against a real file from the bank (backlog P2-15).
    checked = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["bank_name", "code"]

    def __str__(self):
        return f"{self.bank_name} ({self.get_file_kind_display()})"


class BankStatement(models.Model):
    """One imported statement file for one of the company's bank accounts."""

    account = models.ForeignKey(
        "masters.CompanyAccount", on_delete=models.PROTECT, related_name="statements"
    )
    template = models.ForeignKey(StatementTemplate, on_delete=models.PROTECT, related_name="+")
    file_name = models.CharField(max_length=200)
    sha256 = models.CharField(max_length=64)
    from_date = models.DateField()
    to_date = models.DateField()
    opening_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    closing_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    skipped = models.PositiveIntegerField(default=0)  # lines already imported before
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    imported_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-to_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "sha256"], name="banking_statement_file_once"
            ),
            models.CheckConstraint(
                condition=models.Q(to_date__gte=models.F("from_date")),
                name="banking_statement_dates",
            ),
        ]

    def __str__(self):
        return f"{self.account.code} {self.from_date}–{self.to_date}"


class BankStatementLine(models.Model):
    """One transaction as the bank printed it. Money out and in are from the company's side:
    a payment or charge is money out, a deposit or interest money in."""

    statement = models.ForeignKey(BankStatement, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(
        "masters.CompanyAccount", on_delete=models.PROTECT, related_name="statement_lines"
    )
    line_no = models.PositiveIntegerField()
    date = models.DateField()
    description = models.CharField(max_length=500, blank=True)
    reference = models.CharField(max_length=60, blank=True)
    money_out = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    money_in = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["statement", "line_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["statement", "line_no"], name="banking_statement_line_no"
            ),
            models.CheckConstraint(
                condition=(models.Q(money_out__gt=0) & models.Q(money_in=0))
                | (models.Q(money_in__gt=0) & models.Q(money_out=0)),
                name="banking_statement_line_one_side",
            ),
        ]

    def __str__(self):
        return f"{self.statement_id}/{self.line_no}"


# --- Bank reconciliation (backlog P2-16) ------------------------------------------------------


class StatementMatch(models.Model):
    """A statement line matched to the journal entry that put the same money through the bank
    account in our books: a payment, deposit, receipt, advance, transfer or journal. `posted`
    marks an entry made from the line itself (bank charges, interest)."""

    line = models.OneToOneField(BankStatementLine, on_delete=models.CASCADE, related_name="match")
    entry = models.OneToOneField(
        "accounting.JournalEntry", on_delete=models.PROTECT, related_name="statement_match"
    )
    posted = models.BooleanField(default=False)
    matched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    matched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["line"]

    def __str__(self):
        return f"{self.line} = {self.entry}"


class BankRule(models.Model):
    """When a statement line's description contains `text`, suggest posting it to `ledger`
    (bank charges, interest, standing orders). Kept by the Accountant."""

    class Direction(models.TextChoices):
        ANY = "any", "Money in or out"
        OUT = "out", "Money out"
        IN = "in", "Money in"

    account = models.ForeignKey(
        "masters.CompanyAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="bank_rules",
    )
    text = models.CharField(max_length=100)
    direction = models.CharField(max_length=3, choices=Direction.choices, default=Direction.ANY)
    ledger = models.ForeignKey("accounting.Account", on_delete=models.PROTECT, related_name="+")
    division = models.ForeignKey(
        "core.Division", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["text"]

    def __str__(self):
        return self.text


class BankReconciliation(models.Model):
    """A month of a bank account reconciled and locked: the statement lines up to its end are
    all in the books and the difference is nil. Its matches never change afterwards."""

    account = models.ForeignKey(
        "masters.CompanyAccount", on_delete=models.PROTECT, related_name="reconciliations"
    )
    period_end = models.DateField()
    bank_balance = models.DecimalField(max_digits=18, decimal_places=2)
    book_balance = models.DecimalField(max_digits=18, decimal_places=2)
    unpresented = models.DecimalField(max_digits=18, decimal_places=2)  # book items not on it
    note = models.TextField(blank=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    done_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-period_end", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["account", "period_end"], name="banking_reconciliation_once"
            ),
        ]

    def __str__(self):
        return f"{self.account} to {self.period_end}"
