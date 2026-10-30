import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { DivisionRate, Material } from "../api/costing";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import CostingRatesPage from "./CostingRatesPage";

const accountant: CurrentUser = {
  ...sampleUser,
  access: { areas: { accounting: ["enter", "manage", "view"], sales: ["view"] }, actions: [], divisions: "all" },
};

const executive: CurrentUser = {
  ...sampleUser,
  access: { areas: { sales: ["enter", "view"] }, actions: [], divisions: ["WS"] },
};

const en8: Material = {
  id: 3, code: "EN8-BAR", name: "EN8 steel bar", kind: "metal", form: "round_bar", grade: "080M40",
  density: "7.850", notes: "", is_active: true, current_rate: "400.00", in_use: false,
};

const ws: DivisionRate = {
  id: 1, division: "WS", effective_from: "2026-10-01", overhead_pct: "20.00", margin_pct: "25.00",
  setup_rate: "1500.00", reason: "", created_by: "accountant@sml.lk", created_at: "", in_force: true, current: true,
};

const api = (extra: Parameters<typeof mockApi>[0] = {}) => ({
  "GET /api/v1/costing/division-rates/": { body: [ws] },
  "GET /api/v1/costing/materials/": { body: [en8] },
  "GET /api/v1/costing/materials/3/rates/": {
    body: [{ id: 8, effective_from: "2026-10-01", rate: "400.00", reason: "", created_by: null, created_at: "", in_force: true }],
  },
  "GET /api/v1/divisions/": { body: [{ id: 1, code: "WS", name: "Workshop" }, { id: 2, code: "IM", name: "Moulding" }] },
  ...extra,
});

test("the rates in force are shown to sales staff, who cannot change them", async () => {
  mockApi(api());
  renderAt("/costing-rates", <CostingRatesPage me={executive} />);
  const divisions = await screen.findByRole("table", { name: "Division rates" });
  expect(within(divisions).getByText("In force")).toBeInTheDocument();
  expect(within(divisions).getByText("20.00%")).toBeInTheDocument();
  const materials = await screen.findByRole("table", { name: "Materials" });
  expect(within(materials).getByText("400.00")).toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "New division rates" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Add material" })).not.toBeInTheDocument();
});

test("the Accountant adds division rates from a date", async () => {
  const calls = mockApi(api({ "POST /api/v1/costing/division-rates/": { status: 201, body: { ...ws, id: 2, division: "IM" } } }));
  renderAt("/costing-rates", <CostingRatesPage me={accountant} />);
  const form = await screen.findByRole("form", { name: "New division rates" });
  await within(form).findByRole("option", { name: "IM Moulding" });
  fireEvent.change(within(form).getByLabelText("Division"), { target: { value: "IM" } });
  fireEvent.change(within(form).getByLabelText("Overhead %"), { target: { value: "18" } });
  fireEvent.change(within(form).getByLabelText("Default margin %"), { target: { value: "22.5" } });
  fireEvent.change(within(form).getByLabelText("Setup rate per hour (LKR)"), { target: { value: "1200" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/costing/division-rates/", expect.objectContaining({ method: "POST" })),
  );
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/costing/division-rates/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({ division: "IM", overhead_pct: "18", margin_pct: "22.5", setup_rate: "1200" });
});

test("the Accountant adds a material's price from a date", async () => {
  const calls = mockApi(
    api({
      "POST /api/v1/costing/materials/3/rates/": {
        status: 201,
        body: { id: 9, effective_from: "2026-11-01", rate: "425.50", reason: "", created_by: null, created_at: "", in_force: false },
      },
    }),
  );
  renderAt("/costing-rates", <CostingRatesPage me={accountant} />);
  fireEvent.click(await screen.findByRole("button", { name: "EN8-BAR" }));
  const prices = await screen.findByRole("group", { name: "Prices of EN8-BAR" });
  const add = within(prices).getByRole("form", { name: "Add price" });
  fireEvent.change(within(add).getByLabelText("From"), { target: { value: "2026-11-01" } });
  fireEvent.change(within(add).getByLabelText("Price per kg (LKR)"), { target: { value: "425.50" } });
  fireEvent.click(within(add).getByRole("button", { name: "Add price" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/costing/materials/3/rates/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ effective_from: "2026-11-01", rate: "425.50", reason: "" }) }),
    ),
  );
});
