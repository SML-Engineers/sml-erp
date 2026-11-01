import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { PaidInvoice, VoucherDetail, VoucherType } from "../api/vouchers";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import VoucherPage from "./VoucherPage";

const clerk: CurrentUser = { ...sampleUser, access: { areas: { vouchers: ["enter", "view"] }, actions: [], divisions: "all" } };

const cheque: VoucherType = {
  id: 1, code: "CHQ", name: "Cheque Payment", payment_method: "cheque", needs_payee: true, payee_category: "", is_advance: false,
  notes: "", sort_order: 10, is_active: true, in_use: true,
};

const paid: PaidInvoice = {
  id: 5, number: "SI26110101", invoice_no: "INV-77", invoice_date: "2026-11-01", due_date: "2026-12-01", total_lkr: "12500.00",
  on_vouchers: "12500.00",
  lines: [
    {
      item: { code: "M6-INSERT", name: "Brass insert", unit: "pcs" },
      po: { id: 9, label: "PO26110101", quantity: "1000.000", unit_price: "12.50" },
      grn: { id: 4, number: "GRN26110101", received: "1000.000", accepted: "1000.000" },
      invoice: { quantity: "1000.000", unit_price: "12.50", total: "12500.00" },
      matches: true,
    },
  ],
};

const draft: VoucherDetail = {
  id: 9, number: "IM261101001", status: "draft", voucher_type: cheque, division: "IM",
  payee: { id: 3, code: "S0003", name: "Fasteners Lanka", category: "supplier" }, transfer_to: null, voucher_date: "2026-11-01",
  description: "Inserts", total_amount: "0.00", created_by: "Clerk", created_by_id: 1, created_at: "2026-11-01T08:00:00Z",
  submitted_at: null, revision: 0, amendment_reason: "", parent: null, revisions: [], lines: [], attachments: [], warnings: [],
  can_edit: true, payee_balance: { waiting_approval: "0.00", approved_unpaid: "0.00", outstanding: "0.00" }, approvals: [],
  waiting_level: null, waiting_for: null, can_act: false, uncoded_lines: [],
};

const withInvoice: VoucherDetail = {
  ...draft,
  total_amount: "12500.00",
  lines: [
    {
      line_no: 1, invoice_no: "INV-77", invoice_date: "2026-11-01", description: "Supplier invoice SI26110101", amount: "12500.00",
      tax_code: null, tax_amount: "0.00", total: "12500.00", account: { id: 7, number: "2000", name: "Accounts payable" }, division: "IM",
      job_ref: "", splits: [], supplier_invoice: paid,
    },
  ],
};

test("the clerk pays a matched supplier invoice from the voucher form", async () => {
  const calls = mockApi({
    "GET /api/v1/vouchers/9/": { body: { ...draft, lines: [] } },
    "GET /api/v1/voucher-types/": { body: [cheque] },
    "GET /api/v1/taxes/": { body: { components: [], codes: [] } },
    "GET /api/v1/vouchers/transfer-accounts/": { body: [] },
    "GET /api/v1/vouchers/payee-balance/3/": { body: { waiting_approval: "0.00", approved_unpaid: "0.00", outstanding: "0.00" } },
    "GET /api/v1/supplier-invoices/payable/?supplier=3&division=IM": {
      body: [
        {
          id: 5, number: "SI26110101", invoice_no: "INV-77", invoice_date: "2026-11-01", due_date: "2026-12-01", status: "posted",
          division: "IM", supplier: { id: 3, code: "S0003", name: "Fasteners Lanka" }, currency: "LKR", total_amount: "12500.00",
          total_lkr: "12500.00", created_by: "Clerk", unpaid: "12500.00",
        },
      ],
    },
    "PATCH /api/v1/vouchers/9/": { body: withInvoice },
  });
  renderAt("/vouchers/9", <VoucherPage me={clerk} />, "/vouchers/:id");
  const offer = await screen.findByRole("region", { name: "Matched supplier invoices of this payee still to pay" });
  expect(within(offer).getByText(/INV-77, due 2026-12-01: LKR 12,500.00 unpaid/)).toBeInTheDocument();
  fireEvent.click(within(offer).getByRole("button", { name: "Pay INV-77" }));
  const form = screen.getByRole("form", { name: "Voucher details" });
  expect(within(form).getByText(/pays a matched supplier invoice/)).toBeInTheDocument();
  fireEvent.click(within(form).getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/vouchers/9/", expect.objectContaining({ method: "PATCH" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/vouchers/9/" && i?.method === "PATCH")!;
  expect(JSON.parse(String(init!.body)).lines).toMatchObject([{ supplier_invoice: 5, amount: "12500.00", invoice_no: "INV-77" }]);
});

test("the approvers see PO, GRN and invoice side by side", async () => {
  mockApi({ "GET /api/v1/vouchers/9/": { body: { ...withInvoice, status: "submitted", can_edit: false } } });
  renderAt("/vouchers/9", <VoucherPage me={clerk} />, "/vouchers/:id");
  const match = await screen.findByRole("table", { name: "Three-way match of invoice INV-77" });
  expect(within(match).getByRole("link", { name: "PO26110101" })).toHaveAttribute("href", "/purchase-orders/9");
  expect(within(match).getByText(/1,000 received, 1,000 accepted by QC/)).toBeInTheDocument();
  expect(within(match).getByText("1,000 × 12.50 = 12,500.00")).toBeInTheDocument();
});
