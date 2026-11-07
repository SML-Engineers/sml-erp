"""Payroll and people (Phase 2b, docs/backlog/phase-2b.md)."""

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Employee(models.Model):
    """A person employed by the company (P2B-01). The employee number never changes; an
    employee who leaves is deactivated, never deleted, so their payroll history stays. The
    salary bank account, like a supplier's, is checked by a second person whenever it changes:
    until then it is not paid to (spec 4.6, 7A)."""

    class Category(models.TextChoices):
        """The labour law that applies (P2B-16; owner, 5 Nov 2026): office staff under the
        Shop and Office Employees Act, factory staff under a Wages Board."""

        SHOP_OFFICE = "shop_office", "Shop and Office"
        WAGES_BOARD = "wages_board", "Wages Board"

    class Type(models.TextChoices):
        PERMANENT = "permanent", "Permanent"
        PROBATION = "probation", "On probation"
        CONTRACT = "contract", "Contract"
        CASUAL = "casual", "Casual"
        TRAINEE = "trainee", "Trainee"

    class PhoneClock(models.TextChoices):
        """Whether the employee may clock in and out from the phone (P2B-12)."""

        OFF = "off", "Not used"
        ANYWHERE = "anywhere", "From anywhere"
        SITES = "sites", "Only at a site"

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
    # The employee's ID on the fingerprint machine (P2B-21): its attendance file names
    # people by this number.
    device_id = models.CharField("Fingerprint ID", max_length=20, blank=True)
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    section = models.ForeignKey(
        "masters.Section", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    designation = models.CharField(max_length=100, blank=True)
    grade = models.CharField(max_length=30, blank=True)
    employment_type = models.CharField(max_length=12, choices=Type.choices)
    category = models.CharField(
        max_length=12, choices=Category.choices, default=Category.SHOP_OFFICE
    )
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
    # Phone punch clock (P2B-12): set by HR; the location is checked only with the employee's
    # own consent, given and withdrawn on their self-service page.
    phone_clock = models.CharField(max_length=10, choices=PhoneClock.choices, default="off")
    location_consent_at = models.DateTimeField(null=True, blank=True)
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
            models.UniqueConstraint(
                fields=["device_id"],
                condition=~models.Q(device_id=""),
                name="payroll_employee_device_id_once",
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
    # An allowance: an employee has at most four at a time (owner, 5 Nov 2026; P2B-17).
    is_allowance = models.BooleanField(default=False)
    # Part of the "monthly pay" the day rate (÷ 30) and the hourly rate (÷ the work rule's
    # divisor) are worked out from (P2B-06; owner, follow-up 1: basic + fixed allowances).
    in_day_rate = models.BooleanField(default=False)
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
    # The employee's own EPF/ETF and APIT marks for this component (P2B-17; owner, 5 Nov 2026,
    # follow-up 7); empty = the component's marks.
    epf_liable = models.BooleanField(null=True, blank=True)
    apit_taxable = models.BooleanField(null=True, blank=True)
    # The approved pay change that brought it (P2B-17); empty for amounts entered before.
    change = models.ForeignKey(
        "PayChange", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
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
    - after_joining: none in the year of joining, then the full days (Wages Board annual
      leave, owner 5 Nov 2026).
    - fixed: the full days every year.
    - unlimited: no balance kept (no-pay leave, maternity leave, which follow their own rules).

    Wages Board employees (P2B-16) follow `wb_rule` and `wb_days` where they are set, otherwise
    the same rule and days. `max_days` limits one leave (maternity: 84 working days).
    """

    class Rule(models.TextChoices):
        ANNUAL = "annual_soe", "Annual leave rule (by quarter of joining)"
        CASUAL = "casual_soe", "Casual leave rule (half a day a month in the first year)"
        AFTER_JOINING = "after_joining", "None in the year of joining, then the full days"
        FIXED = "fixed", "Same days every year"
        UNLIMITED = "unlimited", "No balance kept"

    code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=100)
    rule = models.CharField(max_length=13, choices=Rule.choices)
    days = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    wb_rule = models.CharField(max_length=13, choices=Rule.choices, blank=True)
    wb_days = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    max_days = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
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

    def rule_for(self, category: str) -> tuple[str, Decimal]:
        """The rule and days for an employee of `category` (P2B-16)."""
        if category == Employee.Category.WAGES_BOARD:
            return self.wb_rule or self.rule, (self.days if self.wb_days is None else self.wb_days)
        return self.rule, self.days


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

    class Kind(models.TextChoices):
        SHEET = "sheet", "Excel sheet"
        PUNCHES = "punches", "Phone punches"
        DEVICE = "device", "Fingerprint machine"

    kind = models.CharField(max_length=10, choices=Kind.choices, default="sheet")
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


class DetailChange(models.Model):
    """An employee's request to change their own contact or salary account details (P2B-20),
    made on the self-service page. HR approves or rejects it (never the employee themselves);
    a new salary account then still waits for the Director's check (P2B-01). Decided requests
    never change, and none is ever deleted (database)."""

    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting for HR"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="detail_changes")
    wanted = models.JSONField()  # the new values asked for
    before = models.JSONField()  # the values when asked
    note = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default="waiting")
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
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.employee.number} {self.created_at:%Y-%m-%d}"


class PunchSite(models.Model):
    """A place where staff may clock in from the phone when HR limits them to sites (P2B-12):
    a point and a radius. Never deleted (rule 9); deactivated instead."""

    name = models.CharField(max_length=100, unique=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    radius_m = models.PositiveIntegerField(default=200)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180
                ),
                name="payroll_punchsite_point",
            ),
            models.CheckConstraint(
                condition=models.Q(radius_m__gte=20, radius_m__lte=5000),
                name="payroll_punchsite_radius",
            ),
        ]

    def __str__(self):
        return self.name


class Punch(models.Model):
    """One clock-in or clock-out from the phone (P2B-12), at the server's time, never the
    phone's. Insert-only (database); HR brings them into attendance per pay month, and a wrong
    day is put right with the attendance sheet."""

    class Kind(models.TextChoices):
        IN = "in", "In"
        OUT = "out", "Out"

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="punches")
    kind = models.CharField(max_length=3, choices=Kind.choices)
    at = models.DateTimeField(default=timezone.now)
    # Only when the location was checked (limited to sites, with consent).
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    accuracy_m = models.PositiveIntegerField(null=True, blank=True)
    site = models.ForeignKey(
        PunchSite, null=True, blank=True, on_delete=models.PROTECT, related_name="punches"
    )
    distance_m = models.PositiveIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["employee", "at"]
        indexes = [models.Index(fields=["employee", "at"], name="payroll_punch_at")]

    def __str__(self):
        return f"{self.employee.number} {self.kind} {self.at:%Y-%m-%d %H:%M}"


class PayPeriodRule(models.Model):
    """The day a pay period starts, from a pay month on (P2B-15; rule 11). Owner, 5 Nov 2026:
    the 21st to the 20th. Pay month M starts on `start_day` of the month before M (1 = the
    calendar month); it ends the day before pay month M+1 starts (apps.payroll.periods)."""

    effective_from = models.DateField(unique=True)  # the 1st of a pay month
    start_day = models.PositiveSmallIntegerField(default=21)
    reason = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-effective_from"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_day__gte=1, start_day__lte=28),
                name="payroll_payperiod_day",
            ),
        ]

    def __str__(self):
        return f"day {self.start_day} from {self.effective_from}"


class WorkRule(models.Model):
    """A division's working-time and overtime rules from a month on (P2B-05; rule 11: a new
    rule is a new row, earlier months keep theirs). Defaults (backlog question 5): 8 hours a
    day; overtime 1.5 times on working days, 2 times on Sundays and holidays."""

    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    effective_from = models.DateField()  # the 1st of a month
    normal_day_minutes = models.PositiveSmallIntegerField(default=480)
    grace_minutes = models.PositiveSmallIntegerField(default=10)
    short_leaves_per_month = models.PositiveSmallIntegerField(default=2)
    short_leave_minutes = models.PositiveSmallIntegerField(default=90)
    # Owner, 5 Nov 2026: short leave is paid for Shop and Office staff; for Wages Board staff
    # each one costs a quarter of a day's pay (P2B-16).
    short_leave_paid_wb = models.BooleanField(default=False)
    ot_min_minutes = models.PositiveSmallIntegerField(default=30)
    ot_step_minutes = models.PositiveSmallIntegerField(default=15)
    rate_working_day = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("1.50"))
    rate_sunday = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("2.00"))
    rate_holiday = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("2.00"))
    hourly_divisor = models.PositiveSmallIntegerField(default=240)
    reason = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["division", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["division", "effective_from"], name="payroll_workrule_once"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    normal_day_minutes__gt=0,
                    ot_step_minutes__gt=0,
                    hourly_divisor__gt=0,
                    rate_working_day__gte=1,
                    rate_sunday__gte=1,
                    rate_holiday__gte=1,
                ),
                name="payroll_workrule_values",
            ),
        ]

    def __str__(self):
        return f"{self.division_id} from {self.effective_from}"


class OvertimeCheck(models.Model):
    """An employee's month of overtime, short time and no-pay as checked by the section's
    supervisor or the Director (P2B-05), kept as checked: payroll (P2B-06) pays these figures.
    Never changed; reopening the attendance month voids it."""

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="+")
    month = models.DateField()
    rule = models.ForeignKey(WorkRule, on_delete=models.PROTECT, related_name="+")
    ot_working_minutes = models.PositiveIntegerField()
    ot_sunday_minutes = models.PositiveIntegerField()
    ot_holiday_minutes = models.PositiveIntegerField()
    short_minutes = models.PositiveIntegerField()
    nopay_minutes = models.PositiveIntegerField()
    nopay_days = models.DecimalField(max_digits=4, decimal_places=1)
    # Wages Board short leaves that cost a quarter of a day's pay each (P2B-16).
    unpaid_short_leaves = models.PositiveSmallIntegerField(default=0)
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    checked_at = models.DateTimeField(default=timezone.now)
    voided = models.BooleanField(default=False)

    class Meta:
        ordering = ["-month", "employee"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "month"],
                condition=models.Q(voided=False),
                name="payroll_otcheck_once",
            ),
        ]

    def __str__(self):
        return f"{self.employee.number} {self.month:%Y-%m}"


class SettingFields(models.Model):
    """An employee's own settings (P2B-17; owner, 5 Nov 2026): empty means the default (the
    division's work rule, the category's leave)."""

    class Apit(models.TextChoices):
        PRIMARY = "primary", "Primary employment (IRD tables)"
        SECONDARY = "secondary", "Secondary employment (IRD tables)"

    normal_day_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    grace_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    rate_working_day = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    rate_sunday = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    rate_holiday = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    annual_leave_days = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    casual_leave_days = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    apit = models.CharField(max_length=10, choices=Apit.choices, default=Apit.PRIMARY)

    class Meta:
        abstract = True


SETTING_FIELDS = (
    "normal_day_minutes",
    "grace_minutes",
    "rate_working_day",
    "rate_sunday",
    "rate_holiday",
    "annual_leave_days",
    "casual_leave_days",
    "apit",
)


class PayChange(SettingFields):
    """A new employee's pay settings, or a change to them (P2B-17; owner, 5 Nov 2026): HR
    prepares it, the Director approves it (approval engine, "pay_change"), and only then do
    its amounts and settings take effect, from the pay month `effective_from`. The person who
    prepared it never approves it (rule 5). Rejected or withdrawn, it changes nothing."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING = "awaiting", "Waiting for the Director"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="pay_changes")
    effective_from = models.DateField()  # the 1st of a pay month
    is_new_employee = models.BooleanField(default=False)
    # Whether the change sets the employee's settings (otherwise only amounts).
    has_settings = models.BooleanField(default=False)
    reason = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.employee.number} pay change from {self.effective_from}"


