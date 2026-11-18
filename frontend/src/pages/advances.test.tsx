import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";

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
      proformas: [],
      sales_orders: [],
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
  id: 7,
  number: "RC26100001",
  receipt_date: "2026-10-31",
  customer: { id: 4, code: "C0004", name: "Unilever Sri Lanka" },
  quotation: { id: 12, label: "QL26103101 Rev 0" },
  proforma: null,
  sales_order: null,
  division: "IM",
  currency: "LKR",
  amount: "75000.00",
  amount_lkr: "75000.00",
  balance_lkr: "0.00",
  method: "transfer",
  status: "awaiting_approval",
  created_by: "Cashier",
  account: { id: 1, code: "COM-CUR", name: "Commercial Bank current" },
  reference: "CEFT 88812",
  exchange_rate: "1.000000",
  rate_date: null,
  set_off_lkr: "0.00",
  notes: "",
  journal_entry: null,
  approved_at: null,
  can_approve: false,
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
    proforma: null,
    sales_order: null,
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

// Owner, 17 Nov 2026: the history said 09:27 (GMT); in Sri Lanka it was 14:57.
test("the history is in Sri Lanka time", async () => {
  mockApi({
    "GET /api/v1/advances/7/": {
      body: {
        ...made,
        history: [{ action: "submit", action_label: "Submitted", by: "Sunil Fernando", at: "2026-11-17T09:27:38Z", reason: "" }],
      },
    },
  });
  renderAt("/advances/7", <AdvancePage />, "/advances/:id");
  expect(await screen.findByText(/Sunil Fernando · 2026-11-17 14:57/)).toBeInTheDocument();
});

// Owner, 17 Nov 2026: an advance taken against a sales order said only "Against quotation".
test("an advance against a sales order shows the order, on its page and in the list", async () => {
  const onOrder: AdvanceDetail = {
    ...made,
    quotation: { id: 12, label: "QL26103104 Rev 0" },
    proforma: { id: 5, number: "PI26100002" },
    sales_order: { id: 9, number: "SO26103101" },
  };
  mockApi({ "GET /api/v1/advances/7/": { body: onOrder }, "GET /api/v1/advances/": { body: [onOrder] } });
  renderAt("/advances/7", <AdvancePage />, "/advances/:id");
  const details = await screen.findByRole("region", { name: "Receipt details" });
  expect(within(details).getByText("Against sales order")).toBeInTheDocument();
  expect(within(details).getByRole("link", { name: "SO26103101" })).toHaveAttribute("href", "/sales-orders/9");
  expect(within(details).getByRole("link", { name: "PI26100002" })).toHaveAttribute("href", "/proformas/5");
  expect(within(details).getByRole("link", { name: "QL26103104 Rev 0" })).toHaveAttribute("href", "/quotations/12");
  expect(within(details).queryByText("Against quotation")).not.toBeInTheDocument();
  cleanup();

  renderAt("/advances", <AdvancesPage me={accountant} />);
  const table = await screen.findByRole("table", { name: "Customer advances" });
  expect(within(table).getByRole("columnheader", { name: /Against/ })).toBeInTheDocument();
  expect(within(table).getByText("SO26103101")).toBeInTheDocument();
});

// Owner, 17 Nov 2026: with no tax invoices yet, the Set off box was a tiny empty list.
test("with no tax invoice to set off, the advance says so instead of an empty box", async () => {
  const posted: AdvanceDetail = {
    ...made,
    status: "approved",
    balance_lkr: "75000.00",
    journal_entry: { id: 3, number: "JE-2026-0003" },
    can_set_off: true,
    open_invoices: [],
  };
  mockApi({ "GET /api/v1/advances/7/": { body: posted } });
  renderAt("/advances/7", <AdvancePage />, "/advances/:id");
  expect(await screen.findByText("No tax invoices of this customer to set off yet.")).toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "Set off against an invoice" })).not.toBeInTheDocument();
  cleanup();

  mockApi({
    "GET /api/v1/advances/7/": {
      body: { ...posted, open_invoices: [{ id: 2, number: "TI26110001", invoice_date: "2026-11-10", open_amount: "50000.00" }] },
    },
  });
  renderAt("/advances/7", <AdvancePage />, "/advances/:id");
  const form = await screen.findByRole("form", { name: "Set off against an invoice" });
  expect(screen.queryByText("No tax invoices of this customer to set off yet.")).not.toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Invoice"), { target: { value: "2" } });
  expect(within(form).getByLabelText("Amount LKR")).toHaveValue("50000.00");
});
