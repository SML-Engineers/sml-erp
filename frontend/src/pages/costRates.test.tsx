import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CostRates } from "../api/costRates";
import { mockApi, renderAt } from "../test-utils";
import CostRatesPage from "./CostRatesPage";

const rates: CostRates = {
  sections: [
    {
      code: "M-LAT",
      name: "Manual lathes",
      division: "WS",
      labour: { id: 1, rate: "450.00", effective_from: "2026-11-01", source: "payroll" },
      labour_next: { id: 2, rate: "500.00", effective_from: "2026-12-01", source: "manual" },
      overhead: null,
      overhead_next: null,
      payroll: { per_hour: "462.50", basis: "division", payroll: "WS Oct 2026" },
    },
    {
      code: "M-MIL",
      name: "Manual milling",
      division: "WS",
      labour: null,
      labour_next: null,
      overhead: null,
      overhead_next: null,
      payroll: null,
    },
  ],
  machines: [{ code: "M-LAT-01", name: "Lathe 1", section: "M-LAT", overhead: null, overhead_next: null, in_force: "0.00" }],
  materials: [{ code: "PP-H", name: "PP homopolymer", per_kg: "520.50", basis: "material", set: null, set_next: null }],
  moulds: [
    {
      code: "MD-001",
      name: "Cap",
      rate: { id: 3, rate: "1.5000", effective_from: "2026-11-01", source: "manual" },
      mould_cost: "1500000.00",
      life_shots: 1000000,
      next: null,
    },
  ],
  history: [
    {
      id: 2,
      kind: "labour",
      kind_label: "Labour per hour",
      target: "M-LAT",
      effective_from: "2026-12-01",
      rate: "500.00",
      mould_cost: "",
      life_shots: null,
      source: "manual",
      reason: "New wages",
      created_by: "Acc",
      in_force: false,
    },
    {
      id: 1,
      kind: "labour",
      kind_label: "Labour per hour",
      target: "M-LAT",
      effective_from: "2026-11-01",
      rate: "450.00",
      mould_cost: "",
      life_shots: null,
      source: "payroll",
      reason: "Payroll WS Sep 2026",
      created_by: "Acc",
      in_force: true,
    },
  ],
  can_keep: true,
  today: "2026-11-08",
};

test("the Accountant sees the rates in force and accepts the payroll's labour rate", async () => {
  const calls = mockApi({
    "GET /api/v1/cost-rates/": { body: rates },
    "POST /api/v1/cost-rates/accept/": { body: rates },
  });
  renderAt("/cost-rates", <CostRatesPage />);
  const table = await screen.findByRole("table", { name: "Labour and overhead per section" });
  const lathe = within(table).getByText("M-LAT").closest("tr")!;
  expect(within(lathe).getByText("450.00 from 2026-11-01")).toBeInTheDocument();
  expect(within(lathe).getByText("(then 500.00 from 2026-12-01)")).toBeInTheDocument();
  expect(within(lathe).getByText(/462.50 an hour \(WS Oct 2026, division rate: fewer than 3 people\)/)).toBeInTheDocument();
  expect(within(table).getByText("Not set: labour not costed")).toBeInTheDocument();
  expect(within(screen.getByRole("table", { name: "Regrind credit per kg" })).getByText("100% of the material's cost")).toBeInTheDocument();
  expect(
    within(screen.getByRole("table", { name: "Mould amortisation (company moulds)" })).getByText("1.5000 from 2026-11-01"),
  ).toBeInTheDocument();
  fireEvent.click(within(lathe).getByRole("button", { name: "Accept the payroll rate for M-LAT" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/cost-rates/accept/",
      expect.objectContaining({ body: JSON.stringify({ sections: ["M-LAT"], effective_from: "" }) }),
    ),
  );
});

test("a mould's rate is entered from its cost and life, and a future rate removed", async () => {
  const calls = mockApi({
    "GET /api/v1/cost-rates/": { body: rates },
    "POST /api/v1/cost-rates/": { body: rates, status: 201 },
    "DELETE /api/v1/cost-rates/2/": { body: rates },
  });
  renderAt("/cost-rates", <CostRatesPage />);
  const form = await screen.findByRole("form", { name: "Enter a rate" });
  fireEvent.change(within(form).getByLabelText("Rate"), { target: { value: "mould" } });
  fireEvent.change(within(form).getByLabelText("Mould"), { target: { value: "MD-001" } });
  fireEvent.change(within(form).getByLabelText("Mould cost (LKR)"), { target: { value: "2000000" } });
  fireEvent.change(within(form).getByLabelText("Expected life (shots)"), { target: { value: "1000000" } });
  fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Bought 2025" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save the rate" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/cost-rates/",
      expect.objectContaining({
        body: JSON.stringify({
          kind: "mould",
          mould: "MD-001",
          effective_from: "",
          reason: "Bought 2025",
          mould_cost: "2000000",
          life_shots: "1000000",
        }),
      }),
    ),
  );
  const history = screen.getByRole("table", { name: "All rates" });
  expect(within(history).queryByRole("button", { name: "Remove the rate for M-LAT from 2026-11-01" })).not.toBeInTheDocument();
  fireEvent.click(within(history).getByRole("button", { name: "Remove the rate for M-LAT from 2026-12-01" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/cost-rates/2/", expect.objectContaining({ method: "DELETE" })));
});

test("an overhead rate is entered for one machine", async () => {
  const calls = mockApi({
    "GET /api/v1/cost-rates/": { body: rates },
    "POST /api/v1/cost-rates/": { body: rates, status: 201 },
  });
  renderAt("/cost-rates", <CostRatesPage />);
  const form = await screen.findByRole("form", { name: "Enter a rate" });
  fireEvent.change(within(form).getByLabelText("Rate"), { target: { value: "overhead" } });
  fireEvent.click(within(form).getByLabelText("For one machine"));
  fireEvent.change(within(form).getByLabelText("Machine"), { target: { value: "M-LAT-01" } });
  fireEvent.change(within(form).getByLabelText("LKR a machine hour"), { target: { value: "350" } });
  fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Budget" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save the rate" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/cost-rates/",
      expect.objectContaining({
        body: JSON.stringify({ kind: "overhead", machine: "M-LAT-01", effective_from: "", reason: "Budget", rate: "350" }),
      }),
    ),
  );
});

test("the Production Manager reads the rates without the payroll figures", async () => {
  mockApi({
    "GET /api/v1/cost-rates/": {
      body: { ...rates, can_keep: false, sections: rates.sections.map((s) => ({ ...s, payroll: null })) },
    },
  });
  renderAt("/cost-rates", <CostRatesPage />);
  const table = await screen.findByRole("table", { name: "Labour and overhead per section" });
  expect(within(table).queryByText("From the payroll")).not.toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "Enter a rate" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Remove/ })).not.toBeInTheDocument();
});