class PayChangeLine(models.Model):
    """One amount in a pay change: the new monthly amount of a component (0 ends it), with the
    employee's own EPF/APIT marks if they differ from the component's."""

    change = models.ForeignKey(PayChange, on_delete=models.CASCADE, related_name="lines")
    component = models.ForeignKey(PayComponent, on_delete=models.PROTECT, related_name="+")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    epf_liable = models.BooleanField(null=True, blank=True)
    apit_taxable = models.BooleanField(null=True, blank=True)

    class Meta:
        ordering = ["component__kind", "component__sort_order", "component__code"]
        constraints = [
            models.UniqueConstraint(fields=["change", "component"], name="payroll_change_line"),
            models.CheckConstraint(
                condition=models.Q(amount__gte=0), name="payroll_change_line_amount"
            ),
        ]

    def __str__(self):
        return f"{self.change_id} {self.component_id} {self.amount}"


def setting_on(employee, day):
    """The employee's approved settings in force on `day` (P2B-17), or None (all defaults)."""
    return (
        EmployeeSetting.objects.filter(employee=employee, effective_from__lte=day)
        .order_by("-effective_from")
        .first()
    )


class EmployeeSetting(SettingFields):
    """An employee's approved settings from a pay month on (P2B-17). Never changed; one that
    has not yet taken effect is replaced by a later approved change for the same month."""

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="settings")
    effective_from = models.DateField()
    change = models.ForeignKey(PayChange, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["employee", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "effective_from"], name="payroll_setting_once"
            ),
        ]

    def __str__(self):
        return f"{self.employee_id} settings from {self.effective_from}"


