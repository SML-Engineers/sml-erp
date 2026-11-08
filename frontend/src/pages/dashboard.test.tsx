import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { VoucherDashboard } from "../api/vouchers";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import HomePage from "./HomePage";
import VoucherReportsPage from "./VoucherReportsPage";
import VouchersPage from "./VouchersPage";

const accountant: CurrentUser = {
  ...sampleUser,
  access: {
    areas: { dashboard: ["view"], vouchers: ["approve", "enter", "view"], payments: ["view"] },
    actions: [],
    divisions: "all",
  },
};

const bands = { "0–2 days": 1, "3–7 days": 0, "8–14 days": 0, "15 days or more": 1 };

const figures: VoucherDashboard = {
  division: "",
  can_approve: true,
  can_enter: true,
  sees_approvals: true,
  waiting_for_me: { count: 2, total: "550.00" },
  my_vouchers: { draft: { count: 0, total: "0.00" }, returned: { count: 1, total: "75.00" } },
  by_level: [
    { level: 2, waiting_for: "L2 Accountant", count: 2, total: "550.00", bands },
    { level: 3, waiting_for: "L3 Director", count: 1, total: "900.00", bands: { ...bands, "15 days or more": 0 } },
  ],
  pending_count: 3,
  unpaid: { count: 1, total: "1000.00", remaining: "600.00" },
  paid_this_month: { count: 1, total: "400.00", from: "2026-10-01", to: "2026-10-29" },
  by_division: [
    {
      code: "WS",
      name: "Workshop",
      pending: 2,
      pending_total: "1150.00",
      unpaid: { count: 1, total: "1000.00", remaining: "600.00" },
      paid_this_month: "400.00",
    },
    {
      code: "IM",
      name: "Moulding",
      pending: 1,
      pending_total: "300.00",
      unpaid: { count: 0, total: "0.00", remaining: "0.00" },
      paid_this_month: "0.00",
    },
  ],
  oldest: [
    {
      id: 7,
      number: "IM261012001",
      type: "Cheque Payment",
      division: "IM",
      payee: "CEB",
      level: 2,
      waiting_for: "L2 Accountant",
      approvers: "Kumari",
      since: "2026-10-12T09:00:00Z",
      days: 17,
      band: "15 days or more",
      total_amount: "300.00",
    },
  ],
};

const homeApi = (extra = {}) => ({
  "GET /api/v1/health/": { body: { status: "ok", database: "ok", version: "0.1.0" } },
  "GET /api/v1/vouchers/dashboard/": { body: figures },
  ...extra,
});

test("every tile opens the list behind it", async () => {
  mockApi(homeApi());
  renderAt("/dashboard", <HomePage user={accountant} />);

  const board = await screen.findByRole("region", { name: "Vouchers" });
  await within(board).findByText("Waiting for my approval");
  expect(within(board).getByRole("link", { name: /Waiting for my approval\s*2/ })).toHaveAttribute("href", "/vouchers/review");
  expect(within(board).getByRole("link", { name: /Returned to me\s*1/ })).toHaveAttribute("href", "/vouchers?status=returned");
  expect(within(board).getByRole("link", { name: /Approved, not yet paid\s*LKR 600.00/ })).toHaveAttribute("href", "/payments");
  expect(within(board).getByRole("link", { name: /Paid this month/ })).toHaveAttribute("href", "/payments?from=2026-10-01&to=2026-10-29");
  const levels = within(board).getByRole("table", { name: "Waiting by level and age" });
  expect(within(levels).getByRole("link", { name: "L2 Accountant" })).toHaveAttribute("href", "/vouchers/reports?tab=pending&level=2");
  expect(within(board).getByRole("link", { name: "IM261012001" })).toHaveAttribute("href", "/vouchers/7");
  const divisions = within(board).getByRole("table", { name: "By division" });
  expect(within(divisions).getByRole("link", { name: /1 · 300.00/ })).toHaveAttribute("href", "/vouchers/reports?tab=pending&division=IM");
});

test("choosing a division shows its figures and keeps it in the links", async () => {
  const calls = mockApi(
    homeApi({
      "GET /api/v1/vouchers/dashboard/?division=IM": {
        body: { ...figures, division: "IM", waiting_for_me: { count: 1, total: "300.00" }, by_division: [figures.by_division[1]] },
      },
    }),
  );
  renderAt("/dashboard", <HomePage user={accountant} />);

  const picker = await screen.findByRole("group", { name: "Division" });
  fireEvent.click(within(picker).getByRole("button", { name: "IM" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/vouchers/dashboard/?division=IM", expect.anything()));
  const board = await screen.findByRole("region", { name: "Vouchers" });
  expect(await within(board).findByRole("link", { name: /Waiting for my approval\s*1/ })).toBeInTheDocument();
  expect(within(board).getByRole("link", { name: /Waiting for approval/ })).toHaveAttribute(
    "href",
    "/vouchers/reports?tab=pending&division=IM",
  );
  expect(within(board).getByRole("link", { name: /Approved, not yet paid/ })).toHaveAttribute("href", "/payments?division=IM");
});

test("the lists open with the filters the dashboard gave them", async () => {
  const calls = mockApi({
    "GET /api/v1/vouchers/?status=returned&division=WS": { body: [] },
    "GET /api/v1/voucher-types/": { body: [] },
    "GET /api/v1/vouchers/reports/pending/?level=2": { body: { rows: [], summary: [] } },
  });
  const { unmount } = renderAt("/vouchers?status=returned&division=WS", <VouchersPage me={accountant} />, "/vouchers");
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/vouchers/?status=returned&division=WS", expect.anything()));
  expect(screen.getByRole("button", { name: "Division WS ✕" })).toBeInTheDocument();
  unmount();

  renderAt("/vouchers/reports?tab=pending&level=2", <VoucherReportsPage />, "/vouchers/reports");
  expect(await screen.findByRole("tab", { name: "Pending by approver and age" })).toHaveAttribute("aria-selected", "true");
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/vouchers/reports/pending/?level=2", expect.anything()));
});

test("a Cashier, who sees approved vouchers only, is not shown approval counts", async () => {
  const cashierView = { ...figures, can_approve: false, can_enter: false, sees_approvals: false, pending_count: 0 };
  mockApi(homeApi({ "GET /api/v1/vouchers/dashboard/": { body: cashierView } }));
  renderAt("/dashboard", <HomePage user={accountant} />);

  const board = await screen.findByRole("region", { name: "Vouchers" });
  await within(board).findByText("Approved, not yet paid");
  expect(within(board).queryByText("Waiting for approval")).not.toBeInTheDocument();
  expect(within(board).queryByRole("columnheader", { name: /Waiting for approval/ })).not.toBeInTheDocument();
});
