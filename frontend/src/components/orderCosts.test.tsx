import { fireEvent, screen, within } from "@testing-library/react";
import { vi } from "vitest";

import type { OrderCosts } from "../api/orderCosts";
import { renderAt } from "../test-utils";
import OrderCostsPanel from "./OrderCostsPanel";

const costs: OrderCosts = {
  elements: [
    { element: "material", label: "Material", amount: "324.00" },
    { element: "labour", label: "Labour", amount: "1200.00" },
    { element: "direct", label: "Direct expenses", amount: "25000.00" },
  ],
  total: "26524.00",
  good: "18",
  rejected: "2",
  per_good: "1473.56",
  on_rejects: "2652.40",
  not_costed: ["M-BSW"],
  out_of_date: true,
  entries: [
    {
      id: 1,
      day: "2026-11-09",
      element: "labour",
      description: "JO26110001 op 10 on M-LAT-01, 2026-11-09",
      quantity: "2",
      unit: "h",
      rate: "600",
      amount: "1200.00",
      adjusts: false,
    },
  ],
  can_refresh: true,
  ledger: { posted: true, note: "wip", wip: "26524.00" },
};

test("an order's costs by element, rejects apart, and each entry's source", () => {
  const refresh = vi.fn();
  renderAt("/", <OrderCostsPanel costs={costs} onRefresh={refresh} />);
  const panel = screen.getByRole("region", { name: "Costs so far" });
  expect(within(panel).getByRole("table", { name: "Costs by element" })).toHaveTextContent("Total cost so far26,524.00");
  expect(
    within(panel).getByText(/18 good pieces, 2 rejected · 1,473.56 a good piece · 2,652.40 spent on the rejected pieces/),
  ).toBeInTheDocument();
  expect(within(panel).getByText(/Labour is not costed yet for M-BSW/)).toBeInTheDocument();
  expect(within(panel).getByText("In the accounts as work in progress: 26,524.00.")).toBeInTheDocument();
  fireEvent.click(within(panel).getByRole("button", { name: "Show the 1 entry" }));
  expect(within(panel).getByRole("table", { name: "Cost entries" })).toHaveTextContent("JO26110001 op 10 on M-LAT-01");
  fireEvent.click(within(panel).getByRole("button", { name: "Bring the costs up to date" }));
  expect(refresh).toHaveBeenCalled();
});

test("a completed job says what moved into finished goods", () => {
  const done: OrderCosts = {
    ...costs,
    ledger: { posted: true, note: "completed", wip: "0.00", finished: "18", finished_value: "26524.00" },
  };
  renderAt("/", <OrderCostsPanel costs={done} />);
  expect(screen.getByText(/Completed: 18 finished, 26,524.00 moved from work in progress into finished goods/)).toBeInTheDocument();
});
