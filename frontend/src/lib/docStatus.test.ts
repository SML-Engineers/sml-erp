import i18n from "../i18n";
import { quotationStatus } from "../api/quotations";
import { voucherStatus } from "../api/vouchers";
import { firstName } from "./docStatus";

// Owner, 16 Nov 2026: say who a document is with, not just "Submitted" or "Returned".
const t = i18n.getFixedT("en");
const nimal = "Nimal Perera";

test("a voucher's status says who it is with", () => {
  expect(voucherStatus(t, { status: "draft", created_by: nimal, people: null })).toBe("Draft of Nimal");
  expect(
    voucherStatus(t, {
      status: "submitted",
      created_by: nimal,
      people: { waiting: { person: "Kumari Silva", role: "Accountant" }, last: null },
    }),
  ).toBe("Waiting for Kumari (Accountant)");
  expect(
    voucherStatus(t, {
      status: "accountant_approved",
      created_by: nimal,
      people: { waiting: { person: null, role: "Director" }, last: { action: "approve", by: "Kumari Silva" } },
    }),
  ).toBe("Waiting for the Director");
  expect(
    voucherStatus(t, {
      status: "returned",
      created_by: nimal,
      people: { waiting: null, last: { action: "return", by: "Ruwan Jayasinghe" } },
    }),
  ).toBe("Returned by Ruwan");
  expect(
    voucherStatus(t, {
      status: "director_approved",
      created_by: nimal,
      people: { waiting: null, last: { action: "approve", by: "Ruwan Jayasinghe" } },
    }),
  ).toBe("Approved by Ruwan");
  expect(
    voucherStatus(t, {
      status: "rejected",
      created_by: nimal,
      people: { waiting: null, last: { action: "reject", by: "Ruwan Jayasinghe" } },
    }),
  ).toBe("Rejected by Ruwan");
  // After approval its own label says it best.
  expect(
    voucherStatus(t, { status: "paid", created_by: nimal, people: { waiting: null, last: { action: "approve", by: "Ruwan Jayasinghe" } } }),
  ).toBe("Paid");
});

test("a quotation's status says who it is with and what the customer did", () => {
  const dilini = "Dilini Wijesekara";
  expect(quotationStatus(t, { status: "draft", created_by: dilini, people: null })).toBe("Draft of Dilini");
  // Sent back to draft by an approver.
  expect(
    quotationStatus(t, {
      status: "draft",
      created_by: dilini,
      people: { waiting: null, last: { action: "return", by: "Ruwan Jayasinghe" } },
    }),
  ).toBe("Returned by Ruwan");
  expect(
    quotationStatus(t, {
      status: "awaiting_approval",
      created_by: dilini,
      people: { waiting: { person: "Ruwan Jayasinghe", role: "Director" }, last: null },
    }),
  ).toBe("Waiting for Ruwan (Director)");
  expect(quotationStatus(t, { status: "sent", created_by: dilini })).toBe("Sent to customer");
  expect(quotationStatus(t, { status: "accepted", created_by: dilini })).toBe("Customer accepted");
  expect(quotationStatus(t, { status: "lost", created_by: dilini })).toBe("Customer did not accept");
});

test("the first name is used in lists", () => {
  expect(firstName("Ruwan  Jayasinghe")).toBe("Ruwan");
  expect(firstName("Admin")).toBe("Admin");
});
