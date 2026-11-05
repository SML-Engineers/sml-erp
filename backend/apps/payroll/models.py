"""Payroll and people (Phase 2b, docs/backlog/phase-2b.md)."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Employee(models.Model):
    """A person employed by the company (P2B-01). The employee number never changes; an
    employee who leaves is deactivated, never deleted, so their payroll history stays. The
    salary bank account, like a supplier's, is checked by a second person whenever it changes:
    until then it is not paid to (spec 4.6, 7A)."""

    class Type(models.TextChoices):
        PERMANENT = "permanent", "Permanent"
        PROBATION = "probation", "On probation"
        CONTRACT = "contract", "Contract"
        CASUAL = "casual", "Casual"
        TRAINEE = "trainee", "Trainee"

    number = models.CharField(max_length=20, unique=True)
    full_name = models.CharField(max_length=200)
    name_with_initials = models.CharField(max_length=100, blank=True)
    nic = models.CharField("NIC", max_length=12, unique=True)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.CharField(max_length=300, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    epf_no = models.CharField("EPF number", max_length=20, blank=True)
    etf_no = models.CharField("ETF number", max_length=20, blank=True)
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    section = models.ForeignKey(
        "masters.Section", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    designation = models.CharField(max_length=100, blank=True)
    grade = models.CharField(max_length=30, blank=True)
    employment_type = models.CharField(max_length=12, choices=Type.choices)
    join_date = models.DateField()
    confirmation_date = models.DateField(null=True, blank=True)
    leaving_date = models.DateField(null=True, blank=True)
    leaving_reason = models.CharField(max_length=200, blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="employee",
    )
    # Salary bank account, and its second check.
    bank_name = models.CharField(max_length=100, blank=True)
    bank_branch = models.CharField(max_length=100, blank=True)
    account_name = models.CharField(max_length=200, blank=True)
    account_number = models.CharField(max_length=34, blank=True)
    bank_changed_at = models.DateTimeField(null=True, blank=True)
    bank_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    bank_checked_at = models.DateTimeField(null=True, blank=True)
    bank_checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(leaving_date__isnull=True)
                | models.Q(leaving_date__gte=models.F("join_date")),
                name="payroll_employee_dates",
            ),
        ]

    def __str__(self):
        return f"{self.number} {self.full_name}"

    @property
    def bank_check_pending(self) -> bool:
        return bool(self.bank_changed_at) and (
            self.bank_checked_at is None or self.bank_checked_at < self.bank_changed_at
        )


class PayComponent(models.Model):
    """An earning or a deduction on the payslip (P2B-02), e.g. basic salary, budgetary relief
    allowance, welfare. Each says whether it counts for EPF and ETF and for APIT. Its code
    never changes; one no longer used is deactivated. A payroll keeps the flags it was run
    with (P2B-06), so changing a flag never changes a past payroll (rule 11)."""

    class Kind(models.TextChoices):
        EARNING = "earning", "Earning"
        DEDUCTION = "deduction", "Deduction"

    class Basis(models.TextChoices):
        FIXED = "fixed", "Fixed each month"
        VARIABLE = "variable", "Entered each month"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    basis = models.CharField(max_length=10, choices=Basis.choices, default=Basis.FIXED)
    epf_liable = models.BooleanField("counts for EPF and ETF", default=False)
    apit_taxable = models.BooleanField("taxable for APIT", default=False)
    sort_order = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["kind", "sort_order", "code"]
        constraints = [
            # A deduction is taken from pay; it is neither EPF earnings nor taxable pay.
            models.CheckConstraint(
                condition=models.Q(kind="earning") | models.Q(epf_liable=False, apit_taxable=False),
                name="payroll_component_deduction_flags",
            ),
        ]

    def __str__(self):
        return f"{self.code} {self.name}"


class PayRate(models.Model):
    """An employee's monthly amount of one component from a month on (P2B-02). Never changed:
    a raise is a new row from its month, and earlier months keep the old amount (rule 11). An
    amount of 0 ends the component. A row that has not yet taken effect may be withdrawn."""

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="pay_rates")
    component = models.ForeignKey(PayComponent, on_delete=models.PROTECT, related_name="+")
    effective_from = models.DateField()  # always the 1st of a month
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    reason = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["employee", "component", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "component", "effective_from"], name="payroll_rate_once"
            ),
            models.CheckConstraint(condition=models.Q(amount__gte=0), name="payroll_rate_amount"),
        ]

    def __str__(self):
        return f"{self.employee.number} {self.component.code} {self.effective_from}"


class Holiday(models.Model):
    """A public, bank, mercantile or company holiday (P2B-03). A holiday that has passed is
    never removed or moved (the database refuses), as pay may already depend on it."""

    class Kind(models.TextChoices):
        PUBLIC = "public", "Public holiday"
        BANK = "bank", "Bank holiday"
        MERCANTILE = "mercantile", "Mercantile holiday"
        POYA = "poya", "Full moon Poya day"
        COMPANY = "company", "Company holiday"

    date = models.DateField(unique=True)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"{self.date} {self.name}"


class LeaveType(models.Model):
    """A kind of leave (P2B-03) and how much is granted each calendar year.

    - annual_soe: none in the year of joining; the next year 14, 10, 7 or 4 days by the
      quarter of joining; then the full days (Shop and Office Employees Act, section 6).
    - casual_soe: half a day for each completed month in the year of joining; then the full
      days.
    - fixed: the full days every year.
    - unlimited: no balance kept (no-pay leave, maternity leave, which follow their own rules).
    """

    class Rule(models.TextChoices):
        ANNUAL = "annual_soe", "Annual leave rule (by quarter of joining)"
        CASUAL = "casual_soe", "Casual leave rule (half a day a month in the first year)"
        FIXED = "fixed", "Same days every year"
        UNLIMITED = "unlimited", "No balance kept"

    code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=100)
    rule = models.CharField(max_length=12, choices=Rule.choices)
    days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    paid = models.BooleanField(default=True)
    carry_forward_max = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(days__gte=0, carry_forward_max__gte=0),
                name="payroll_leavetype_days",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def keeps_balance(self) -> bool:
        return self.rule != self.Rule.UNLIMITED


class LeaveGrant(models.Model):
    """Days of leave given to an employee for a calendar year (P2B-03): the year's
    entitlement, days carried forward, or an adjustment with a reason (+ or -). Never changed
    or removed: a correction is another adjustment."""

    class Kind(models.TextChoices):
        ENTITLEMENT = "entitlement", "Entitlement"
        CARRIED = "carried", "Carried forward"
        ADJUSTMENT = "adjustment", "Adjustment"

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="leave_grants")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="+")
    year = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=12, choices=Kind.choices)
    days = models.DecimalField(max_digits=5, decimal_places=1)
    reason = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["employee", "year", "leave_type", "created_at"]
        constraints = [
            # One entitlement and one carry-forward per employee, type and year.
            models.UniqueConstraint(
                fields=["employee", "leave_type", "year", "kind"],
                condition=~models.Q(kind="adjustment"),
                name="payroll_leavegrant_once",
            ),
        ]

    def __str__(self):
        return f"{self.employee.number} {self.leave_type.code} {self.year} {self.days}"


class Leave(models.Model):
    """Leave taken or applied for (P2B-03). HR records leave approved on the leave form; leave
    applied for on the self-service page (P2B-11) waits for HR's approval; leave codes in the
    attendance sheet (P2B-04) are recorded from it. Days count working days (Monday to
    Saturday, not holidays); a single day can be half a day."""

    class Status(models.TextChoices):
        APPLIED = "applied", "Applied for"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    class Source(models.TextChoices):
        HR = "hr", "Recorded by HR"
        APPLIED = "applied", "Applied for by the employee"
        ATTENDANCE = "attendance", "From attendance"

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="leaves")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="+")
    start = models.DateField()
    end = models.DateField()
    half_day = models.BooleanField(default=False)
    days = models.DecimalField(max_digits=5, decimal_places=1)
    reason = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    source = models.CharField(max_length=10, choices=Source.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-start", "employee"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end__gte=models.F("start")), name="payroll_leave_dates"
            ),
            models.CheckConstraint(
                condition=models.Q(half_day=False) | models.Q(end=models.F("start")),
                name="payroll_leave_half_day",
            ),
            models.CheckConstraint(condition=models.Q(days__gt=0), name="payroll_leave_days"),
        ]

    def __str__(self):
        return f"{self.employee.number} {self.leave_type.code} {self.start}"


class AttendanceImport(models.Model):
    """One attendance sheet uploaded (P2B-04): who, when, and the file's fingerprint."""

    file_name = models.CharField(max_length=200)
    sha256 = models.CharField(max_length=64)
    rows = models.PositiveIntegerField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.file_name} {self.created_at:%Y-%m-%d}"


