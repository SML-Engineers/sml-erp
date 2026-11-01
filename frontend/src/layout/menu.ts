import { can, type Access, type Level } from "../api/access";

export interface MenuItem {
  /** Translation key for the label. */
  label: string;
  path: string;
  /** The area the user needs View access to; null = everyone signed in. */
  area: string | null;
  /** A higher level needed in that area, when View is not enough. */
  level?: Level;
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
    items: [{ label: "menu.dashboard", path: "/", area: null }],
  },
  {
    label: "menu.vouchers",
    items: [
      { label: "vouchers.title", path: "/vouchers", area: "vouchers" },
      { label: "menu.waiting", path: "/vouchers/review", area: "vouchers", level: "approve" },
      { label: "menu.approveVouchers", path: "/vouchers/approve", area: "vouchers", level: "approve" },
      { label: "payments.title", path: "/payments", area: "payments" },
      { label: "advances.title", path: "/advances", area: "payments" },
      { label: "voucherReports.title", path: "/vouchers/reports", area: "vouchers" },
    ],
  },
  {
    label: "menu.sales",
    items: [
      { label: "quotations.title", path: "/quotations", area: "sales" },
      { label: "proformas.title", path: "/proformas", area: "sales" },
      { label: "salesOrders.title", path: "/sales-orders", area: "sales" },
      { label: "salesReports.title", path: "/sales/reports", area: "sales" },
      { label: "customers.title", path: "/customers", area: "sales" },
      { label: "costing.title", path: "/costing-rates", area: "sales" },
    ],
  },
  {
    label: "menu.purchasing",
    items: [
      { label: "po.title", path: "/purchase-orders", area: "purchasing" },
      { label: "grn.title", path: "/goods-receipts", area: "stores" },
      { label: "items.title", path: "/items", area: "stores" },
    ],
  },
  {
    label: "menu.accounts",
    items: [
      { label: "payees.title", path: "/payees", area: "payees" },
      { label: "banking.title", path: "/bank-accounts", area: "banking" },
      { label: "chart.title", path: "/chart-of-accounts", area: "accounting" },
      { label: "taxes.title", path: "/taxes", area: "accounting" },
      { label: "journal.title", path: "/journal", area: "accounting" },
      { label: "periods.title", path: "/accounting-periods", area: "accounting" },
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
      { label: "currencies.title", path: "/settings/currencies", area: "settings" },
      { label: "limits.title", path: "/settings/quotation-limits", area: "settings" },
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
    items: section.items.filter((item) => item.area === null || can(access, item.area, item.level ?? "view")),
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
  return !owner || owner.area === null || can(access, owner.area, owner.level ?? "view");
}
