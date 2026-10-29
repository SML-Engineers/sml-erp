import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { AmendmentRow, VoucherDetail, VoucherSummary, VoucherType } from "../api/vouchers";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import AmendmentsPage from "./AmendmentsPage";
import VoucherPage from "./VoucherPage";
import VouchersPage from "./VouchersPage";

const clerk: CurrentUser = {
  ...sampleUser,
  access: { areas: { vouchers: ["enter", "view"] }, actions: [], divisions: "all" },
};

const summary: VoucherSummary = {
  id: 1,
  number: "WS261029001",
  status: "director_approved",
  voucher_type: { code: "CHQ", name: "Cheque Payment" },
  division: "WS",
  payee: { id: 3, name: "Lanka Steel" },
  voucher_date: "2026-10-29",
  total_amount: "1000.00",
  created_by: "Nimal",
  attachments: 1,
  actions: ["resources", "print", "amend"],
};

const cheque: VoucherType = {
  id: 1, code: "CHQ", name: "Cheque Payment", payment_method: "cheque", needs_payee: true,
  payee_category: "", is_advance: false, notes: "", sort_order: 10, is_active: true, in_use: true,
};

const detail = (over: Partial<VoucherDetail>): VoucherDetail => ({
  ...summary,
  voucher_type: cheque,
  payee: { id: 3, code: "S0003", name: "Lanka Steel", category: "supplier" },
  transfer_to: null,
  description: "",
  created_by_id: 1,
  created_at: "2026-10-29T08:00:00Z",
  submitted_at: "2026-10-29T08:05:00Z",
  revision: 0,
  amendment_reason: "",
  parent: null,
  revisions: [],
  lines: [],
  attachments: [],
  warnings: [],
  can_edit: false,
  payee_balance: null,
  approvals: [],
  waiting_level: null,
  waiting_for: null,
  can_act: false,
  uncoded_lines: [],
  ...over,
});

const formApi = {
  "GET /api/v1/voucher-types/": { body: [cheque] },
  "GET /api/v1/taxes/": { body: { components: [], codes: [] } },
  "GET /api/v1/vouchers/transfer-accounts/": { body: [] },
  "GET /api/v1/vouchers/payee-balance/3/": { body: { waiting_approval: "0.00", approved_unpaid: "0.00", outstanding: "0.00" } },
};

test("Amend asks why, then starts the new revision", async () => {
  const calls = mockApi({
    "GET /api/v1/vouchers/": { body: [summary] },
    "GET /api/v1/voucher-types/": { body: [] },
    "POST /api/v1/vouchers/1/amend/": {
      status: 201,
      body: detail({ id: 7, number: "WS261029001-R1", status: "draft", revision: 1, parent: { id: 1, number: "WS261029001" } }),
    },
  });
  renderAt("/vouchers", <VouchersPage me={clerk} />);

  fireEvent.click(await screen.findByRole("button", { name: "Actions for WS261029001" }));
  const menu = screen.getByRole("menu", { name: "Actions for WS261029001" });
  expect(within(menu).queryByRole("menuitem", { name: "Edit" })).not.toBeInTheDocument();
  fireEvent.click(within(menu).getByRole("menuitem", { name: "Amend" }));
  const dialog = screen.getByRole("dialog", { name: "Amend voucher WS261029001" });
  const start = within(dialog).getByRole("button", { name: "Start amendment" });
  expect(start).toBeDisabled();
  fireEvent.change(within(dialog).getByLabelText("Why is it being amended? (required)"), {
    target: { value: "Corrected invoice" },
  });
  fireEvent.click(start);
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/vouchers/1/amend/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "Corrected invoice" }) }),
    ),
  );
  // It opens the new draft (another page, not part of this test's routes).
  await waitFor(() => expect(screen.queryByRole("heading", { name: "Payment vouchers" })).not.toBeInTheDocument());
});

test("the replaced voucher links to its amendment, and the amendment to the original", async () => {
  mockApi({
    ...formApi,
    "GET /api/v1/vouchers/1/": {
      body: detail({ status: "amended", actions: ["resources", "print"], revisions: [{ id: 7, number: "WS261029001-R1", status: "submitted" }] }),
    },
    "GET /api/v1/vouchers/7/": {
      body: detail({
        id: 7, number: "WS261029001-R1", status: "draft", revision: 1, can_edit: true,
        parent: { id: 1, number: "WS261029001" }, amendment_reason: "Corrected invoice",
      }),
    },
  });
  const { unmount } = renderAt("/vouchers/1", <VoucherPage me={clerk} />, "/vouchers/:id");
  const replaced = await screen.findByText(/replaced and cannot be paid/);
  expect(within(replaced).getByRole("link", { name: "WS261029001-R1" })).toHaveAttribute("href", "/vouchers/7");
  unmount();

  renderAt("/vouchers/7", <VoucherPage me={clerk} />, "/vouchers/:id");
  const note = await screen.findByText(/Amendment \(revision 1\) of voucher/);
  expect(within(note).getByRole("link", { name: "WS261029001" })).toHaveAttribute("href", "/vouchers/1");
  expect(note).toHaveTextContent("Corrected invoice");
});

test("a returned voucher shows the reason it came back", async () => {
  mockApi({
    ...formApi,
    "GET /api/v1/vouchers/1/": {
      body: detail({
        status: "returned",
        can_edit: true,
        approvals: [
          { level: 1, action: "submit", user: "Nimal", reason: "", acted_at: "2026-10-29T08:05:00Z" },
          { level: 3, action: "return", user: "Mewantha", reason: "Attach the delivery note", acted_at: "2026-10-29T09:00:00Z" },
        ],
      }),
    },
  });
  renderAt("/vouchers/1", <VoucherPage me={clerk} />, "/vouchers/:id");
  expect(await screen.findByText(/Returned to you by Mewantha/)).toHaveTextContent("Attach the delivery note");
});

test("the amendments list shows the original and the change in amount", async () => {
  const row: AmendmentRow = {
    ...summary,
    id: 7,
    number: "WS261029001-R1",
    total_amount: "1150.00",
    actions: ["resources", "print"],
    revision: 1,
    amendment_reason: "Corrected invoice",
    parent: { id: 1, number: "WS261029001", total_amount: "1000.00" },
  };
  mockApi({ "GET /api/v1/vouchers/amendments/": { body: [row] } });
  renderAt("/vouchers/amendments", <AmendmentsPage />);

  const table = await screen.findByRole("table", { name: "Amendments" });
  expect(within(table).getByRole("link", { name: "WS261029001" })).toHaveAttribute("href", "/vouchers/1");
  expect(within(table).getByText("Corrected invoice")).toBeInTheDocument();
  expect(within(table).getByText("150.00")).toBeInTheDocument();
  expect(within(table).getByText("1,150.00")).toBeInTheDocument();
});
