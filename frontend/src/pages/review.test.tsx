import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { LedgerAccount } from "../api/accounts";
import type { VoucherDetail } from "../api/vouchers";
import { mockApi, renderAt } from "../test-utils";
import ReviewPage from "./ReviewPage";

const electricity: LedgerAccount = {
  id: 61,
  number: "6100",
  name: "Electricity",
  full_name: "Electricity",
  depth: 0,
  parent: null,
  account_type: "expense",
  account_type_label: "Expense",
  section: "profit_and_loss",
  detail_type: { id: 1, name: "Electricity" },
  description: "",
  default_division: "HO",
  default_tax_code: null,
  system_role: null,
  is_active: true,
  merged_into: null,
  in_use: false,
  company_account: null,
};

const voucher: VoucherDetail = {
  id: 9,
  number: "WS261029001",
  status: "submitted",
  voucher_type: {
    id: 1, code: "ONL", name: "Online Payment", payment_method: "transfer", needs_payee: true,
    payee_category: "", is_advance: false, notes: "", sort_order: 20, is_active: true, in_use: true,
  },
  division: "WS",
  payee: { id: 3, code: "S0003", name: "Ceylon Electricity Board", category: "utility" },
  transfer_to: null,
  voucher_date: "2026-10-29",
  description: "October electricity",
  total_amount: "25000.00",
  created_by: "Nimal",
  created_by_id: 1,
  created_at: "2026-10-29T08:00:00Z",
  submitted_at: "2026-10-29T08:05:00Z",
  revision: 0,
  lines: [
    {
      line_no: 1, invoice_no: "CEB-1029", invoice_date: "2026-10-28", description: "", amount: "25000.00",
      tax_code: null, tax_amount: "0.00", total: "25000.00", account: null, division: "WS", job_ref: "", splits: [],
    },
  ],
  attachments: [
    { id: 4, file_name: "bill.pdf", content_type: "application/pdf", size: 2048, sha256: "ab", uploaded_at: "" },
  ],
  warnings: [],
  can_edit: false,
  payee_balance: { waiting_approval: "25000.00", approved_unpaid: "0.00", outstanding: "25000.00" },
  approvals: [],
  waiting_level: 2,
  waiting_for: "Accountant",
  can_act: true,
  uncoded_lines: [1],
};

const api = (extra: Parameters<typeof mockApi>[0] = {}) => ({
  "GET /api/v1/vouchers/waiting/": {
    body: [{ ...voucher, voucher_type: { code: "ONL", name: "Online Payment" }, payee: { id: 3, name: "Ceylon Electricity Board" }, attachments: 1 }],
  },
  "GET /api/v1/vouchers/9/": { body: voucher },
  "GET /api/v1/chart-of-accounts/": { body: [electricity] },
  "GET /api/v1/divisions/": { body: [{ id: 1, code: "WS", name: "Workshop" }, { id: 2, code: "IM", name: "Moulding" }, { id: 3, code: "HO", name: "Head Office" }] },
  "GET /api/v1/taxes/": { body: { components: [], codes: [] } },
  ...extra,
});

test("the accountant codes an electricity bill split across divisions and approves it", async () => {
  const calls = mockApi(
    api({
      "PATCH /api/v1/vouchers/9/coding/": { body: { ...voucher, uncoded_lines: [] } },
      "POST /api/v1/vouchers/9/approve/": { body: { ...voucher, status: "accountant_approved", can_act: false } },
    }),
  );
  renderAt("/vouchers/review", <ReviewPage />);

  const queue = await screen.findByRole("region", { name: "Queue" });
  fireEvent.click(within(queue).getByRole("button", { name: /WS261029001/ }));
  const panel = await screen.findByRole("region", { name: "Voucher WS261029001" });
  expect(within(panel).getByTitle("bill.pdf")).toHaveAttribute("src", "/api/v1/vouchers/9/attachments/4/");

  await within(panel).findByRole("option", { name: "6100 Electricity" });
  fireEvent.change(within(panel).getByLabelText("Account, line 1"), { target: { value: "61" } });
  expect(within(panel).getByLabelText("Division, line 1")).toHaveValue("HO"); // the account's default
  fireEvent.click(within(panel).getByLabelText("Split across divisions"));
  const split = within(panel).getByRole("group", { name: "Split of line 1" });
  fireEvent.click(within(split).getByLabelText("By percentage"));
  fireEvent.change(within(split).getByLabelText("Line 1, part 1: %"), { target: { value: "60" } });
  fireEvent.change(within(split).getByLabelText("Line 1, part 2: division"), { target: { value: "IM" } });
  fireEvent.change(within(split).getByLabelText("Line 1, part 2: %"), { target: { value: "40" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Save coding" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/vouchers/9/coding/", expect.objectContaining({ method: "PATCH" })),
  );
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "PATCH")!;
  expect(JSON.parse(String(init!.body))).toEqual({
    lines: [
      {
        line_no: 1,
        account: 61,
        division: null,
        tax_code: null,
        tax_amount: "0.00",
        job_ref: "",
        splits: [
          { division: "WS", percent: "60" },
          { division: "IM", percent: "40" },
        ],
      },
    ],
  });

  fireEvent.change(within(panel).getByLabelText("Comment (approve) or reason (return, reject)"), { target: { value: "checked meter" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Approve" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/vouchers/9/approve/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ comment: "checked meter" }) }),
    ),
  );
});

test("returning sends the reason", async () => {
  const calls = mockApi(api({ "POST /api/v1/vouchers/9/return/": { body: { ...voucher, status: "returned" } } }));
  renderAt("/vouchers/review", <ReviewPage />);

  fireEvent.click(await screen.findByRole("button", { name: /WS261029001/ }));
  const panel = await screen.findByRole("region", { name: "Voucher WS261029001" });
  fireEvent.change(within(panel).getByLabelText("Comment (approve) or reason (return, reject)"), { target: { value: "Attach the meter reading" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Return to Clerk" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/vouchers/9/return/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "Attach the meter reading" }) }),
    ),
  );
});