# --- The payroll (P2B-06) -----------------------------------------------------------------------


class StatutoryRate(models.Model):
    """EPF and ETF rates from a date (rule 11): employee EPF 8%, employer EPF 12%, ETF 3%."""

    effective_from = models.DateField(unique=True)
    epf_employee = models.DecimalField(max_digits=5, decimal_places=2)
    epf_employer = models.DecimalField(max_digits=5, decimal_places=2)
    etf = models.DecimalField(max_digits=5, decimal_places=2)
    reason = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-effective_from"]

    def __str__(self):
        return f"EPF and ETF rates from {self.effective_from}"


class TaxTable(models.Model):
    """An IRD APIT table from a date (rule 11): the monthly bands of Table 01 (primary
    employment) or Table 07 (secondary employment). Tax = earnings x rate - constant, in the
    first band whose upper limit the month's taxable earnings do not pass."""

    class Kind(models.TextChoices):
        PRIMARY = "primary", "Table 01: primary employment"
        SECONDARY = "secondary", "Table 07: secondary employment"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    effective_from = models.DateField()
    reason = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["kind", "-effective_from"]
        constraints = [
            models.UniqueConstraint(fields=["kind", "effective_from"], name="payroll_tax_once"),
        ]

    def __str__(self):
        return f"{self.kind} from {self.effective_from}"


