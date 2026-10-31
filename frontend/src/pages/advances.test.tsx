import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { AdvanceDetail, AdvanceOptions } from "../api/advances";
import type { CurrentUser } from "../api/auth";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import AdvancePage from "./AdvancePage";
import AdvancesPage from "./AdvancesPage";

const cashier: CurrentUser = {
  ...sampleUser,
  access: { areas: { payments: ["enter", "view"] }, actions: ["record_payment", "record_receipt"], divisions: "all" },
};

const accountant: CurrentUser = {
  ...sampleUser,
  access: { areas: { payments: ["view"] }, actions: [], divisions: "all" },
};

const options: AdvanceOptions = {
  can_record: true,
  customers: [
    {
      id: 4,
      code: "C0004",
      name: "Unilever Sri Lanka",
      quotations: [{ id: 12, label: "QL26103101 Rev 0", division: 2, currency: "LKR", total_amount: "150000.00" }],
    },
  ],
  divisions: [
    { code: "WS", name: "Workshop" },
    { code: "IM", name: "Moulding" },
  ],
  accounts: [
    { id: 1, code: "COM-CUR", name: "Commercial Bank current", kind: "current", currency: "LKR" },
    { id: 2, code: "CASH", name: "Cash on hand", kind: "cash", currency: "LKR" },
  ],
};

const made: AdvanceDetail = {
  id: 7, number: "RC26100001", receipt_date: "2026-10-31", customer: { id: 4, code: "C0004", name: "Unilever Sri Lanka" },
  quotation: { id: 12, label: "QL26103101 Rev 0" }, division: "IM", currency: "LKR", amount: "75000.00", amount_lkr: "75000.00",
  balance_lkr: "0.00", method: "transfer", status: "awaiting_approval", created_by: "Cashier",
  account: { id: 1, code: "COM-CUR", name: "Commercial Bank current" }, reference: "CEFT 88812", exchange_rate: "1.000000",
  rate_date: null, set_off_lkr: "0.00", notes: "", journal_entry: null, approved_at: null, can_approve: false,
  history: [{ action: "submit", action_label: "Submitted", by: "Cashier", at: "2026-10-31T09:00:00", reason: "" }],
};

test("the Cashier records an advance against an approved quotation", async () => {
  const calls = mockApi({
    "GET /api/v1/advances/": { body: [] },
    "GET /api/v1/advances/options/": { body: options },
    "POST /api/v1/advances/": { status: 201, body: made },
  });
  renderAt("/advances", <AdvancesPage me={cashier} />);
  const form = await screen.findByRole("form", { name: "Receive an advance" });
  fireEvent.change(within(form).getByRole("combobox", { name: "Customer" }), { target: { value: "unilever" } });
  fireEvent.mouseDown(await within(form).findByRole("option", { name: "C0004 Unilever Sri Lanka" }));
  fireEvent.change(within(form).getByLabelText("Against quotation"), { target: { value: "12" } });
  expect(within(form).queryByLabelText("Division")).not.toBeInTheDocument(); // from the quotation
  // A transfer goes into a bank account: the cash account is not offered.
  const account = within(form).getByLabelText("Into account");
  expect(within(account).queryByRole("option", { name: /CASH/ })).not.toBeInTheDocument();
  fireEvent.change(account, { target: { value: "1" } });
  fireEvent.change(within(form).getByLabelText("Amount LKR"), { target: { value: "75000.00" } });
  fireEvent.change(within(form).getByLabelText("Cheque no. or reference"), { target: { value: "CEFT 88812" } });
  fireEvent.click(within(form).getByRole("button", { name: "Record and send to the Accountant" }));

  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/advances/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/advances/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    customer: 4,
    quotation: 12,
    division: "",
    account: 1,
    method: "transfer",
    amount: "75000.00",
    reference: "CEFT 88812",
  });
});

test("only the Cashier sees the form to receive an advance", async () => {
  mockApi({ "GET /api/v1/advances/": { body: [made] } });
  renderAt("/advances", <AdvancesPage me={accountant} />);
  const table = await screen.findByRole("table", { name: "Customer advances" });
  expect(within(table).getByRole("link", { name: "RC26100001" })).toHaveAttribute("href", "/advances/7");
  expect(screen.queryByRole("form", { name: "Receive an advance" })).not.toBeInTheDocument();
});

test("the Accountant approves the advance and it is posted", async () => {
  const waiting: AdvanceDetail = { ...made, can_approve: true };
  const calls = mockApi({
    "GET /api/v1/advances/7/": { body: waiting },
    "POST /api/v1/advances/7/approve/": {
      body: { ...made, status: "approved", balance_lkr: "75000.00", journal_entry: { id: 3, number: "JE-2026-0003" } },
    },
  });
  renderAt("/advances/7", <AdvancePage />, "/advances/:id");
  const decision = await screen.findByRole("group", { name: "Accountant's decision" });
  fireEvent.click(within(decision).getByRole("button", { name: "Approve and post" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/advances/7/approve/", expect.objectContaining({ method: "POST" })));
  expect(await screen.findByText("JE-2026-0003")).toBeInTheDocument();
  expect(screen.getByText("Approved and posted")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Print the receipt (PDF)" })).toHaveAttribute("href", "/api/v1/advances/7/receipt/");
});
