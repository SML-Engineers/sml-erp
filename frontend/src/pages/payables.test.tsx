import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { PayableRow, SupplierStatementDetail } from "../api/payables";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import PayablesPage from "./PayablesPage";
import SupplierStatementPage from "./SupplierStatementPage";
import SupplierStatementsPage from "./SupplierStatementsPage";

const clerk: CurrentUser = {
  ...sampleUser,
  access: { areas: { vouchers: ["enter", "view"], payees: ["enter", "view"] }, actions: [], divisions: "all" },
};

const row: PayableRow = {
  supplier_id: 3, code: "S0001", supplier: "Lanka Steel (Pvt) Ltd", current: "600.00", d30: "0.00", d60: "0.00",
  d90: "0.00", over90: "0.00", total: "600.00",
};

const statement: SupplierStatementDetail = {
  id: 4, supplier: { id: 3, code: "S0001", name: "Lanka Steel (Pvt) Ltd" }, currency: "LKR", from_date: null,
  statement_date: "2026-11-03", closing_balance: "1100.00", status: "open", created_by: "Clerk", notes: "",
  lines: [], checked_by: null, checked_at: null, check_note: "", can_edit: true, can_check: true,
  reconciliation: {
    from: "2026-11-01", to: "2026-11-03",
    matched: [
      {
        line: { line_no: 1, date: "2026-11-03", reference: "inv 7", description: "Steel bars", debit: "1000.00", credit: "0.00" },
        ours: { date: "2026-11-03", reference: "INV-7", document: "WS261103001", link: "/vouchers/9", amount: "1000.00" },
        difference: "0.00",
      },
    ],
    theirs_only: [{ line_no: 2, date: "2026-11-03", reference: "INV-99", description: "Steel plates", debit: "500.00", credit: "0.00" }],
    ours_only: [],
    their_balance: "1100.00", our_balance: "600.00", difference: "500.00",
  },
};

test("the aging lists what we owe and a supplier opens its items", async () => {
  mockApi({
    "GET /api/v1/payables/aging/": { body: { as_at: "2026-11-03", rows: [row], items: [] } },
    "GET /api/v1/payables/aging/?supplier=3": {
      body: {
        as_at: "2026-11-03",
        rows: [row],
        items: [
          {
            kind: "voucher", reference: "INV-7", document: "WS261103001", link: "/vouchers/9", division: "WS",
            date: "2026-11-03", due_date: "2026-12-03", days_overdue: 0, total: "1000.00", open: "600.00",
          },
        ],
      },
    },
  });
  renderAt("/payables", <PayablesPage />);
  const table = await screen.findByRole("table", { name: "Payables and statements" });
  fireEvent.click(within(table).getByRole("button", { name: "S0001 Lanka Steel (Pvt) Ltd" }));
  const items = await screen.findByRole("table", { name: "What we owe this supplier" });
  expect(within(items).getByRole("link", { name: "WS261103001" })).toHaveAttribute("href", "/vouchers/9");
  expect(within(items).getByText("INV-7")).toBeInTheDocument();
});

test("the Clerk types in a statement and it is saved for comparing", async () => {
  const calls = mockApi({
    "GET /api/v1/supplier-statements/": { body: [] },
    "GET /api/v1/payees/": { body: [{ id: 3, code: "S0001", name: "Lanka Steel (Pvt) Ltd" }] },
    "POST /api/v1/supplier-statements/": { status: 201, body: statement },
  });
  renderAt("/supplier-statements", <SupplierStatementsPage me={clerk} />);
  const form = await screen.findByRole("form", { name: "Enter a supplier statement" });
  fireEvent.change(within(form).getByRole("combobox", { name: "Supplier" }), { target: { value: "lanka" } });
  fireEvent.mouseDown(await within(form).findByRole("option", { name: "S0001 Lanka Steel (Pvt) Ltd" }));
  fireEvent.change(within(form).getByLabelText("Their closing balance"), { target: { value: "1,100.00" } });
  fireEvent.change(within(form).getByLabelText("Line 1 Date"), { target: { value: "2026-11-03" } });
  fireEvent.change(within(form).getByLabelText("Line 1 Reference"), { target: { value: "inv 7" } });
  fireEvent.change(within(form).getByLabelText("Line 1 Debit"), { target: { value: "1000.00" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add a line" }));
  fireEvent.click(within(form).getByRole("button", { name: "Save and compare" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/supplier-statements/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/supplier-statements/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    supplier: 3,
    closing_balance: "1100.00",
    lines: [{ date: "2026-11-03", reference: "inv 7", description: "", debit: "1000.00", credit: "" }],
  });
});

test("the comparison shows the differences and the Accountant marks it checked", async () => {
  const calls = mockApi({
    "GET /api/v1/supplier-statements/4/": { body: statement },
    "POST /api/v1/supplier-statements/4/check/": {
      body: { ...statement, status: "checked", can_check: false, checked_by: "Accountant", check_note: "INV-99 asked for" },
    },
  });
  renderAt("/supplier-statements/4", <SupplierStatementPage />, "/supplier-statements/:id");
  const theirs = await screen.findByRole("region", { name: "On their statement, not in our books" });
  expect(within(theirs).getByText(/INV-99/)).toBeInTheDocument();
  expect(screen.getByText("500.00")).toBeInTheDocument(); // the difference in balances
  const form = screen.getByRole("form", { name: "Mark checked" });
  fireEvent.change(within(form).getByLabelText("What was found"), { target: { value: "INV-99 asked for" } });
  fireEvent.click(within(form).getByRole("button", { name: "Mark checked" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/supplier-statements/4/check/", expect.objectContaining({ method: "POST" })),
  );
  expect(await screen.findByText("Checked by Accountant: INV-99 asked for")).toBeInTheDocument();
});
