import { screen, within } from "@testing-library/react";

import type { OrderProfit } from "../api/orderProfits";
import { renderAt } from "../test-utils";
import OrderProfitPanel from "./OrderProfitPanel";

const profit: OrderProfit = {
  quantity: "20",
  good: "10",
  rejected: "0",
  complete_pct: "50.00",
  price: "400.00",
  value: "8000.00",
  earned: "4000.00",
  estimate_basis: "quotation",
  estimate_unit: "300.00",
  estimate_cost: "6000.00",
  estimate_margin: "2000.00",
  cost: "3080.00",
  per_good: "308.00",
  forecast_cost: "6080.00",
  forecast_revenue: "8000.00",
  forecast_margin: "1920.00",
  margin_pct: "31.58",
  min_margin_pct: "40.00",
  overrun_pct: "2.67",
  overrun_limit: "10.00",
  reject_pct: null,
  reject_limit: "5.00",
  flags: ["margin"],
  status: "amber",
  snapshots: [
    { day: "2026-11-09", cost: "3080.00", forecast_margin: "1920.00", margin_pct: "31.58", complete_pct: "50.00", status: "amber" },
  ],
  alerts: [
    {
      kind: "margin",
      label: "Margin below the minimum",
      detail: "Forecast margin 1,920.00 (31.58%) is below the minimum of 40.00%.",
      at: "2026-11-09T10:00:00Z",
    },
  ],
};

test("an order's estimate, actual and forecast, its status and alerts", () => {
  renderAt("/", <OrderProfitPanel profit={profit} />);
  const panel = screen.getByRole("region", { name: "Profitability" });
  expect(within(panel).getByRole("heading", { name: "Profitability Amber" })).toBeInTheDocument();
  const table = within(panel).getByRole("table", { name: "Estimate, actual and forecast" });
  expect(within(table).getByRole("row", { name: /Revenue/ })).toHaveTextContent("8,000.004,000.008,000.00");
  expect(within(table).getByRole("row", { name: /Cost/ })).toHaveTextContent("6,000.003,080.006,080.00");
  expect(within(table).getByRole("row", { name: /Margin/ })).toHaveTextContent("2,000.001,920.00 (31.58%)");
  expect(within(panel).getByText(/50.00% complete \(10 of 20 good\) · estimate 300.00 a piece from the quotation/)).toBeInTheDocument();
  expect(within(panel).getByRole("list", { name: "Alerts sent" })).toHaveTextContent("Margin below the minimum:");
  expect(within(panel).getByText("Forecast margin day by day (1 days)")).toBeInTheDocument();
});
