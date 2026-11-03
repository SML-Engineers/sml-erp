import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { AdvanceDetail } from "../api/advances";
import type { CurrentUser } from "../api/auth";
import type { ReceiptDetail, ReceiptOptions } from "../api/receipts";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import AdvancePage from "./AdvancePage";
import ReceiptPage from "./ReceiptPage";
import ReceiptsPage from "./ReceiptsPage";

const cashier: CurrentUser = {
  ...sampleUser,
  access: { areas: { payments: ["enter", "view"] }, actions: ["record_payment", "record_receipt"], divisions: "all" },
};

const accountant: CurrentUser = {
  ...sampleUser,
  access: { areas: { payments: ["view"], accounting: ["manage", "enter", "view"] }, actions: [], divisions: "all" },
};

const options: ReceiptOptions = {
  can_record: true,
  customers: [
    {
      id: 9,
      code: "C0009",
      name: "Lanka Tiles PLC",
      invoices: [
        {
          id: 21, number: "26NOV_W1_01", invoice_date: "2026-11-02", due_date: "2026-12-02", division: "WS",
          customer_po: "LT/PO/1201", total_amount: "55794.98", open_amount: "55794.98",
        },
        {
          id: 22, number: "26NOV_W1_02", invoice_date: "2026-11-03", due_date: "2026-12-03", division: "WS",
          customer_po: "LT/PO/1201", total_amount: "83692.46", open_amount: "83692.46",
        },
      ],
    },
  ],
  accounts: [
    { id: 1, code: "COM-CUR", name: "Commercial Bank current", kind: "current", currency: "LKR" },
    { id: 2, code: "CASH", name: "Cash on hand", kind: "cash", currency: "LKR" },
  ],
};

const made: ReceiptDetail = {
  id: 5, number: "RC26110002", receipt_date: "2026-11-03", customer: { id: 9, code: "C0009", name: "Lanka Tiles PLC" },
  method: "transfer", reference: "CEFT 99120", cheque_date: null, amount: "100000.00", status: "awaiting_approval",
  created_by: "Cashier", account: { id: 1, code: "COM-CUR", name: "Commercial Bank current" }, cheque_bank: "", notes: "",
  allocations: [
    { invoice: { id: 21, number: "26NOV_W1_01", invoice_date: "2026-11-02", division: "WS", total_amount: "55794.98" }, amount: "55794.98" },
    { invoice: { id: 22, number: "26NOV_W1_02", invoice_date: "2026-11-03", division: "WS", total_amount: "83692.46" }, amount: "44205.02" },
  ],
  journal_entry: null, approved_by: null, approved_at: null, posted_at: null, can_approve: false,
  history: [{ action: "submit", action_label: "Submitted", by: "Cashier", at: "2026-11-03T09:00:00", reason: "" }],
};

async function chooseCustomer(form: HTMLElement) {
  fireEvent.change(within(form).getByRole("combobox", { name: "Customer" }), { target: { value: "lanka" } });
  fireEvent.mouseDown(await within(form).findByRole("option", { name: "C0009 Lanka Tiles PLC" }));
}

test("the Cashier splits a transfer over the invoices, oldest first", async () => {
  const calls = mockApi({
    "GET /api/v1/receipts/": { body: [] },
    "GET /api/v1/receipts/options/": { body: options },
    "POST /api/v1/receipts/": { status: 201, body: made },
  });
  renderAt("/receipts", <ReceiptsPage me={cashier} />);
  const form = await screen.findByRole("form", { name: "Receive a payment for invoices" });
  await chooseCustomer(form);
  fireEvent.change(within(form).getByLabelText("Into account"), { target: { value: "1" } });
  fireEvent.change(within(form).getByLabelText("Amount LKR"), { target: { value: "100,000.00" } });
  fireEvent.change(within(form).getByLabelText("Cheque no. or reference"), { target: { value: "CEFT 99120" } });
  const record = within(form).getByRole("button", { name: "Record and send to the Accountant" });
  expect(record).toBeDisabled(); // nothing split yet
  fireEvent.click(within(form).getByRole("button", { name: "Fill oldest first" }));
  expect(within(form).getByLabelText("Paid on 26NOV_W1_01")).toHaveValue("55794.98");
  expect(within(form).getByLabelText("Paid on 26NOV_W1_02")).toHaveValue("44205.02");
  expect(within(form).getByText("100,000.00 of 100,000.00 split over the invoices")).toBeInTheDocument();
  fireEvent.click(record);

  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/receipts/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/receipts/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    customer: 9,
    method: "transfer",
    account: 1,
    amount: "100000.00",
    reference: "CEFT 99120",
    cheque_date: null,
    allocations: [
      { invoice: 21, amount: "55794.98" },
      { invoice: 22, amount: "44205.02" },
    ],
  });
});

