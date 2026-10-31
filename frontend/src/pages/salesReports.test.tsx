import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";

import type { RegisterReport, SalesDashboard as Board, WinLossReport } from "../api/salesReports";
import SalesDashboard from "../components/SalesDashboard";
import { mockApi, renderAt } from "../test-utils";
import SalesReportsPage from "./SalesReportsPage";

const register: RegisterReport = {
  rows: [
    {
      id: 12, label: "QL26103101 Rev 0", quote_date: "2026-10-31", valid_until: "2026-11-30", division: "IM", customer_id: 4,
      customer: "Unilever Sri Lanka", salesperson_id: 3, salesperson: "Nimal", status: "Lost", status_code: "lost",
      reason: "Price", currency: "LKR", total: "LKR 23,500.00", total_amount: "23500.00", total_lkr: "23500.00",
    },
  ],
  summary: [{ status_code: "lost", status: "Lost", count: 1, total_lkr: "23500.00" }],
  salespeople: [
    { id: 3, name: "Nimal" },
    { id: 5, name: "Kamani" },
  ],
};

test("the quotation register lists, filters and exports", async () => {
  const calls = mockApi({
    "GET /api/v1/sales/reports/register/": { body: register },
    "GET /api/v1/sales/reports/register/?salesperson=5": { body: { ...register, rows: [], summary: [] } },
  });
  renderAt("/sales/reports", <SalesReportsPage />);
  const table = await screen.findByRole("table", { name: "Quotation register" });
  expect(within(table).getByRole("link", { name: "QL26103101 Rev 0" })).toHaveAttribute("href", "/quotations/12");
  expect(within(table).getByText("Price")).toBeInTheDocument();
  expect(screen.getByRole("list", { name: "By status" })).toHaveTextContent("Lost: 1 · LKR 23,500.00");
  const exports = screen.getByRole("group", { name: "Download Quotation register" });
  expect(within(exports).getByRole("link", { name: "PDF" })).toHaveAttribute("href", "/api/v1/sales/reports/register/?export=pdf");

  fireEvent.change(screen.getByLabelText("Salesperson"), { target: { value: "5" } });
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/sales/reports/register/?salesperson=5", expect.anything()));
  expect(await screen.findByText("No quotations match.")).toBeInTheDocument();
});

test("won and lost shows the win rate and the reasons", async () => {
  const report: WinLossReport = {
    rows: [],
    summary: {
      total: { won: 1, won_lkr: "23500.00", lost: 2, lost_lkr: "86500.00", win_rate: "33.3", value_win_rate: "21.4" },
      by_reason: [{ reason_code: "price", reason: "Price", won: 1, won_lkr: "23500.00", lost: 1, lost_lkr: "76500.00", win_rate: "50.0" }],
      by_salesperson: [],
    },
  };
  mockApi({ "GET /api/v1/sales/reports/win-loss/?from=2026-10-01": { body: report } });
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-31T10:00:00"));
  renderAt("/sales/reports?tab=winLoss", <SalesReportsPage />, "/sales/reports");
  expect(await screen.findByText("1 won, 2 lost: win rate 33.3% by number, 21.4% by value.")).toBeInTheDocument();
  const reasons = screen.getByRole("table", { name: "By reason" });
  expect(within(reasons).getByText("76,500.00")).toBeInTheDocument();
  vi.useRealTimers();
});

test("the sales tiles open their reports", async () => {
  const board: Board = {
    division: "", divisions: [{ code: "IM", name: "Moulding" }, { code: "WS", name: "Workshop" }],
    can_approve: true, can_enter: false,
    waiting_for_me: { count: 2, quotations: 1, orders: 1, total: "23500.00" },
    awaiting_approval: 1, expiring: 2, live: { count: 3, total: "70500.00" },
    this_month: { from: "2026-10-01", to: "2026-10-31", won: 1, won_lkr: "10000.00", lost: 1, lost_lkr: "5000.00", win_rate: "50.0", value_win_rate: "66.7" },
    open_orders: { count: 1, total: "23500.00" }, deliveries: { overdue: 1, this_week: 0 }, advances: { count: 0, balance: "0.00" },
  };
  const calls = mockApi({
    "GET /api/v1/sales/dashboard/": { body: board },
    "GET /api/v1/sales/dashboard/?division=IM": { body: { ...board, division: "IM" } },
  });
  renderAt("/", <SalesDashboard />);
  const tiles = await screen.findByRole("region", { name: "Sales" });
  expect(within(tiles).getByRole("link", { name: /Quotations needing attention 3/ })).toHaveAttribute("href", "/sales/reports?tab=attention");
  expect(within(tiles).getByRole("link", { name: /Won this month LKR 10,000.00/ })).toHaveTextContent("win rate 50.0%");
  expect(within(tiles).getByRole("link", { name: /Open sales orders/ })).toHaveTextContent("1 deliveries overdue");
  expect(within(tiles).queryByText("Advances not yet set off")).not.toBeInTheDocument();
  fireEvent.click(within(tiles).getByRole("button", { name: "IM" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/sales/dashboard/?division=IM", expect.anything()));
  expect(await within(tiles).findByRole("link", { name: /Open sales orders/ })).toHaveAttribute("href", "/sales/reports?tab=orders&division=IM");
});
