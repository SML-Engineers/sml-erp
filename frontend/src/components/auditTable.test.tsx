import { render, screen } from "@testing-library/react";

import "../i18n";
import AuditTable, { eventWords } from "./AuditTable";

const row = {
  id: 1,
  occurred_at: "2026-11-16T09:22:25Z",
  actor_email: "admin@smlengineers.com",
  ip_address: null,
  action: "create" as const,
  object_type: "core.passwordreset",
  object_id: "3",
  object_repr: "Password reset for Nimal Perera",
  related_user: 1,
  related_user_email: "clerk@demo.sml.lk",
  event: "password_reset_requested",
  reason: "forgot the password",
  changes: {},
};

// Owner, 16 Nov 2026: the trail showed raw names such as "password_reset_requested".
test("events are named in plain words", () => {
  render(<AuditTable rows={[row, { ...row, id: 2, event: "stock_count_started" }]} />);
  expect(screen.getByText("Password reset asked for")).toBeInTheDocument();
  // An event with no wording of its own yet still reads as words.
  expect(screen.getByText("Stock count started")).toBeInTheDocument();
  expect(screen.getAllByText("2026-11-16 14:52")).toHaveLength(2);
});

test("event names become words", () => {
  expect(eventWords("goods_receipt_confirmed")).toBe("Goods receipt confirmed");
});
