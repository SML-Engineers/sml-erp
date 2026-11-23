import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { VoucherDetail, VoucherType } from "../api/vouchers";
import { monthsBack } from "../lib/invoiceDates";
import { addDays, factoryToday } from "../lib/time";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import VoucherPage from "./VoucherPage";

const clerk: CurrentUser = {
  ...sampleUser,
  access: { areas: { vouchers: ["enter", "view"] }, actions: [], divisions: "all" },
};

const cheque: VoucherType = {
  id: 1,
  code: "CHQ",
  name: "Cheque Payment",
  payment_method: "cheque",
  needs_payee: true,
  payee_category: "",
  is_advance: false,
  notes: "",
  sort_order: 10,
  is_active: true,
  in_use: true,
};

const draft: VoucherDetail = {
  id: 9,
  number: "WS261029001",
  status: "draft",
  voucher_type: cheque,
  division: "WS",
  payee: { id: 3, code: "S0003", name: "Lanka Steel (Pvt) Ltd", category: "supplier" },
  transfer_to: null,
  voucher_date: "2026-10-29",
  description: "Steel",
  total_amount: "25000.00",
  created_by: "Nimal",
  created_by_id: 1,
  created_at: "2026-10-29T08:00:00Z",
  submitted_at: null,
  revision: 0,
  amendment_reason: "",
  parent: null,
  revisions: [],
  lines: [
    {
      line_no: 1,
      invoice_no: "INV-1001",
      invoice_date: "2026-10-28",
      description: "",
      amount: "25000.00",
      tax_code: null,
      tax_amount: "0.00",
      total: "25000.00",
      account: null,
      division: "WS",
      job_ref: "",
      splits: [],
    },
  ],
  attachments: [],
  warnings: [],
  can_edit: true,
  payee_balance: { waiting_approval: "0.00", approved_unpaid: "0.00", outstanding: "0.00" },
  approvals: [],
  waiting_level: null,
  waiting_for: null,
  can_act: false,
  uncoded_lines: [],
};

const formApi = {
  "GET /api/v1/voucher-types/": { body: [cheque] },
  "GET /api/v1/divisions/": { body: [{ id: 1, code: "WS", name: "Workshop" }] },
  "GET /api/v1/taxes/": { body: { components: [], codes: [] } },
  "GET /api/v1/vouchers/transfer-accounts/": { body: [] },
  "GET /api/v1/vouchers/payee-balance/3/": {
    body: { waiting_approval: "10000.00", approved_unpaid: "5000.00", outstanding: "15000.00" },
  },
};

test("the clerk creates a draft: division, type, payee with balance, a line", async () => {
  const calls = mockApi({
    ...formApi,
    "GET /api/v1/payees/?q=Lanka": {
      body: [{ id: 3, code: "S0003", name: "Lanka Steel (Pvt) Ltd", category: "supplier" }],
    },
    "POST /api/v1/vouchers/": { status: 201, body: draft },
    "GET /api/v1/vouchers/9/": { body: draft },
  });
  renderAt("/vouchers/new", <VoucherPage me={clerk} />, "/vouchers/:id");

  const form = await screen.findByRole("form", { name: "Voucher details" });
  await within(form).findByRole("option", { name: "WS Workshop" });
  fireEvent.change(within(form).getByLabelText("Division"), { target: { value: "WS" } });
  await within(form).findByRole("option", { name: "Cheque Payment" });
  // The payee box is there from the start, waiting for the type.
  expect(within(form).getByLabelText("Find the payee (name or code)")).toBeDisabled();
  expect(within(form).getByPlaceholderText("Choose the type first")).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Type"), { target: { value: "CHQ" } });
  fireEvent.change(within(form).getByLabelText("Find the payee (name or code)"), { target: { value: "Lanka" } });
  fireEvent.click(await within(form).findByRole("button", { name: "S0003 Lanka Steel (Pvt) Ltd" }));
  expect(await within(form).findByText(/outstanding on vouchers: LKR 15,000.00/)).toBeInTheDocument();
  // Once chosen, the list of matches closes.
  expect(within(form).queryByRole("button", { name: "S0003 Lanka Steel (Pvt) Ltd" })).not.toBeInTheDocument();
  expect(within(form).getByLabelText("Find the payee (name or code)")).toHaveValue("");
  fireEvent.change(within(form).getByLabelText("Invoice no., line 1"), { target: { value: "INV-1001" } });
  fireEvent.change(within(form).getByLabelText("Amount, line 1"), { target: { value: "25000.00" } });
  // Owner, 18 Nov 2026: tax comes only from a tax code; it is never typed in.
  expect(within(form).queryByLabelText("Tax, line 1")).not.toBeInTheDocument();
  expect(within(form).getByText("0.00 until a tax code is chosen")).toBeInTheDocument();
  expect(within(form).getByRole("option", { name: "No tax code yet" })).toBeInTheDocument();
  fireEvent.click(within(form).getByRole("button", { name: "Save draft" }));

  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/vouchers/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    voucher_type: "CHQ",
    division: "WS",
    payee: 3,
    transfer_to: null,
    lines: [{ invoice_no: "INV-1001", amount: "25000.00", tax_code: null, tax_amount: "0.00" }],
  });
  expect(await screen.findByRole("heading", { name: "Voucher WS261029001" })).toBeInTheDocument();
});

