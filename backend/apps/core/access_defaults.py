"""The access catalogue and the standard roles' default access (spec 1.1 and 1.2).

STANDARD_ROLES_V1 is loaded by migration 0004. Treat it as frozen: a later change to the
defaults is a new constant (V2) loaded by a new migration, so existing databases and new
ones always agree.
"""

# --- Catalogue --------------------------------------------------------------------------

AREAS = {
    "dashboard": "Dashboard",
    "vouchers": "Payment vouchers",
    "payments": "Supplier payments",
    "banking": "Banking and reconciliation",
    "payees": "Suppliers and payees",
    "accounting": "Chart of accounts and journals",
    "financial_reports": "Financial reports",
    "sales": "Sales",
    "purchasing": "Purchasing",
    "stores": "Stores and goods receipt",
    "quality": "Quality",
    "production_planning": "Production planning and job orders",
    "shop_floor": "Shop-floor entry",
    "production_approvals": "Production approvals and reports",
    "job_profitability": "Job and order profitability",
    "hr_payroll": "HR and payroll",
    "settings": "Settings",
    "users": "Users, roles and access",
    "audit_logs": "Audit and approval logs",
}

LEVELS = {
    "view": "View: read, search, print and export",
    "enter": "Enter: create and edit own records, and submit them",
    "approve": "Approve: review, approve, return or reject at the role's level",
    "manage": "Manage: full maintenance of the area's records or settings",
}

# What each level includes (spec 1.2): Approve and Enter include View; Manage includes Enter.
IMPLIES = {
    "view": {"view"},
    "enter": {"enter", "view"},
    "approve": {"approve", "view"},
    "manage": {"manage", "enter", "view"},
}

ACTIONS = {
    "record_payment": "Record supplier payments",
    "delete_submitted_voucher": "Delete a submitted voucher that has no payment",
    "close_period": "Close and reopen accounting periods",
    "change_bank_details": "Change suppliers' and payees' bank details",
    "export_personal_data": "Export personal data",
    "confirm_sensitive_grants": "Confirm sensitive access grants",
    "confirm_limits": "Confirm quotation approval limits",
    "record_receipt": "Record customer receipts and advances",
    "confirm_tax_rates": "Confirm changes to tax rates",
    "issue_tax_invoices": "Issue tax invoices",
    "approve_credit_notes": "Approve credit notes",
    "allow_credit_holds": "Allow documents on credit hold",
    "approve_customer_receipts": "Approve customer receipts and advances",
    "set_credit_terms": "Change customers' credit limits and payment terms",
    "approve_production_corrections": "Approve corrections to shift reports",
}

# Access that counts as sensitive (spec 1.3): an override granting it needs the Director.
SENSITIVE_AREA_LEVELS = {("vouchers", "approve"), ("users", "manage")}
SENSITIVE_AREAS = {"hr_payroll"}
SENSITIVE_ACTIONS = {
    "allow_credit_holds",
    "approve_production_corrections",
    "approve_credit_notes",
    "approve_customer_receipts",
    "set_credit_terms",
    "issue_tax_invoices",
    "record_payment",
    "record_receipt",
    "delete_submitted_voucher",
    "change_bank_details",
    "close_period",
}

# Holding any of these roles switches two-factor sign-in on (spec 1.1, P0-03).
TWO_FACTOR_ROLES = {"system_admin", "director", "accountant", "cashier"}

FINANCE_ROLES = {"director", "accountant", "clerk", "cashier"}

# Pairs that should be held by different people (spec 1.1, "Conflicting combinations").
CONFLICTING_PAIRS = (
    [
        ("clerk", "cashier", "records and pays the same vouchers"),
        ("accountant", "cashier", "approves and pays the same vouchers"),
    ]
    + [
        ("system_admin", role, "manages access and also handles money")
        for role in sorted(FINANCE_ROLES)
    ]
    + [
        # Phase 1.6 (P16-02, spec 5A.6): who orders, who receives, who invoices and who pays.
        ("purchasing_officer", "store_supervisor", "orders and receives the same goods"),
        ("purchasing_officer", "cashier", "orders goods and pays for them"),
        ("store_supervisor", "clerk", "receives goods and enters the supplier's invoice for them"),
        ("store_supervisor", "cashier", "receives goods and pays for them"),
    ]
)

# Pairs that are never allowed, even with a reason: QC acceptance is the check on the single
# stores person (owner's decision, 31 Oct 2026; spec 5A decision 2).
FORBIDDEN_PAIRS = [
    ("store_supervisor", "qc_inspector", "receives goods and also accepts them in QC"),
]


# --- Standard roles ---------------------------------------------------------------------

V, E, A, M = "view", "enter", "approve", "manage"


