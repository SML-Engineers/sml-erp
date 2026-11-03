import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { AgingRow, CreditHold, Statement } from "../api/receivables";
import { mockApi, renderAt } from "../test-utils";
import CreditHoldsPage from "./CreditHoldsPage";
import ReceivablesPage from "./ReceivablesPage";
import StatementPage from "./StatementPage";

const row: AgingRow = {
  customer_id: 5, code: "C0005", customer: "Lanka Tiles PLC", current: "0.00", d30: "55794.98", d60: "0.00",
  d90: "0.00", over90: "0.00", total: "55794.98", ledger: "55794.98",
};

const statement: Statement = {
  customer: { id: 5, code: "C0005", name: "Lanka Tiles PLC", credit_limit: null, payment_terms_days: 30 },
  from: "2026-08-05", to: "2026-11-03", opening: "0.00", closing: "45794.98",
  lines: [
    { date: "2026-09-19", reference: "26SEP_W1_01", source_type: "tax_invoice", description: "Tax invoice 26SEP_W1_01", debit: "55794.98", credit: "0.00", balance: "55794.98" },
    { date: "2026-11-03", reference: "RC26110001", source_type: "customer_receipt", description: "Receipt RC26110001", debit: "0.00", credit: "10000.00", balance: "45794.98" },
  ],
  items: [
    {
      invoice: { id: 21, number: "26SEP_W1_01", invoice_date: "2026-09-19", due_date: "2026-10-19", total_amount: "55794.98" },
      open: "45794.98", days_overdue: 15, bucket: "d30",
    },
  ],
  buckets: { current: "0.00", d30: "45794.98", d60: "0.00", d90: "0.00", over90: "0.00" },
  overdue: "45794.98", advances_held: "0.00",
  credit: { owed: "45794.98", overdue: "45794.98", over_limit: false, on_hold: true },
  reminders: { is_on: false, every_days: 7, set_by: null, recipient: "accounts@lankatiles.lk", last_sent_on: null, can_manage: true },
  can_email: true, emails: [],
};

const hold: CreditHold = {
  id: 3, document_type: "tax_invoice", document_label: "the invoice for order SO26110301", link: "/tax-invoices/22",
  customer: { id: 5, code: "C0005", name: "Lanka Tiles PLC" }, amount_lkr: "83692.46", exposure_lkr: "129487.44",
  credit_limit: null, overdue_lkr: "45794.98",
  reasons: "Lanka Tiles PLC has 1 overdue invoice (LKR 45,794.98, the oldest 15 days past due).",
  status: "waiting", requested_by: "Accountant", requested_at: "2026-11-03T10:00:00", decided_by: null, decided_at: null,
  note: "", can_allow: true,
};

test("the aging lists what each customer owes by age, with downloads", async () => {
  mockApi({ "GET /api/v1/receivables/aging/": { body: { as_at: "2026-11-03", rows: [row] } } });
  renderAt("/receivables", <ReceivablesPage />);
  const table = await screen.findByRole("table", { name: "Receivables and statements" });
  expect(within(table).getByRole("link", { name: "C0005 Lanka Tiles PLC" })).toHaveAttribute("href", "/receivables/5");
  expect(within(table).getAllByText("55,794.98")).toHaveLength(6); // the row and the totals
  expect(screen.getByRole("link", { name: "Excel" })).toHaveAttribute("href", "/api/v1/receivables/aging/?export=xlsx");
});

test("the statement shows the running balance, the credit hold, and reminders are switched on", async () => {
  const calls = mockApi({
    "GET /api/v1/receivables/statements/5/": { body: statement },
    "PUT /api/v1/receivables/statements/5/reminders/": { body: { ...statement.reminders, is_on: true, every_days: 14 } },
  });
  renderAt("/receivables/5", <StatementPage />, "/receivables/:id");
  const lines = await screen.findByRole("table", { name: "Transactions" });
  expect(within(lines).getByText("RC26110001")).toBeInTheDocument();
  expect(within(lines).getAllByText("45,794.98")).toHaveLength(2); // after the receipt, and closing
  expect(screen.getByText(/On credit hold/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Print the statement (PDF)" })).toHaveAttribute(
    "href",
    "/api/v1/receivables/statements/5/?export=pdf",
  );

  const settings = screen.getByRole("form", { name: "Reminder settings" });
  fireEvent.click(within(settings).getByLabelText("Email reminders while invoices are overdue"));
  fireEvent.change(within(settings).getByLabelText("Every (days)"), { target: { value: "14" } });
  fireEvent.click(within(settings).getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/receivables/statements/5/reminders/", expect.objectContaining({ method: "PUT" })),
  );
  const [, init] = calls.mock.calls.find(([url]) => url === "/api/v1/receivables/statements/5/reminders/")!;
  expect(JSON.parse(String(init!.body))).toEqual({ is_on: true, every_days: 14 });
});

test("the Director allows a document on credit hold with a note", async () => {
  let allowed = false;
  const calls = mockApi({
    "GET /api/v1/credit-holds/?status=waiting": () => ({ body: allowed ? [] : [hold] }),
    "POST /api/v1/credit-holds/3/allow/": () => {
      allowed = true;
      return { body: { ...hold, status: "allowed", decided_by: "Director", note: "Paying Friday", can_allow: false } };
    },
  });
  renderAt("/credit-holds", <CreditHoldsPage />);
  const card = await screen.findByRole("region", { name: "the invoice for order SO26110301" });
  expect(within(card).getByText(/1 overdue invoice/)).toBeInTheDocument();
  expect(within(card).getByRole("link", { name: "the invoice for order SO26110301" })).toHaveAttribute("href", "/tax-invoices/22");
  const decision = within(card).getByRole("form", { name: "Director's decision" });
  fireEvent.change(within(decision).getByLabelText("Why it is allowed"), { target: { value: "Paying Friday" } });
  fireEvent.click(within(decision).getByRole("button", { name: "Allow this document" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/credit-holds/3/allow/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url]) => url === "/api/v1/credit-holds/3/allow/")!;
  expect(JSON.parse(String(init!.body))).toEqual({ note: "Paying Friday" });
  expect(await screen.findByText("Nothing here.")).toBeInTheDocument();
});
