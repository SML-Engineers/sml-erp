import { can, type Access, type Level } from "../api/access";

export interface MenuItem {
  /** Translation key for the label. */
  label: string;
  path: string;
  /** The area the user needs View access to; null = everyone signed in. */
  area: string | null;
  /** A higher level needed in that area, when View is not enough. */
  level?: Level;
  /** A second area that also opens the page (e.g. delivery notes: Sales or the stores). */
  alsoArea?: string;
  /** Any one of these levels opens the page (e.g. employees: HR's Enter or the Director's Approve). */
  anyLevel?: Level[];
}

function allowed(access: Access | undefined, item: MenuItem): boolean {
  if (item.area === null) return true;
  if (item.anyLevel) return item.anyLevel.some((level) => can(access, item.area!, level));
  const level = item.level ?? "view";
  return can(access, item.area, level) || (item.alsoArea !== undefined && can(access, item.alsoArea, level));
}

export interface MenuSection {
  label: string;
  items: MenuItem[];
}

/**
 * The side menu. Each module adds its pages here as it is built. An item appears only for
 * users who can view its area (spec 1.2); the server still checks every request itself.
 */
export const MENU: MenuSection[] = [
  {
    label: "menu.main",
    items: [
      { label: "menu.dashboard", path: "/", area: null },
      // Self-service (P2B-11): every signed-in employee sees their own pay and leave.
      { label: "my.title", path: "/my", area: null },
      // A custodian can be anyone; the page shows only the floats the user may see (P2-17).
      { label: "petty.title", path: "/petty-cash", area: null },
      // Each data source checks its own area and divisions (P2-26).
      { label: "rb.title", path: "/report-builder", area: "dashboard" },
    ],
  },
  {
    label: "menu.vouchers",
    items: [
      { label: "vouchers.title", path: "/vouchers", area: "vouchers" },
      { label: "si.title", path: "/supplier-invoices", area: "vouchers" },
      { label: "menu.waiting", path: "/vouchers/review", area: "vouchers", level: "approve" },
      { label: "menu.approveVouchers", path: "/vouchers/approve", area: "vouchers", level: "approve" },
      { label: "payments.title", path: "/payments", area: "payments" },
      { label: "advances.title", path: "/advances", area: "payments" },
      { label: "receipts.title", path: "/receipts", area: "payments" },
      { label: "voucherReports.title", path: "/vouchers/reports", area: "vouchers" },
      { label: "ap.title", path: "/payables", area: "vouchers", alsoArea: "accounting" },
    ],
  },
  {
    label: "menu.sales",
    items: [
      { label: "quotations.title", path: "/quotations", area: "sales" },
      { label: "proformas.title", path: "/proformas", area: "sales" },
      { label: "salesOrders.title", path: "/sales-orders", area: "sales" },
      { label: "dn.title", path: "/delivery-notes", area: "sales", alsoArea: "stores" },
      { label: "ti.title", path: "/tax-invoices", area: "sales", alsoArea: "accounting" },
      { label: "cn.title", path: "/credit-notes", area: "sales", alsoArea: "accounting" },
      { label: "ar.title", path: "/receivables", area: "sales", alsoArea: "accounting" },
      { label: "holds.title", path: "/credit-holds", area: "sales", alsoArea: "accounting" },
      { label: "salesReports.title", path: "/sales/reports", area: "sales" },
      { label: "customers.title", path: "/customers", area: "sales" },
      { label: "costing.title", path: "/costing-rates", area: "sales" },
    ],
  },
  {
    label: "menu.purchasing",
    items: [
      { label: "reorder.title", path: "/reorder", area: "stores", alsoArea: "purchasing" },
      { label: "prq.title", path: "/purchase-requests", area: "purchasing", alsoArea: "stores" },
      { label: "po.title", path: "/purchase-orders", area: "purchasing" },
      { label: "grn.title", path: "/goods-receipts", area: "stores" },
      { label: "qc.title", path: "/inspections", area: "quality" },
      { label: "plans.title", path: "/inspection-plans", area: "quality" },
      { label: "stock.title", path: "/stock", area: "stores" },
      { label: "sw.title", path: "/stores-work", area: "stores", alsoArea: "accounting" },
      { label: "os.title", path: "/opening-stock", area: "stores" },
      { label: "rtn.title", path: "/supplier-returns", area: "stores" },
      { label: "items.title", path: "/items", area: "stores" },
      { label: "pr.title", path: "/purchasing/reports", area: "purchasing" },
    ],
  },
  {
    label: "menu.accounts",
    items: [
      { label: "payees.title", path: "/payees", area: "payees" },
      { label: "banking.title", path: "/bank-accounts", area: "banking" },
      { label: "cheques.title", path: "/cheques", area: "banking", alsoArea: "payments" },
      { label: "bs.title", path: "/bank-statements", area: "banking" },
      { label: "rec.title", path: "/reconciliation", area: "banking" },
      { label: "chart.title", path: "/chart-of-accounts", area: "accounting" },
      { label: "taxes.title", path: "/taxes", area: "accounting" },
      { label: "sa.title", path: "/sales-accounts", area: "accounting" },
      { label: "mj.title", path: "/journals/manual", area: "accounting" },
      { label: "rj.title", path: "/journals/recurring", area: "accounting" },
      { label: "journal.title", path: "/journal", area: "accounting" },
      { label: "fa.title", path: "/fixed-assets", area: "accounting" },
      { label: "reval.title", path: "/revaluation", area: "accounting" },
      { label: "budget.title", path: "/budgets", area: "accounting" },
      { label: "close.title", path: "/month-end", area: "accounting" },
      { label: "wip.title", path: "/wip-report", area: "accounting" },
      { label: "planner.title", path: "/cash-planner", area: "financial_reports" },
      { label: "mig.title", path: "/migration", area: "accounting" },
      { label: "par.title", path: "/parallel-run", area: "financial_reports" },
      { label: "tax.title", path: "/tax-reports", area: "accounting", alsoArea: "financial_reports" },
      { label: "fr.title", path: "/reports/financial", area: "financial_reports" },
      { label: "periods.title", path: "/accounting-periods", area: "accounting" },
    ],
  },
  {
    label: "menu.production",
    items: [
      { label: "prodOrder.title", path: "/production-orders", area: "production_planning", alsoArea: "stores" },
      { label: "job.title", path: "/job-orders", area: "production_planning", alsoArea: "stores" },
      { label: "plan.title", path: "/production-plan", area: "production_planning", alsoArea: "shop_floor" },
      { label: "shiftReport.title", path: "/shift-report", area: "shop_floor", alsoArea: "production_approvals" },
      { label: "mould.title", path: "/moulds", area: "production_planning" },
      { label: "mouldMaint.title", path: "/mould-maintenance", area: "production_planning" },
      { label: "routing.title", path: "/routings", area: "production_planning" },
      { label: "bom.title", path: "/boms", area: "production_planning" },
      { label: "costRate.title", path: "/cost-rates", area: "production_planning" },
      { label: "profit.pageTitle", path: "/order-profits", area: "job_profitability", alsoArea: "accounting" },
    ],
  },
  {
    label: "menu.people",
    items: [
      // Personal details: HR (Enter) and the Director (Approve), not the Accountant's totals view.
      { label: "emp.title", path: "/employees", area: "hr_payroll", anyLevel: ["enter", "approve"] },
      { label: "pc.title", path: "/pay-components", area: "hr_payroll", anyLevel: ["enter", "approve"] },
      { label: "att.title", path: "/attendance", area: "hr_payroll", anyLevel: ["enter", "approve"] },
      // Section supervisors check their people's overtime (they hold HR and payroll: View).
      { label: "ot.title", path: "/overtime", area: "hr_payroll" },
      { label: "wr.title", path: "/work-rules", area: "hr_payroll", anyLevel: ["enter", "approve"] },
      { label: "payroll.title", path: "/payroll", area: "hr_payroll", anyLevel: ["enter", "approve"] },
      { label: "takeover.title", path: "/payroll-takeover", area: "hr_payroll", anyLevel: ["enter", "approve"] },
      { label: "returns.title", path: "/payroll-returns", area: "hr_payroll", anyLevel: ["enter", "approve"] },
      { label: "credits.title", path: "/advances-loans", area: "hr_payroll", anyLevel: ["enter", "approve"] },
      // The Accountant keeps the APIT tables and EPF/ETF rates.
      { label: "taxTables.title", path: "/payroll-tax-tables", area: "accounting" },
      { label: "gratuity.title", path: "/gratuity", area: "accounting" },
      { label: "leave.title", path: "/leave", area: "hr_payroll", anyLevel: ["enter", "approve"] },
      { label: "hol.title", path: "/holidays", area: "hr_payroll", anyLevel: ["enter", "approve"] },
    ],
  },
  {
    label: "menu.administration",
    items: [
      { label: "users.title", path: "/admin/users", area: "users" },
      { label: "review.link", path: "/admin/access-review", area: "users" },
      { label: "audit.link", path: "/admin/audit", area: "audit_logs" },
      { label: "sentEmails.title", path: "/admin/sent-emails", area: "audit_logs" },
    ],
  },
  {
    label: "menu.settings",
    items: [
      { label: "company.title", path: "/settings/company", area: "settings" },
      { label: "divisions.title", path: "/settings/divisions", area: "settings" },
      { label: "stores.title", path: "/settings/stores", area: "settings" },
      { label: "factory.title", path: "/settings/factory", area: "settings" },
      { label: "shifts.title", path: "/settings/shifts", area: "settings" },
      { label: "prodSetup.title", path: "/settings/production", area: "settings" },
      { label: "currencies.title", path: "/settings/currencies", area: "settings" },
      { label: "limits.title", path: "/settings/quotation-limits", area: "settings" },
      { label: "taxRates.title", path: "/settings/tax-rates", area: "settings" },
      { label: "numbering.title", path: "/settings/number-series", area: "settings" },
      { label: "voucherTypes.title", path: "/settings/voucher-types", area: "settings" },
      { label: "matrix.title", path: "/settings/approval-matrix", area: "settings" },
      { label: "documentEmail.title", path: "/settings/document-email", area: "settings" },
    ],
  },
];

/** The menu as this user may see it: items they cannot view, and empty sections, removed. */
export function visibleMenu(access: Access | undefined): MenuSection[] {
  return MENU.map((section) => ({
    ...section,
    items: section.items.filter((item) => allowed(access, item)),
  })).filter((section) => section.items.length > 0);
}

/** Whether the user may open the page at `pathname`: the menu item that owns it (the longest
 * matching path) decides. Pages outside the menu (account pages) are open to everyone signed
 * in. The server still checks every request; this only shows a clear "No access" page. */
export function pageAllowed(pathname: string, access: Access | undefined): boolean {
  let owner: MenuItem | undefined;
  for (const section of MENU)
    for (const item of section.items) {
      if (item.path === "/") continue;
      const matches = pathname === item.path || pathname.startsWith(`${item.path}/`);
      if (matches && (!owner || item.path.length > owner.path.length)) owner = item;
    }
  return !owner || allowed(access, owner);
}