class TaxBand(models.Model):
    table = models.ForeignKey(TaxTable, on_delete=models.CASCADE, related_name="bands")
    up_to = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    rate = models.DecimalField(max_digits=5, decimal_places=2)  # percent
    constant = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        ordering = ["table", "up_to"]  # PostgreSQL puts the open top band last

    def __str__(self):
        return f"up to {self.up_to}: {self.rate}% - {self.constant}"


class PayrollRun(models.Model):
    """A division's payroll for a pay month (P2B-06): HR prepares it from confirmed attendance,
    checked overtime and approved pay settings; the Director approves it (never the person who
    prepared it, rule 5); then it is locked (database)."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING = "awaiting", "Waiting for the Director"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="+")
    month = models.DateField()  # the 1st of the pay month
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    statutory = models.ForeignKey(StatutoryRate, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    worked_out_at = models.DateTimeField(default=timezone.now)
    approved_at = models.DateTimeField(null=True, blank=True)
    # Given on approval (P2B-07): the number (number series "payroll", rule 10) and the
    # journal entry that posted it.
    number = models.CharField(max_length=30, blank=True)
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-month", "division"]
        constraints = [
            models.UniqueConstraint(
                fields=["division", "month"],
                condition=~models.Q(status="rejected"),
                name="payroll_run_once",
            ),
        ]

    def __str__(self):
        return f"{self.division} payroll {self.month:%Y-%m}"


class PayrollLine(models.Model):
    """One employee in a payroll: the totals; the figures behind them are its items."""

    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="+")
    days_employed = models.PositiveSmallIntegerField()
    days_in_period = models.PositiveSmallIntegerField()
    day_rate = models.DecimalField(max_digits=18, decimal_places=2)
    hourly_rate = models.DecimalField(max_digits=18, decimal_places=2)
    gross = models.DecimalField(max_digits=18, decimal_places=2)
    epf_earnings = models.DecimalField(max_digits=18, decimal_places=2)
    apit_earnings = models.DecimalField(max_digits=18, decimal_places=2)
    epf_employee = models.DecimalField(max_digits=18, decimal_places=2)
    epf_employer = models.DecimalField(max_digits=18, decimal_places=2)
    etf = models.DecimalField(max_digits=18, decimal_places=2)
    apit = models.DecimalField(max_digits=18, decimal_places=2)
    deductions = models.DecimalField(max_digits=18, decimal_places=2)
    net = models.DecimalField(max_digits=18, decimal_places=2)
    basic = models.DecimalField(max_digits=18, decimal_places=2)
    # Gratuity (P2B-19): the liability at the end of the period and this month's provision
    # (the change since the employee's previous approved payroll; negative releases it).
    gratuity_years = models.PositiveSmallIntegerField(default=0)
    gratuity_liability = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    gratuity_charge = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        ordering = ["run", "employee__number"]
        constraints = [
            models.UniqueConstraint(fields=["run", "employee"], name="payroll_line_once"),
        ]

    def __str__(self):
        return f"{self.run} {self.employee.number}"


class PayrollItem(models.Model):
    """One figure on a payroll line, with where it came from ("basis")."""

    class Kind(models.TextChoices):
        EARNING = "earning", "Earning"
        DEDUCTION = "deduction", "Deduction"
        EMPLOYER = "employer", "Paid by the employer"

    line = models.ForeignKey(PayrollLine, on_delete=models.CASCADE, related_name="items")
    # The advance or loan this deduction recovers (P2B-10).
    credit = models.ForeignKey(
        "StaffCredit", null=True, blank=True, on_delete=models.PROTECT, related_name="recoveries"
    )
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    basis = models.CharField(max_length=300, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["line", "sort_order", "id"]

    def __str__(self):
        return f"{self.code} {self.amount}"


class PayrollEntry(models.Model):
    """An amount HR types in for one pay month (a component "entered each month", e.g. an
    incentive or an advance recovery), used when the payroll is worked out."""

    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="entries")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="+")
    component = models.ForeignKey(PayComponent, on_delete=models.PROTECT, related_name="+")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["run", "employee__number", "component__sort_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "employee", "component"], name="payroll_entry_once"
            ),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payroll_entry_amount"),
        ]

    def __str__(self):
        return f"{self.run} {self.employee_id} {self.component_id} {self.amount}"


class StaffCredit(models.Model):
    """A salary advance or a staff loan (P2B-10; owner, 5 Nov 2026). HR records it, the
    Director approves it (never the person who recorded it), the Clerk pays it by a voucher
    coded to Staff loans and advances, and the payroll recovers it: an advance in full in its
    pay month, a loan in equal monthly instalments of (amount + interest) / months from its
    first pay month. The employee always keeps more than 40% of the basic salary: a recovery
    that would take more waits for the next month."""

    class Kind(models.TextChoices):
        ADVANCE = "advance", "Salary advance"
        LOAN = "loan", "Loan"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        AWAITING = "awaiting", "Waiting for the Director"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="credits")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    number = models.CharField(max_length=30, blank=True)  # given on approval (rule 10)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    interest = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    months = models.PositiveSmallIntegerField(default=1)
    first_month = models.DateField()  # the 1st of the pay month recovery starts
    reason = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0, interest__gte=0, months__gte=1),
                name="payroll_credit_amounts",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.number or self.pk} {self.employee_id}"

    @property
    def total(self):
        return self.amount + self.interest

    @property
    def instalment(self):
        return (self.total / self.months).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class GratuitySetting(models.Model):
    """An employee's gratuity settings from a pay month on (P2B-19; owner, follow-up 9): the
    Accountant enters them, the Director approves (approval engine, "gratuity_setting"). Never
    less than the Payment of Gratuity Act No. 12 of 1983 (half a month's wage per completed
    year once 5 years are completed, service from joining). Without one, the Act applies.
    Decided settings never change; none is deleted (database)."""

    class Status(models.TextChoices):
        AWAITING = "awaiting", "Waiting for the Director"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    employee = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="gratuity_settings"
    )
    effective_from = models.DateField()  # the 1st of a pay month
    service_from = models.DateField()
    months_per_year = models.DecimalField(max_digits=4, decimal_places=2)
    after_years = models.PositiveSmallIntegerField()
    reason = models.CharField(max_length=200)
    status = models.CharField(max_length=10, choices=Status.choices, default="awaiting")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["employee", "-effective_from", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(after_years__lte=5, months_per_year__gte=Decimal("0.5")),
                name="payroll_gratuity_not_below_act",
            ),
        ]

    def __str__(self):
        return f"{self.employee_id} gratuity from {self.effective_from}"


# --- Taking over from the old payroll (P2B-14) ---------------------------------------------------


class OpeningBatch(models.Model):
    """One upload of the year's figures to date from the old payroll (P2B-14): HR uploads it,
    the Director approves it (approval engine, "payroll_opening"). Decided batches never
    change; none is deleted (database)."""

    class Status(models.TextChoices):
        AWAITING = "awaiting", "Waiting for the Director"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    file_name = models.CharField(max_length=200)
    tax_year = models.DateField()  # 1 April of the year of assessment
    status = models.CharField(max_length=10, choices=Status.choices, default="awaiting")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Opening figures {self.tax_year:%Y} ({self.file_name})"


class OpeningFigures(models.Model):
    """An employee's figures from the old payroll for the year of assessment, up to and
    including pay month `last_month`, and the gratuity provided for them so far. Counted in
    the payslips' year to date, the APIT year return and certificate, and as the gratuity
    provided before the first payroll here. Never changed (database)."""

    batch = models.ForeignKey(OpeningBatch, on_delete=models.PROTECT, related_name="figures")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="openings")
    last_month = models.DateField()
    months = models.PositiveSmallIntegerField()
    gross = models.DecimalField(max_digits=18, decimal_places=2)
    apit_earnings = models.DecimalField(max_digits=18, decimal_places=2)
    apit = models.DecimalField(max_digits=18, decimal_places=2)
    epf_employee = models.DecimalField(max_digits=18, decimal_places=2)
    epf_employer = models.DecimalField(max_digits=18, decimal_places=2)
    etf = models.DecimalField(max_digits=18, decimal_places=2)
    net = models.DecimalField(max_digits=18, decimal_places=2)
    gratuity_provision = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        ordering = ["batch", "employee__number"]
        constraints = [
            models.UniqueConstraint(fields=["batch", "employee"], name="payroll_opening_once"),
        ]

    def __str__(self):
        return f"{self.employee_id} opening to {self.last_month}"


class ParallelCheck(models.Model):
    """A pay month run both in the old payroll and here (P2B-14): the old figures uploaded,
    compared employee by employee with this payroll, and signed off by the Director (never
    by the person who uploaded them). Kept as compared; never deleted (database)."""

    run = models.ForeignKey(PayrollRun, on_delete=models.PROTECT, related_name="parallel_checks")
    file_name = models.CharField(max_length=200)
    result = models.JSONField()  # the comparison as shown
    differences = models.PositiveIntegerField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)
    signed_off_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    signed_off_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Parallel check of {self.run_id}"
