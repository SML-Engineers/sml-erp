import { can, type Access } from "../api/access";

export interface MenuItem {
  /** Translation key for the label. */
  label: string;
  path: string;
  /** The area the user needs View access to; null = everyone signed in. */
  area: string | null;
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
    label: "menu.administration",
    items: [
      { label: "users.title", path: "/admin/users", area: "users" },
      { label: "review.link", path: "/admin/access-review", area: "users" },
      { label: "audit.link", path: "/admin/audit", area: "audit_logs" },
    ],
  },
  {
    label: "menu.settings",
    items: [
      { label: "company.title", path: "/settings/company", area: "settings" },
      { label: "divisions.title", path: "/settings/divisions", area: "settings" },
      { label: "factory.title", path: "/settings/factory", area: "settings" },
      { label: "numbering.title", path: "/settings/number-series", area: "settings" },
    ],
  },
];

/** The menu as this user may see it: items they cannot view, and empty sections, removed. */
export function visibleMenu(access: Access | undefined): MenuSection[] {
  return MENU.map((section) => ({
    ...section,
    items: section.items.filter((item) => item.area === null || can(access, item.area)),
  })).filter((section) => section.items.length > 0);
}
