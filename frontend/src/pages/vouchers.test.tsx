import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { VoucherDetail, VoucherType } from "../api/vouchers";
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
  fireEvent.change(within(form).getByLabelText("Type"), { target: { value: "CHQ" } });
  fireEvent.change(within(form).getByLabelText("Find the payee (name or code)"), { target: { value: "Lanka" } });
  fireEvent.click(await within(form).findByRole("button", { name: "S0003 Lanka Steel (Pvt) Ltd" }));
  expect(await within(form).findByText(/outstanding on vouchers: LKR 15,000.00/)).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Invoice no., line 1"), { target: { value: "INV-1001" } });
  fireEvent.change(within(form).getByLabelText("Amount, line 1"), { target: { value: "25000.00" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save draft" }));

  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/vouchers/", expect.objectContaining({ method: "POST" })),
  );
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
        attachments: [
          { id: 4, file_name: "invoice.pdf", content_type: "application/pdf", size: 2048, sha256: "ab", uploaded_at: "" },
        ],
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