test("a cheque needs no account: it waits in Undeposited funds", async () => {
  mockApi({
    "GET /api/v1/receipts/": { body: [] },
    "GET /api/v1/receipts/options/": { body: options },
  });
  renderAt("/receipts", <ReceiptsPage me={cashier} />);
  const form = await screen.findByRole("form", { name: "Receive a payment for invoices" });
  fireEvent.change(within(form).getByLabelText("Received by"), { target: { value: "cheque" } });
  expect(within(form).queryByLabelText("Into account")).not.toBeInTheDocument();
  expect(within(form).getByLabelText("Date on the cheque")).toBeInTheDocument();
  expect(within(form).getByLabelText("Bank of the cheque")).toBeInTheDocument();
});

test("only the Cashier sees the form", async () => {
  mockApi({ "GET /api/v1/receipts/": { body: [made] } });
  renderAt("/receipts", <ReceiptsPage me={accountant} />);
  const table = await screen.findByRole("table", { name: "Customer receipts" });
  expect(within(table).getByRole("link", { name: "RC26110002" })).toHaveAttribute("href", "/receipts/5");
  expect(screen.queryByRole("form", { name: "Receive a payment for invoices" })).not.toBeInTheDocument();
});

test("the Accountant approves the receipt and it is posted", async () => {
  const calls = mockApi({
    "GET /api/v1/receipts/5/": { body: { ...made, can_approve: true } },
    "POST /api/v1/receipts/5/approve/": {
      body: { ...made, status: "posted", journal_entry: { id: 8, number: "JE-2026-0008" } },
    },
  });
  renderAt("/receipts/5", <ReceiptPage />, "/receipts/:id");
  const paid = await screen.findByRole("table", { name: "Invoices paid" });
  expect(within(paid).getByText("44,205.02")).toBeInTheDocument();
  const decision = screen.getByRole("group", { name: "Accountant's decision" });
  fireEvent.click(within(decision).getByRole("button", { name: "Approve and post" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/receipts/5/approve/", expect.objectContaining({ method: "POST" })));
  expect(await screen.findByText("JE-2026-0008")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Print the receipt (PDF)" })).toHaveAttribute("href", "/api/v1/receipts/5/pdf/");
});

test("a post-dated cheque says when it will be posted", async () => {
  mockApi({
    "GET /api/v1/receipts/5/": {
      body: { ...made, method: "cheque", account: null, reference: "004513", cheque_date: "2026-11-15", status: "post_dated" },
    },
  });
  renderAt("/receipts/5", <ReceiptPage />, "/receipts/:id");
  expect(await screen.findByText("Approved. The cheque is posted on 2026-11-15.")).toBeInTheDocument();
});

test("the Accountant sets off an advance against an open invoice", async () => {
  const advance: AdvanceDetail = {
    id: 7, number: "RC26110001", receipt_date: "2026-11-01", customer: { id: 9, code: "C0009", name: "Lanka Tiles PLC" },
    quotation: null, proforma: null, sales_order: null, division: "WS", currency: "LKR", amount: "25000.00",
    amount_lkr: "25000.00", balance_lkr: "25000.00", method: "transfer", status: "approved", created_by: "Cashier",
    account: { id: 1, code: "COM-CUR", name: "Commercial Bank current" }, reference: "CEFT 70001", exchange_rate: "1.000000",
    rate_date: null, set_off_lkr: "0.00", notes: "", journal_entry: { id: 2, number: "JE-2026-0002" }, approved_at: null,
    can_approve: false, history: [], set_offs: [], can_set_off: true,
    open_invoices: [{ id: 21, number: "26NOV_W1_01", invoice_date: "2026-11-02", open_amount: "5794.98" }],
  };
  const calls = mockApi({
    "GET /api/v1/advances/7/": { body: advance },
    "POST /api/v1/advances/7/set-off/": {
      body: {
        ...advance, balance_lkr: "19205.02", set_off_lkr: "5794.98",
        set_offs: [{ invoice: { id: 21, number: "26NOV_W1_01" }, amount: "5794.98", set_off_date: "2026-11-03", journal_entry: "JE-2026-0009", by: "Accountant" }],
      },
    },
  });
  renderAt("/advances/7", <AdvancePage />, "/advances/:id");
  const form = await screen.findByRole("form", { name: "Set off against an invoice" });
  fireEvent.change(within(form).getByLabelText("Invoice"), { target: { value: "21" } });
  expect(within(form).getByLabelText("Amount LKR")).toHaveValue("5794.98"); // what is open, less than the advance
  fireEvent.click(within(form).getByRole("button", { name: "Set off" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/advances/7/set-off/", expect.objectContaining({ method: "POST" })),
  );
  const [, init] = calls.mock.calls.find(([url]) => url === "/api/v1/advances/7/set-off/")!;
  expect(JSON.parse(String(init!.body))).toEqual({ invoice: 21, amount: "5794.98" });
  expect(await screen.findByText(/JE-2026-0009/)).toBeInTheDocument();
});