class AttendanceDay(models.Model):
    """An employee's attendance on a date, from the attendance sheet (P2B-04). A later sheet
    replaces the day while its month is open; once HR confirms the month for the division,
    its days never change (database)."""

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="attendance")
    date = models.DateField()
    shift = models.ForeignKey(
        "masters.Shift", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    time_in = models.TimeField(null=True, blank=True)
    time_out = models.TimeField(null=True, blank=True)
    leave_type = models.ForeignKey(
        LeaveType, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    remarks = models.CharField(max_length=200, blank=True)
    worked_minutes = models.PositiveIntegerField(default=0)
    late_minutes = models.PositiveIntegerField(default=0)
    early_minutes = models.PositiveIntegerField(default=0)
    source = models.ForeignKey(AttendanceImport, on_delete=models.PROTECT, related_name="days")

    class Meta:
        ordering = ["employee", "date"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "date"], name="payroll_attendance_once"),
            models.CheckConstraint(
                condition=models.Q(time_in__isnull=True, time_out__isnull=True)
                | models.Q(time_in__isnull=False, time_out__isnull=False),
                name="payroll_attendance_times",
            ),
        ]

    def __str__(self):
        return f"{self.employee.number} {self.date}"


class AttendanceMonth(models.Model):
    """HR's confirmation of a division's attendance for a month (P2B-04): payroll (P2B-06)
    uses only confirmed months. Reopening needs a reason."""

    month = models.DateField()  # the 1st
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    confirmed = models.BooleanField(default=False)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-month", "division"]
        constraints = [
            models.UniqueConstraint(fields=["month", "division"], name="payroll_attmonth_once"),
        ]

    def __str__(self):
        return f"{self.division_id} {self.month:%Y-%m}"
