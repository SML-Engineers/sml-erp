import { screen, within } from "@testing-library/react";

import type { CloseReport } from "../api/orderProfits";
import { renderAt } from "../test-utils";
import OrderClosePanel from "./OrderClosePanel";

const report: CloseReport = {
  basis: "quotation",
  quantity: "20",
  good: "18",
  rejected: "2",
  revenue: "7200.00",
  revenue_basis: "order",
  cost: "3080.00",
  margin: "4120.00",
  margin_pct: "133.77",
  estimate_cost: "7200.00",
  variance: "-4120.00",
  rows: [
    { key: "material", label: "Material", estimate: "5400.00", actual: "972.00", variance: "-4428.00" },
    { key: "machine", label: "Machine time", estimate: "1800.00", actual: "1800.00", variance: "0.00" },
    { key: "setup", label: "Setup and mould changes", estimate: "0.00", actual: "0.00", variance: "0.00" },
    { key: "rejects", label: "Rejects", estimate: "0.00", actual: "308.00", variance: "308.00" },
    { key: "outside", label: "Subcontract, direct expenses and packing", estimate: "0.00", actual: "0.00", variance: "0.00" },
  ],
  material_price: "-1728.00",
  material_usage: "-2700.00",
  actuals: { kg_per_piece: "0.5000", hours_per_1000: "100.00", setup_hours: "0.00", cycle_s: null },
  quoted: { kg_per_piece: "1.0000", setup_hours: "0.00", cycle_s: null },
  standard_cycle_s: null,
  automatic: true,
  closed_by: "Sales",
  closed_at: "2026-11-09T10:00:00Z",
};

test("a closed order's final report with its variances", () => {
  renderAt("/", <OrderClosePanel report={report} />);
  const panel = screen.getByRole("region", { name: "Final report" });
  expect(within(panel).getByText(/Closed by the last delivery \(Sales, 2026-11-09\) · 18 good and 2 rejected of 20/)).toBeInTheDocument();
  const table = within(panel).getByRole("table", { name: "Estimate against actual" });
  expect(within(table).getByRole("row", { name: /^Material 5,400/ })).toHaveTextContent("5,400.00972.00-4,428.00");
  expect(within(table).getByRole("row", { name: /^Rejects/ })).toHaveTextContent("308.00");
  expect(within(table).getByRole("row", { name: /material price/ })).toHaveTextContent("-1,728.00");
  expect(within(table).getByRole("row", { name: /^Total/ })).toHaveTextContent("7,200.003,080.00-4,120.00");
  expect(within(panel).getByText(/Actual 0.5000 kg a piece \(quoted 1.0000\)/)).toBeInTheDocument();
});
