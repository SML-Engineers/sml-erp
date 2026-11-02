import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { MJDetail } from "../api/manualJournals";
import { mockApi, renderAt } from "../test-utils";
import ManualJournalPage from "./ManualJournalPage";

const account = (id: number, number: string, full_name: string, account_type: string) => ({
  id, number, name: full_name, full_name, depth: 0, parent: null, account_type, account_type_label: account_type, section: "assets",
  detail_type: { id: 1, name: "x" }, description: "", default_division: null, default_tax_code: null, system_role: null,
  is_active: true, merged_into: null, in_use: true, company_account: null,
});

const formApi = {
  "GET /api/v1/chart-of-accounts/": {
    body: [
      account(1, "6220", "Building repairs", "expense"),
      account(2, "2170", "Accrued expenses", "other_current_liability"),
      account(3, "2000", "Accounts payable", "accounts_payable"),
      account(4, "1100", "Accounts receivable", "accounts_receivable"),
    ],
  },
  "GET /api/v1/payees/": { body: [{ id: 7, code: "S0007", name: "Lanka Steel" }] },
  "GET /api/v1/divisions/": { body: [{ id: 1, code: "WS", name: "Workshop", division_type: "production" }] },
};

const draft: MJDetail = {
  id: 5, number: "MJ26110201", entry_date: "2026-11-02", narration: "Accrue October repairs", status: "draft", status_label: "Draft",
  total_debit: "25000.00", total_credit: "25000.00", created_by: "Kumari Silva", journal_entry: null,
  lines: [
    { line_no: 1, account: { id: 1, number: "6220", name: "Building repairs", account_type: "expense" }, division: "WS", supplier: null, description: "", debit: "25000.00", credit: "0.00" },
    { line_no: 2, account: { id: 2, number: "2170", name: "Accrued expenses", account_type: "other_current_liability" }, division: null, supplier: null, description: "", debit: "0.00", credit: "25000.00" },
  ],
  attachments: [], can_edit: true, can_approve: false, approval: null,
};

async function choose(form: HTMLElement, label: string, typed: string, option: string) {
  fireEvent.change(within(form).getByRole("combobox", { name: label }), { target: { value: typed } });
  fireEvent.mouseDown(await within(form).findByRole("option", { name: option }));
}

test("the Accountant types a journal; the totals show when it does not balance", async () => {
  const calls = mockApi({
    ...formApi,
    "POST /api/v1/manual-journals/": { status: 201, body: draft },
    "GET /api/v1/manual-journals/5/": { body: draft },
  });
  renderAt("/journals/manual/new", <ManualJournalPage />, "/journals/manual/:id");
  const form = await screen.findByRole("form", { name: "Journal details" });
  fireEvent.change(within(form).getByLabelText("Narration"), { target: { value: "Accrue October repairs" } });
  await choose(form, "Account, line 1", "repairs", "6220 Building repairs");
  fireEvent.change(within(form).getByLabelText("Debit, line 1"), { target: { value: "25000" } });
  await waitFor(() => expect(within(form).getByLabelText("Division, line 1").querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(within(form).getByLabelText("Division, line 1"), { target: { value: "WS" } });
  // Customer balances never change by journal, so receivables are not offered.
  fireEvent.change(within(form).getByRole("combobox", { name: "Account, line 2" }), { target: { value: "receivable" } });
  expect(within(form).queryByRole("option", { name: "1100 Accounts receivable" })).not.toBeInTheDocument();
  await choose(form, "Account, line 2", "accrued", "2170 Accrued expenses");
  fireEvent.change(within(form).getByLabelText("Credit, line 2"), { target: { value: "24000" } });
  expect(within(form).getByText(/out of balance by 1,000.00/)).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Credit, line 2"), { target: { value: "25000" } });
  expect(within(form).queryByText(/out of balance/)).not.toBeInTheDocument();
  fireEvent.click(within(form).getByRole("button", { name: "Make the draft journal" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/manual-journals/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/manual-journals/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    narration: "Accrue October repairs",
    lines: [
      { account: 1, debit: "25000", credit: "", division: "WS", supplier: null },
      { account: 2, debit: "", credit: "25000", division: null, supplier: null },
    ],
  });
});

test("a payables line asks for the supplier", async () => {
  mockApi({ ...formApi });
  renderAt("/journals/manual/new", <ManualJournalPage />, "/journals/manual/:id");
  const form = await screen.findByRole("form", { name: "Journal details" });
  expect(within(form).queryByRole("combobox", { name: "Supplier, line 1" })).not.toBeInTheDocument();
  await choose(form, "Account, line 1", "payable", "2000 Accounts payable");
  expect(within(form).getByRole("combobox", { name: "Supplier, line 1" })).toBeInTheDocument();
});

test("the Director approves and the journal is posted", async () => {
  const waiting: MJDetail = {
    ...draft, status: "awaiting_approval", status_label: "Waiting for approval", can_edit: false, can_approve: true,
    approval: { status: "in_progress", history: [{ action: "submit", action_label: "Submitted", by: "Kumari Silva", at: "2026-11-02T09:00:00", reason: "" }] },
  };
  const calls = mockApi({
    "GET /api/v1/manual-journals/5/": { body: waiting },
    "POST /api/v1/manual-journals/5/approve/": {
      body: { ...waiting, status: "posted", status_label: "Approved and posted", can_approve: false, journal_entry: { id: 40, number: "JV26110012" } },
    },
  });
  renderAt("/journals/manual/5", <ManualJournalPage />, "/journals/manual/:id");
  const lines = await screen.findByRole("table", { name: "Lines" });
  expect(within(lines).getByText("Building repairs")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Send for approval" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Approve and post" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/manual-journals/5/approve/", expect.objectContaining({ body: JSON.stringify({ comment: "" }) })),
  );
  expect(await screen.findByRole("link", { name: "JV26110012" })).toBeInTheDocument();
});