test("scans are uploaded and a duplicate file is flagged", async () => {
  const calls = mockApi({
    ...formApi,
    "GET /api/v1/vouchers/9/": { body: draft },
    "POST /api/v1/vouchers/9/attachments/": {
      status: 201,
      body: {
        ...draft,
        attachments: [{ id: 4, file_name: "invoice.pdf", content_type: "application/pdf", size: 2048, sha256: "ab", uploaded_at: "" }],
        upload_warnings: ["This file is already attached to voucher WS261028004."],
      },
    },
  });
  renderAt("/vouchers/9", <VoucherPage me={clerk} />, "/vouchers/:id");

  const files = await screen.findByRole("region", { name: "Scanned invoices and receipts" });
  const input = within(files).getByLabelText("Choose files");
  fireEvent.change(input, { target: { files: [new File(["%PDF-1.7"], "invoice.pdf", { type: "application/pdf" })] } });
  expect(await within(files).findByRole("link", { name: "invoice.pdf" })).toBeInTheDocument();
  expect(within(files).getByText(/already attached to voucher WS261028004/)).toBeInTheDocument();
  expect(calls).toHaveBeenCalledWith("/api/v1/vouchers/9/attachments/", expect.objectContaining({ method: "POST" }));
  expect(within(files).getByLabelText("Take a photo")).toHaveAttribute("capture", "environment");
});

test("a submitted voucher is shown read-only with its approval history", async () => {
  mockApi({
    ...formApi,
    "GET /api/v1/vouchers/9/": {
      body: {
        ...draft,
        status: "submitted",
        can_edit: false,
        approvals: [{ level: 1, action: "submit", user: "Nimal", reason: "", acted_at: "2026-10-29T09:00:00Z" }],
      },
    },
  });
  renderAt("/vouchers/9", <VoucherPage me={clerk} />, "/vouchers/:id");

  expect(await screen.findByRole("region", { name: "Voucher details" })).toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "Voucher details" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Submit for approval" })).not.toBeInTheDocument();
  const history = screen.getByRole("region", { name: "Approval history" });
  expect(within(history).getByText(/L1 · Submitted · Nimal/)).toBeInTheDocument();
});

// Owner, 16 Nov 2026: the Director opened a voucher from the bell and found no Approve.
test("a voucher waiting for me says so and opens it where I approve it", async () => {
  const director: CurrentUser = {
    ...sampleUser,
    full_name: "Ruwan Jayasinghe",
    access: { areas: { vouchers: ["approve", "view"] }, actions: [], divisions: "all" },
  };
  mockApi({
    ...formApi,
    "GET /api/v1/vouchers/9/": {
      body: { ...draft, status: "accountant_approved", can_edit: false, waiting_level: 3, waiting_for: "Director", can_act: true },
    },
  });
  renderAt("/vouchers/9", <VoucherPage me={director} />, "/vouchers/:id");

  const box = await screen.findByRole("region", { name: "Waiting for your approval" });
  expect(within(box).getByText(/waits for your approval at level 3 \(Director\)/)).toBeInTheDocument();
  expect(within(box).getByRole("link", { name: "Open to approve" })).toHaveAttribute("href", "/vouchers/review?open=9");
});

