import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { Mould, MouldList } from "../api/moulds";
import { mockApi, renderAt } from "../test-utils";
import MouldsPage from "./MouldsPage";

const mould: Mould = {
  id: 1,
  code: "MD-001",
  name: "Cap 28 mm",
  division: "IM",
  owner: "company",
  owner_label: "Company",
  customer: "",
  customer_name: "",
  asset: "",
  cycle_time_s: "12.50",
  shot_weight_g: "36.0",
  runner_weight_g: "4.0",
  tonnage_t: "120.0",
  width_mm: "400.0",
  height_mm: "450.0",
  thickness_mm: "380.0",
  pm_interval_shots: 50000,
  shot_count: 1200,
  pm_due_at: 50000,
  status: "active",
  status_label: "Active",
  notes: "",
  in_use: false,
  parts: [{ item: "CAP-28", name: "Bottle cap", cavities: 8 }],
  machines: ["IMM-250", "IMM-90"],
  warnings: ["IMM-90: Clamping force: the mould needs 120 t, IMM-90 has 90"],
};
const list: MouldList = {
  results: [mould],
  can_edit: true,
  statuses: [
    { value: "active", label: "Active" },
    { value: "retired", label: "Retired" },
  ],
  machines: [
    { code: "IMM-250", name: "Haitian 250 t" },
    { code: "IMM-90", name: "Haitian 90 t" },
  ],
};

test("moulds are listed with their parts and size warnings", async () => {
  mockApi({ "GET /api/v1/moulds/?q=&status=": { body: list } });
  renderAt("/moulds", <MouldsPage />);
  const row = (await screen.findByRole("button", { name: "MD-001" })).closest("tr")!;
  expect(within(row).getByText("CAP-28 × 8")).toBeInTheDocument();
  expect(within(row).getByText(/1 size warning/)).toHaveAttribute("title", mould.warnings[0]);
  expect(within(row).getByText("Maintenance at 50,000")).toBeInTheDocument();
});

test("a new mould is saved and its size warnings are shown", async () => {
  const calls = mockApi({
    "GET /api/v1/moulds/?q=&status=": { body: { ...list, results: [] } },
    "POST /api/v1/moulds/": { body: mould, status: 201 },
  });
  renderAt("/moulds", <MouldsPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Add a mould" }));
  const form = screen.getByRole("region", { name: "Add a mould" });
  fireEvent.change(within(form).getByLabelText("Code"), { target: { value: "MD-001" } });
  fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Cap 28 mm" } });
  fireEvent.change(within(form).getByLabelText(/Parts and cavities/), { target: { value: "CAP-28 x 8" } });
  fireEvent.change(within(form).getByLabelText("Standard cycle time (s)"), { target: { value: "12.5" } });
  fireEvent.click(within(form).getByRole("checkbox", { name: /IMM-90/ }));
  fireEvent.click(within(form).getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/moulds/", expect.objectContaining({ method: "POST" })));
  const sent = JSON.parse((calls.mock.calls.find((c) => c[0] === "/api/v1/moulds/")![1] as RequestInit).body as string);
  expect(sent).toMatchObject({ code: "MD-001", parts: "CAP-28 x 8", cycle_time_s: "12.5", machines: ["IMM-90"] });
  expect(await within(form).findByText(/Saved. Check that the mould fits/)).toBeInTheDocument();
  expect(within(form).getByText(mould.warnings[0])).toBeInTheDocument();
});

test("a customer's mould asks for the customer, not the asset", async () => {
  mockApi({ "GET /api/v1/moulds/?q=&status=": { body: list } });
  renderAt("/moulds", <MouldsPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Add a mould" }));
  const form = screen.getByRole("region", { name: "Add a mould" });
  expect(within(form).getByLabelText(/Fixed asset code/)).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Owner"), { target: { value: "customer" } });
  expect(within(form).getByLabelText("Customer code")).toBeInTheDocument();
  expect(within(form).queryByLabelText(/Fixed asset code/)).not.toBeInTheDocument();
});
