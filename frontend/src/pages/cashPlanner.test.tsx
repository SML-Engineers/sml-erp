import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { CashPlan } from "../api/cashPlanner";
import { mockApi, renderAt } from "../test-utils";
import CashPlannerPage from "./CashPlannerPage";

const days = Array.from({ length: 91 }, (_, i) => ({ day: `d${i}`, opening: "100000.00", in: "0.00", out: "0.00", closing: "100000.00" }));
const plan: CashPlan = {
  today: "2026-11-05", end: "2027-02-03", opening: "100000.00", closing: "-50000.00",
  lowest: { amount: "-50000.00", day: "2026-11-15" },
  weeks: [{ from: "2026-11-05", to: "2026-11-11", opening: "100000.00", in: "0.00", out: "150000.00", closing: "-50000.00", lowest: "-50000.00" }],
  days,
  flows: [{ day: "2026-11-08", amount: "-150000.00", kind: "what_if", label: "New CNC machine", link: "", item_id: 4 }],
  what_ifs: [{ id: 4, description: "New CNC machine", on_date: "2026-11-08", amount: "-150000.00", created_by: "Accountant" }],
  can_plan: true,
};

test("a shortfall is shown and a what-if can be switched off", async () => {
  const calls = mockApi({
    "GET /api/v1/cash-planner/": { body: plan },
    "GET /api/v1/cash-planner/?without=4": { body: { ...plan, closing: "100000.00", lowest: { amount: "100000.00", day: "2026-11-05" } } },
  });
  renderAt("/cash-planner", <CashPlannerPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("2026-11-15");
  fireEvent.click(screen.getByRole("button", { name: /2026-11-05/ }));
  expect(screen.getByText(/New CNC machine/, { selector: "td" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox"));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/cash-planner/?without=4", expect.anything()));
});