def _all_view(note_for=None):
    note_for = note_for or {}
    return [(area, V, note_for.get(area, "")) for area in AREAS]


# Each role: code -> (name, description, active from phase 1, permissions, actions).
# Permissions are (area, level, note); notes explain limits that the module itself applies.
STANDARD_ROLES_V1 = {
    "system_admin": (
        "System Administrator",
        "Users, roles, settings and master codes. Kept apart from money.",
        True,
        [
            ("dashboard", V, "system"),
            ("vouchers", V, "to delete unpaid vouchers"),
            ("settings", M, ""),
            ("users", M, ""),
            ("audit_logs", V, ""),
        ],
        ["delete_submitted_voucher"],
    ),
    "director": (
        "Director",
        "Final approval (L3); approves deletions, cancellations, limits and period close.",
        True,
        [
            ("dashboard", V, "all"),
            ("vouchers", A, "level 3"),
            ("payments", V, ""),
            ("banking", V, ""),
            ("payees", V, ""),
            ("accounting", V, ""),
            ("financial_reports", V, ""),
            ("sales", A, "above limits"),
            ("purchasing", A, ""),
            ("stores", V, ""),
            ("quality", A, "deviations"),
            ("production_planning", V, ""),
            ("production_approvals", V, ""),
            ("job_profitability", V, ""),
            ("hr_payroll", A, "payroll"),
            ("settings", V, ""),
            ("users", V, ""),
            ("audit_logs", V, ""),
        ],
        ["delete_submitted_voucher", "close_period", "confirm_limits", "confirm_sensitive_grants"],
    ),
    "accountant": (
        "Accountant",
        "Reviews and codes vouchers (L2); suppliers, chart of accounts, journals, banking.",
        True,
        [
            ("dashboard", V, ""),
            ("vouchers", E, ""),
            ("vouchers", A, "level 2"),
            ("payments", V, ""),
            ("banking", M, ""),
            ("payees", M, ""),
            ("accounting", M, ""),
            ("financial_reports", V, ""),
            ("sales", V, ""),
            ("purchasing", V, ""),
            ("stores", V, ""),
            ("quality", V, ""),
            ("production_planning", V, ""),
            ("production_approvals", V, ""),
            ("job_profitability", V, ""),
            ("hr_payroll", V, "totals only"),
            ("settings", V, ""),
            ("audit_logs", V, "finance"),
        ],
        ["change_bank_details"],
    ),
    "clerk": (
        "Accounts Clerk",
        "Creates vouchers and uploads scanned invoices (L1).",
        True,
        [
            ("dashboard", V, "own"),
            ("vouchers", E, "own"),
            ("payees", E, "add"),
        ],
        [],
    ),
    "cashier": (
        "Cashier / Payment Officer",
        "Records payments against Director-approved vouchers.",
        True,
        [
            ("dashboard", V, "own"),
            ("vouchers", V, "approved only"),
            ("payments", E, ""),
            ("banking", V, ""),
            ("payees", V, ""),
        ],
        ["record_payment"],
    ),
    "auditor": (
        "Auditor",
        "Reads everything, including audit and approval logs. Changes nothing.",
        True,
        _all_view({"hr_payroll": "totals only"}),
        [],
    ),
    "sales_executive": (
        "Sales Executive",
        "Customers, quotations, proformas and sales orders.",
        False,
        [("dashboard", V, "own"), ("sales", E, ""), ("production_planning", V, "status")],
        [],
    ),
    "sales_manager": (
        "Sales Manager",
        "Approves quotations within the limits.",
        False,
        [
            ("dashboard", V, "sales"),
            ("sales", A, "within limits"),
            ("production_planning", V, "status"),
            ("job_profitability", V, ""),
        ],
        [],
    ),
    "purchasing_officer": (
        "Purchasing Officer",
        "Purchase requests and orders.",
        False,
        [
            ("dashboard", V, "own"),
            ("payees", E, ""),
            ("purchasing", E, ""),
            ("stores", V, ""),
            ("quality", V, ""),
        ],
        [],
    ),
    "store_supervisor": (
        "Store Supervisor",
        "Goods receipts with weights and counts, material issues and returns.",
        False,
        [
            ("dashboard", V, "own"),
            ("payees", V, ""),
            ("purchasing", V, ""),
            ("stores", E, ""),
            ("quality", V, ""),
        ],
        [],
    ),
    "qc_inspector": (
        "QC Inspector",
        "Inspection results; accepts or rejects lots.",
        False,
        [
            ("dashboard", V, "own"),
            ("payees", V, ""),
            ("purchasing", V, ""),
            ("stores", V, ""),
            ("quality", A, ""),
            ("shop_floor", E, "inspection"),
            ("production_approvals", V, ""),
        ],
        [],
    ),
    "hr_payroll_officer": (
        "HR and Payroll Officer",
        "Employees, attendance and payroll preparation.",
        False,
        [("dashboard", V, "own"), ("hr_payroll", M, "")],
        ["export_personal_data"],
    ),
    "production_planner": (
        "Production Planner",
        "Job orders, production plans and bills of materials.",
        False,
        [
            ("dashboard", V, "production"),
            ("sales", V, ""),
            ("purchasing", V, ""),
            ("stores", V, ""),
            ("production_planning", E, ""),
            ("production_approvals", V, ""),
        ],
        [],
    ),
    "production_supervisor": (
        "Production Supervisor",
        "Shift entries for assigned sections only.",
        False,
        [
            ("dashboard", V, "own sections"),
            ("stores", V, ""),
            ("quality", V, ""),
            ("production_planning", V, ""),
            ("shop_floor", E, "own sections"),
            ("production_approvals", V, "own sections"),
            ("hr_payroll", V, "attendance"),
        ],
        [],
    ),
    "production_manager": (
        "Production Manager",
        "Approves shift reports, corrections, deviations and bills of materials.",
        False,
        [
            ("dashboard", V, "production"),
            ("sales", V, ""),
            ("purchasing", V, ""),
            ("stores", V, ""),
            ("quality", A, "deviations"),
            ("production_planning", A, ""),
            ("shop_floor", V, ""),
            ("production_approvals", A, ""),
            ("job_profitability", V, ""),
            ("hr_payroll", V, "attendance"),
        ],
        [],
    ),
}

