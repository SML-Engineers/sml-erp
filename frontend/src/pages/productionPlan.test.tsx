import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { PlanBoard } from "../api/productionPlan";
import { mockApi, renderAt } from "../test-utils";
import ProductionPlanPage from "./ProductionPlanPage";

const d = new Date();
const TODAY = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const URL = `/api/v1/production-plan/?start=${TODAY}&days=3`;

const entry = {
  id: 5,
  day: TODAY,
  shift: "G",
  machine: "IMM-250",
  section: "IM-MLD",
  order: 7,
  order_number: "MO26110001",
  item: "CAP-28",
  item_name: "Cap 28 mm",
  mould: "MD-001",
  minutes: 480,
  quantity: "19200",
  notes: "",
  past: false,
  warnings: ["No crew is rostered on General in IM-MLD."],
};
const board: PlanBoard = {
  first: TODAY,
  days: [TODAY],
  shifts: [
    { code: "G", name: "General", minutes: 480 },
    { code: "N", name: "Night", minutes: 660 },
  ],
  machines: [
    { code: "IMM-250", name: "Haitian 250 t", section: "IM-MLD", status: "active" },
    { code: "IMM-90", name: "Haitian 90 t", section: "IM-MLD", status: "maintenance" },
  ],
  entries: [entry],
  orders: [
    {
      id: 7,
      number: "MO26110001",
      item: "CAP-28",
      item_name: "Cap 28 mm",
      mould: "MD-001",
      quantity: "10000",
      planned: "19200",
      first_due: TODAY,
    },
  ],
  can_plan: true,
};

test("the plan shows each run with its quantity and warnings", async () => {
  mockApi({ [`GET ${URL}`]: { body: board } });
  renderAt("/production-plan", <ProductionPlanPage />);
  const day = await screen.findByRole("table", { name: `Plan for ${TODAY}` });
  const run = within(day).getByLabelText("MO26110001 on IMM-250, General");
  expect(within(run).getByText(/19,200 pcs · 480 min/)).toBeInTheDocument();
  expect(within(run).getByText("No crew is rostered on General in IM-MLD.")).toBeInTheDocument();
  expect(within(day).getByText("(under maintenance)")).toBeInTheDocument();
  const orders = screen.getByRole("table", { name: "Released orders" });
  expect(within(orders).getByText("19,200")).toBeInTheDocument();
});

test("the planner adds an order to a shift and moves a run", async () => {
  const calls = mockApi({
    [`GET ${URL}`]: { body: board },
    "POST /api/v1/production-plan/": { body: entry, status: 201 },
    "PATCH /api/v1/production-plan/5/": { body: entry },
  });
  renderAt("/production-plan", <ProductionPlanPage />);
  const form = await screen.findByRole("form", { name: "Plan an order" });
  fireEvent.change(within(form).getByLabelText("Production order"), { target: { value: "7" } });
  fireEvent.change(within(form).getByLabelText("Shift"), { target: { value: "N" } });
  fireEvent.change(within(form).getByLabelText("Machine"), { target: { value: "IMM-90" } });
  fireEvent.change(within(form).getByLabelText("Planned minutes"), { target: { value: "120" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add to the plan" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/production-plan/",
      expect.objectContaining({ body: JSON.stringify({ day: TODAY, shift: "N", machine: "IMM-90", order: 7, minutes: "120", notes: "" }) }),
    ),
  );
  const run = screen.getByLabelText("MO26110001 on IMM-250, General");
  fireEvent.click(within(run).getByRole("button", { name: "Move" }));
  const move = await screen.findByRole("form", { name: "Move MO26110001" });
  fireEvent.change(within(move).getByLabelText("Machine"), { target: { value: "IMM-90" } });
  fireEvent.click(within(move).getByRole("button", { name: "Save the move" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/production-plan/5/",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ day: TODAY, shift: "G", machine: "IMM-90", minutes: "480" }) }),
    ),
  );
});

test("a day's plan is copied, and a supervisor only reads", async () => {
  const calls = mockApi({
    [`GET ${URL}`]: { body: board },
    "POST /api/v1/production-plan/copy/": { body: { copied: 1 } },
  });
  const { unmount } = renderAt("/production-plan", <ProductionPlanPage />);
  const panel = await screen.findByRole("region", { name: "Copy a day's plan" });
  fireEvent.change(within(panel).getByLabelText("Copy the plan of"), { target: { value: "2026-11-09" } });
  fireEvent.change(within(panel).getByLabelText("To"), { target: { value: "2026-11-10" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Copy" }));
  expect(await within(panel).findByText("1 run copied.")).toBeInTheDocument();
  expect(calls).toHaveBeenCalledWith(
    "/api/v1/production-plan/copy/",
    expect.objectContaining({ body: JSON.stringify({ source: "2026-11-09", target: "2026-11-10" }) }),
  );
  unmount();
  mockApi({ [`GET ${URL}`]: { body: { ...board, can_plan: false } } });
  renderAt("/production-plan", <ProductionPlanPage />);
  const day = await screen.findByRole("table", { name: `Plan for ${TODAY}` });
  expect(within(day).queryByRole("button", { name: "Move" })).not.toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "Plan an order" })).not.toBeInTheDocument();
});
