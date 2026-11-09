import { fireEvent, screen, within } from "@testing-library/react";

import type { ProfitRow } from "../api/orderProfits";
import { mockApi, renderAt } from "../test-utils";
import OrderProfitsPage from "./OrderProfitsPage";

function day(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
const now = new Date();
const start = day(new Date(now.getFullYear(), now.getMonth(), 1));
const end = day(now);

const figures = {
  quantity: "20",
  good: "10",
  rejected: "0",
  complete_pct: "50.00",
  price: "400.00",
  value: "8000.00",
  earned: "4000.00",
  estimate_basis: "quotation" as const,
  estimate_unit: "300.00",
  estimate_cost: "6000.00",
  estimate_margin: "2000.00",
  cost: "3080.00",
  per_good: "308.00",
  forecast_cost: "6080.00",
  forecast_revenue: "8000.00",
  forecast_margin: "1920.00",
  margin_pct: "31.58",
  min_margin_pct: "15.00",
  overrun_pct: "2.67",
  overrun_limit: "10.00",
  reject_pct: null,
  reject_limit: "5.00",
};

const shafts: ProfitRow = {
  ...figures,
  flags: [],
  status: "green",
  kind: "job",
  id: 4,
  number: "JO26110001",
  link: "/job-orders?job=4",
  status_label: "Released",
  division: "WS",
  customer: "Unilever Sri Lanka",
  customer_id: 2,
  sales_order: "SO26110901",
  part: "SH-100",
  description: "Drive shaft",
  due_date: "2026-11-23",
  sections: ["M-LAT"],
};
const caps: ProfitRow = {
  ...shafts,
  kind: "production",
  id: 9,
  number: "PO26110003",
  link: "/production-orders?order=9",
  division: "IM",
  customer: "",
  customer_id: null,
  sales_order: "",
  part: "CAP-28",
  sections: ["IM-MLD"],
  value: null,
  earned: null,
  forecast_margin: null,
  margin_pct: null,
  reject_pct: "7.50",
  flags: ["overrun", "rejects"],
  status: "red",
};

test("the dashboard shows open orders worst first, filtered and by status", async () => {
  mockApi({
    "GET /api/v1/order-profits/?state=open": { body: { state: "open", counts: { red: 1, amber: 0, green: 1 }, orders: [caps, shafts] } },
    "GET /api/v1/order-profits/?state=open&division=WS": {
      body: { state: "open", counts: { red: 0, amber: 0, green: 1 }, orders: [shafts] },
    },
    [`GET /api/v1/order-profits/moulding/?start=${start}&end=${end}`]: {
      body: {
        start,
        end,
        rows: [
          {
            machine: "IMM-250",
            mould: "MD-001",
            orders: ["PO26110003"],
            good: "3960",
            rejected: 40,
            reject_pct: "1.00",
            standard_cycle_s: "12.00",
            actual_cycle_s: "10.80",
            material_per_piece: "0.6600",
            cost_per_1000: "1329.29",
            margin_per_1000: null,
          },
        ],
      },
    },
  });
  renderAt("/order-profits", <OrderProfitsPage />);
  const table = await screen.findByRole("table", { name: "Orders" });
  const [, first, second] = within(table).getAllByRole("row");
  expect(first).toHaveTextContent(/^Red.*PO26110003/);
  expect(first).toHaveTextContent("cost over estimate, rejects over limit");
  expect(first).toHaveTextContent("For stock");
  expect(within(second).getByRole("link", { name: "JO26110001" })).toHaveAttribute("href", "/job-orders?job=4");
  expect(second).toHaveTextContent("50.00%8,000.003,080.001,920.0031.58%");
  // Only the red ones.
  fireEvent.click(screen.getByRole("button", { name: "Red: 1" }));
  expect(within(table).queryByText("JO26110001")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Red: 1" }));
  fireEvent.change(screen.getByLabelText("Customer"), { target: { value: "Unilever Sri Lanka" } });
  expect(within(table).queryByText("PO26110003")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Division"), { target: { value: "WS" } });
  expect(await screen.findByRole("button", { name: "Red: 0" })).toBeInTheDocument();
  // The moulding view per machine and mould.
  const moulding = await screen.findByRole("table", { name: "Moulding by machine and mould" });
  expect(moulding).toHaveTextContent("IMM-250MD-001PO261100033,96040 (1.00%)10.80 / 12.000.66001,329.29For stock");
});

test("actuals of a part's closed orders, for quoting", async () => {
  mockApi({
    "GET /api/v1/order-profits/?state=open": { body: { state: "open", counts: { red: 0, amber: 0, green: 0 }, orders: [] } },
    [`GET /api/v1/order-profits/moulding/?start=${start}&end=${end}`]: { body: { start, end, rows: [] } },
    "GET /api/v1/order-profits/part/?item=SH-100": {
      body: {
        item: "SH-100",
        name: "Drive shaft",
        orders: [
          {
            number: "JO26110001",
            closed_at: "2026-11-09T10:00:00Z",
            good: "18",
            margin_pct: "133.77",
            kg_per_piece: "0.5000",
            hours_per_1000: "100.00",
            setup_hours: "0.00",
            cycle_s: null,
          },
        ],
        average: { kg_per_piece: "0.5000", hours_per_1000: "100.00", setup_hours: "0.00", cycle_s: null },
      },
    },
  });
  renderAt("/order-profits", <OrderProfitsPage />);
  const panel = await screen.findByRole("region", { name: "Actuals for quoting" });
  fireEvent.change(within(panel).getByLabelText("Part (item code)"), { target: { value: "sh-100" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Show" }));
  const table = await within(panel).findByRole("table", { name: "Closed orders of SH-100" });
  expect(within(table).getByRole("row", { name: /JO26110001/ })).toHaveTextContent("JO26110001180.5000100.000.00–133.77%");
  expect(within(table).getByRole("row", { name: /Average/ })).toHaveTextContent("Average0.5000100.000.00–");
});