STANDARD_DIVISIONS_V1 = [
    ("WS", "Workshop", "production"),
    ("IM", "Plastic Injection Moulding", "production"),
    ("HO", "Head Office", "shared"),
]


# --- Later changes to the standard roles (loaded by their own migrations) ----------------

# Phase 1.5 (P15-09, core migration 0017): the Cashier records customer advances, which the
# Accountant approves (owner, 31 Oct 2026).
ROLE_ACTIONS_V2 = {"cashier": ["record_receipt"]}

# P16-20 (core migration 0020): the Director confirms tax rate changes the Admin or the
# Accountant enters (owner, 2 Nov 2026).
ROLE_ACTIONS_V3 = {"director": ["confirm_tax_rates"]}

# P2-05 (core migration 0021): tax invoices are issued by the Director, the Accountant and the
# salespeople the Admin chooses (granted to them one by one, confirmed by the Director as a
# sensitive grant); not every salesperson (owner, 3 Nov 2026).
ROLE_ACTIONS_V4 = {"director": ["issue_tax_invoices"], "accountant": ["issue_tax_invoices"]}

# P2-06 (core migration 0022): credit notes are approved by the Director, or by a person the
# Admin gives "approve_credit_notes" to and the Director confirms (owner, 3 Nov 2026).
ROLE_ACTIONS_V5 = {"director": ["approve_credit_notes"]}

# P2-08 (core migration 0023): a document on credit hold is allowed by the Director (owner,
# 3 Nov 2026: block until the Director allows that document).
ROLE_ACTIONS_V6 = {"director": ["allow_credit_holds"]}

# P2-07 fix (core migration 0024): customer receipts and advances are approved by the
# Accountant, or by a person the Admin gives "approve_customer_receipts" to and the Director
# confirms (owner, 3 Nov 2026).
ROLE_ACTIONS_V7 = {"accountant": ["approve_customer_receipts"]}

# Owner, 3 Nov 2026 (core migration 0025): only the Accountant and the Director change a
# customer's credit limit and payment terms, so nobody lifts a credit hold (P2-08) by
# changing them; a grant to anyone else is sensitive.
ROLE_ACTIONS_V8 = {"director": ["set_credit_terms"], "accountant": ["set_credit_terms"]}

# P3-09 (production migration 0019): a correction to a shift report after its entry time is
# approved by the Production Manager, the Director, or a person the Admin gives
# "approve_production_corrections" to and the Director confirms (owner, 7 Nov 2026).
ROLE_ACTIONS_V9 = {
    "production_manager": ["approve_production_corrections"],
    "director": ["approve_production_corrections"],
}

# Phase 1.6 (P16-02, core migration 0019): purchasing, stores and QC roles switched on. SML has
# one stores person, called Stores Manager or Stores Executive (owner, 31 Oct 2026).
PHASE_1_6_ROLES = ("purchasing_officer", "store_supervisor", "qc_inspector")
ROLE_NAMES_V2 = {
    "store_supervisor": (
        "Stores Manager / Executive",
        "Receives goods against purchase orders and confirms GRNs; material issues and "
        "returns. Never approves payments or accepts goods in QC.",
    ),
}
