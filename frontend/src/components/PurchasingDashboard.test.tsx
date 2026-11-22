import { screen } from "@testing-library/react";

import { mockApi, renderAt } from "../test-utils";
import PurchasingDashboard from "./PurchasingDashboard";

const board = {
  waiting_for_me: 0,
  open_orders: 3,
  overdue: 3,
  qc_waiting: 1,
  grni: { count: 1, total: "60000.00" },
  held_invoices: 1,
  stock_value: "845150.00",
};

test("the Invoices held tile counts an invoice that is held (testing T44)", async () => {
  mockApi({ "GET /api/v1/purchasing-reports/dashboard/": { body: board } });
  renderAt("/", <PurchasingDashboard />);
  const tile = await screen.findByRole("link", { name: /Invoices held/ });
  expect(tile).toHaveTextContent("1");
  expect(tile).toHaveClass("attention");
  expect(screen.getByRole("link", { name: /Received, not invoiced/ })).toHaveTextContent("LKR 60,000.00");
});

test("someone who cannot see supplier invoices gets no Invoices held tile, not a 0", async () => {
  mockApi({ "GET /api/v1/purchasing-reports/dashboard/": { body: { ...board, held_invoices: null } } });
  renderAt("/", <PurchasingDashboard />);
  expect(await screen.findByRole("link", { name: /Received, not invoiced/ })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Invoices held/ })).not.toBeInTheDocument();
});
