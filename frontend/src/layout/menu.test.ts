import type { Access } from "../api/access";
import { pageAllowed } from "./menu";

const admin = { areas: { users: ["manage", "view"], settings: ["manage", "view"], vouchers: ["view"] }, actions: [], divisions: "all" } as Access;

test("a page is allowed only when the user can view the area of the menu item that owns it", () => {
  expect(pageAllowed("/admin/users/7", admin)).toBe(true);
  expect(pageAllowed("/vouchers/12", admin)).toBe(true);
  expect(pageAllowed("/payments", admin)).toBe(false);
  expect(pageAllowed("/quotations", admin)).toBe(false);
  expect(pageAllowed("/quotations/12/costing", admin)).toBe(false);
  expect(pageAllowed("/vouchers/review", admin)).toBe(false); // needs Approve
  expect(pageAllowed("/", admin)).toBe(true);
  expect(pageAllowed("/account/notifications", admin)).toBe(true);
});