test("a voucher that does not wait for me shows no approval box", async () => {
  mockApi({
    ...formApi,
    "GET /api/v1/vouchers/9/": {
      body: { ...draft, status: "submitted", can_edit: false, waiting_level: 2, waiting_for: "Accountant", can_act: false },
    },
  });
  renderAt("/vouchers/9", <VoucherPage me={clerk} />, "/vouchers/:id");

  expect(await screen.findByRole("region", { name: "Voucher details" })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Waiting for your approval" })).not.toBeInTheDocument();
});

// Owner, 17 Nov 2026: a Cancel button on each payment row opens its reason box; no reason
// boxes are open under the table until asked for.
test("each payment has its own Cancel button that opens the reason box", async () => {
  const payment = (id: number, number: string) => ({
    id,
    number,
    voucher: { id: 9, number: "IM261031002" },
    payee: "Polymer Resins Lanka (Pvt) Ltd",
    account: { id: 1, code: "COM-CUR", name: "Commercial Bank current" },
    method: "cheque" as const,
    reference: String(100000 + id),
    cheque_date: null,
    payment_date: "2026-11-17",
    amount: "10000.00",
    journal_entry: "JV26110018",
    notes: "",
    created_by: "Sunil Fernando",
    created_at: "2026-11-17T09:00:00Z",
    can_cancel: true,
  });
  const calls = mockApi({
    ...formApi,
    "GET /api/v1/vouchers/9/": {
      body: {
        ...draft,
        status: "partly_paid",
        can_edit: false,
        remaining: "90000.00",
        payments: [payment(1, "PY26100001"), payment(2, "PY26110001")],
      },
    },
    "POST /api/v1/payments/2/cancel/": { body: payment(2, "PY26110001") },
  });
  renderAt("/vouchers/9", <VoucherPage me={clerk} />, "/vouchers/:id");

  const table = await screen.findByRole("table", { name: "Payments" });
  expect(screen.queryByRole("textbox", { name: /Why cancel it/ })).not.toBeInTheDocument();
  fireEvent.click(within(table).getByRole("button", { name: "Cancelling payment PY26110001" }));
  const box = screen.getByRole("form", { name: "Cancelling payment PY26110001" });
  const send = within(box).getByRole("button", { name: "Ask the Director" });
  expect(send).toBeDisabled();
  fireEvent.change(within(box).getByRole("textbox"), { target: { value: "Cheque spoiled" } });
  fireEvent.click(send);
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/payments/2/cancel/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "Cheque spoiled" }) }),
    ),
  );
  // Only one box at a time, and none for the other payment.
  expect(screen.queryByRole("form", { name: "Cancelling payment PY26100001" })).not.toBeInTheDocument();
});

// Owner, 20 Nov 2026: more than 2 months old needs "Yes, the date is right"; more than a year
// old cannot be entered; the Accountant and the Director see a note.
test("an old invoice date asks the clerk to confirm it, a very old one is refused", async () => {
  const today = factoryToday();
  const old = addDays(monthsBack(today, 2), -1);
  const calls = mockApi({
    ...formApi,
    "GET /api/v1/vouchers/9/": { body: draft },
    "PATCH /api/v1/vouchers/9/": { body: draft },
  });
  renderAt("/vouchers/9", <VoucherPage me={clerk} />, "/vouchers/:id");

  const form = await screen.findByRole("form", { name: "Voucher details" });
  expect(within(form).queryByText(/more than 2 months old/)).not.toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Invoice date, line 1"), { target: { value: old } });
  expect(within(form).getByText("This invoice is more than 2 months old. Is the date right?")).toBeInTheDocument();
  fireEvent.click(within(form).getByLabelText("Yes, the date is right, line 1"));
  fireEvent.click(within(form).getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/vouchers/9/", expect.objectContaining({ method: "PATCH" })));
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "PATCH")!;
  expect(JSON.parse(String(init!.body)).lines[0]).toMatchObject({ invoice_date: old, date_confirmed: true });

  // A new date clears the tick; a date more than a year old is refused.
  fireEvent.change(within(form).getByLabelText("Invoice date, line 1"), { target: { value: "2006-11-13" } });
  expect(within(form).getByRole("alert")).toHaveTextContent("more than a year old and cannot be entered");
  expect(within(form).queryByLabelText("Yes, the date is right, line 1")).not.toBeInTheDocument();
});

test("the approvers see a note on an old invoice date the clerk confirmed", async () => {
  mockApi({
    ...formApi,
    "GET /api/v1/vouchers/9/": {
      body: {
        ...draft,
        status: "submitted",
        can_edit: false,
        lines: [{ ...draft.lines[0], invoice_date: "2026-08-13", old_date_confirmed: true }],
      },
    },
  });
  renderAt("/vouchers/9", <VoucherPage me={clerk} />, "/vouchers/:id");

  const note = await screen.findByRole("note", { name: "Old invoice dates" });
  expect(note).toHaveTextContent("Line 1: the invoice is dated 13/08/2026, more than 2 months old when it was entered.");
  expect(note).toHaveTextContent("The Clerk confirmed the date is right.");
});

test("asks before submitting, naming the voucher, the amount and the payee (testing T49)", async () => {
  const calls = mockApi({
    ...formApi,
    "GET /api/v1/vouchers/9/": { body: draft },
    "POST /api/v1/vouchers/9/submit/": { body: { ...draft, status: "submitted", can_edit: false } },
  });
  renderAt("/vouchers/9", <VoucherPage me={clerk} />, "/vouchers/:id", { ask: true });
  const panel = await screen.findByRole("region", { name: "Submit for approval" });
  fireEvent.click(within(panel).getByRole("button", { name: "Submit for approval" }));
  const dialog = await screen.findByRole("alertdialog", {
    name: "Submit voucher WS261029001 for 25,000.00 to Lanka Steel (Pvt) Ltd for approval?",
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "No, go back" }));
  expect(calls).not.toHaveBeenCalledWith("/api/v1/vouchers/9/submit/", expect.anything());

  fireEvent.click(within(panel).getByRole("button", { name: "Submit for approval" }));
  fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Submit for approval" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/vouchers/9/submit/", expect.objectContaining({ method: "POST" })));
});
