import { render, screen } from "@testing-library/react";

import "../i18n";
import { plainWords } from "../lib/words";
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

// Testing T33 (22 Nov 2026): the user's trail showed field names such as "totp_confirmed_at".
test("changed fields are named in plain words and moments in Sri Lanka time", () => {
  const changed = {
    ...row,
    action: "update" as const,
    event: "user_updated",
    changes: {
      totp_confirmed_at: [null, "2026-11-20T04:30:00Z"],
      two_factor_required: [false, true],
      is_staff: [false, false],
      all_sections: [true, false],
      discount_pct: ["0", "5"],
    } as Record<string, [unknown, unknown]>,
  };
  const { container } = render(<AuditTable rows={[changed]} />);
  const list = container.querySelector("ul.changes") as HTMLElement;
  expect(list).toHaveTextContent("Two-factor sign-in set up on: — → 2026-11-20 10:00");
  expect(list).toHaveTextContent("Two-factor sign-in required: no → yes");
  expect(list).toHaveTextContent("Can open the technical admin site: no → no");
  expect(list).toHaveTextContent("All sections: yes → no");
  expect(list).toHaveTextContent("Discount %: 0 → 5");
  expect(list.textContent).not.toContain("_");
});

test("program names without wording become words", () => {
  expect(plainWords("is_active")).toBe("Active");
  expect(plainWords("po_line_id")).toBe("PO line");
  expect(plainWords("max_shot_weight_g")).toBe("Max shot weight (g)");
  expect(plainWords("supplier_invoice_no")).toBe("Supplier invoice number");
});
