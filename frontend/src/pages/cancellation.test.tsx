import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { CancellationRow, VoucherDetail, VoucherSummary, VoucherType } from "../api/vouchers";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import CancellationsPage from "./CancellationsPage";
import VoucherPage from "./VoucherPage";
import VouchersPage from "./VouchersPage";

const director: CurrentUser = {
  ...sampleUser,
  access: { areas: { vouchers: ["approve", "view"] }, actions: [], divisions: "all" },
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
  actions: ["resources", "print", "amend", "cancel"],
};

const cheque: VoucherType = {
  id: 1, code: "CHQ", name: "Cheque Payment", payment_method: "cheque", needs_payee: true,
  payee_category: "", is_advance: false, notes: "", sort_order: 10, is_active: true, in_use: true,
};

const pending = {
  id: 3,
  status: "pending" as const,
  reason: "Supplier will not deliver",
  requested_by: "Kumari",
  requested_at: "2026-10-29T09:00:00Z",
  decided_by: null,
  decided_at: null,
  decision_reason: "",
  can_decide: true,
};

const detail: VoucherDetail = {
  ...summary,
  actions: ["resources", "print"],
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
  cancellation: pending,
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
};

test("the Accountant requests a cancellation with a reason", async () => {
  const calls = mockApi({
    "GET /api/v1/vouchers/": { body: [summary] },
    "GET /api/v1/voucher-types/": { body: [] },
    "POST /api/v1/vouchers/1/cancel/": { body: detail },
  });
  renderAt("/vouchers", <VouchersPage me={director} />);

  fireEvent.click(await screen.findByRole("button", { name: "Actions for WS261029001" }));
  fireEvent.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "Request cancellation" }));
  const dialog = screen.getByRole("dialog", { name: "Request cancellation of WS261029001" });
  const send = within(dialog).getByRole("button", { name: "Send to the Director" });
  expect(send).toBeDisabled();
  fireEvent.change(within(dialog).getByLabelText("Why should it be cancelled? (required)"), {
    target: { value: "Supplier will not deliver" },
  });
  fireEvent.click(send);
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/vouchers/1/cancel/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "Supplier will not deliver" }) }),
    ),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

test("the Director decides on the voucher's page; rejecting needs a comment", async () => {
  let latest: VoucherDetail = detail;
  const calls = mockApi({
    "GET /api/v1/vouchers/1/": () => ({ body: latest }),
    "POST /api/v1/vouchers/cancellations/3/approve/": () => {
      latest = {
        ...detail,
        status: "cancelled",
        cancellation: { ...pending, status: "approved", can_decide: false, decided_by: "Mewantha", decided_at: "2026-10-29T10:00:00Z" },
      };
      return { body: latest };
    },
  });
  renderAt("/vouchers/1", <VoucherPage me={director} />, "/vouchers/:id");

  const panel = await screen.findByRole("region", { name: "Cancellation" });
  expect(panel).toHaveTextContent("Waiting for the Director · requested by Kumari");
  expect(panel).toHaveTextContent("Supplier will not deliver");
  expect(within(panel).getByRole("button", { name: "Reject" })).toBeDisabled();
  fireEvent.click(within(panel).getByRole("button", { name: "Approve cancellation" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/vouchers/cancellations/3/approve/",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(await within(panel).findByText(/Decided by Mewantha/)).toBeInTheDocument();
  expect(within(panel).queryByRole("button", { name: "Approve cancellation" })).not.toBeInTheDocument();
});

test("the requests list shows those waiting, with a link to decide", async () => {
  const row: CancellationRow = {
    ...pending,
    voucher: { id: 1, number: "WS261029001", status: "director_approved", payee: "Lanka Steel", total_amount: "1000.00" },
  };
  mockApi({
    "GET /api/v1/vouchers/cancellations/?pending=1": { body: [row] },
    "GET /api/v1/vouchers/cancellations/": { body: [row, { ...row, id: 2, status: "rejected", can_decide: false, decided_by: "Mewantha", decision_reason: "Pay it" }] },
  });
  renderAt("/vouchers/cancellations", <CancellationsPage />);

  const table = await screen.findByRole("table", { name: "Cancellation requests" });
  expect(within(table).getByRole("link", { name: "Decide" })).toHaveAttribute("href", "/vouchers/1");
  fireEvent.click(screen.getByLabelText("Only those waiting for the Director"));
  await waitFor(() =>
    expect(within(screen.getByRole("table", { name: "Cancellation requests" })).getByText("Mewantha: Pay it")).toBeInTheDocument(),
  );
});
