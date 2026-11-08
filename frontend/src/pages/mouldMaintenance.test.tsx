import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { MaintenanceOverview } from "../api/mouldMaintenance";
import { mockApi, renderAt } from "../test-utils";
import MouldMaintenancePage from "./MouldMaintenancePage";

const data: MaintenanceOverview = {
  moulds: [
    {
      code: "MD-001",
      name: "Cap",
      owner: "company",
      status: "active",
      status_label: "Active",
      shot_count: 1200,
      since: 1200,
      interval: 1000,
      left: 0,
      state: "due",
    },
    {
      code: "MD-002",
      name: "Lid",
      owner: "customer",
      status: "active",
      status_label: "Active",
      shot_count: 920,
      since: 920,
      interval: 1000,
      left: 80,
      state: "approaching",
    },
  ],
  history: [
    {
      id: 1,
      mould: "MD-001",
      kind: "repair",
      kind_label: "Repair",
      done_on: "2026-11-01",
      shot_count: 900,
      work_done: "Ejector pin",
      cost: "4500.00",
      done_by: "ABC Moulds",
      by_workshop: false,
      created_by: "PM",
    },
  ],
  total_cost: "4500.00",
  can_record: true,
};

test("moulds due and approaching, and the history", async () => {
  mockApi({ "GET /api/v1/mould-maintenance/?mould=": { body: data } });
  renderAt("/mould-maintenance", <MouldMaintenancePage />);
  const table = await screen.findByRole("table", { name: "Moulds and their next maintenance" });
  expect(within(within(table).getByText("MD-001").closest("tr")!).getByText("Due now")).toBeInTheDocument();
  expect(within(table).getByText("Approaching: 80 shots left")).toBeInTheDocument();
  const history = screen.getByRole("table", { name: "Maintenance history" });
  expect(within(history).getByText("Ejector pin")).toBeInTheDocument();
  expect(screen.getByText("Total cost shown: LKR 4,500.00")).toBeInTheDocument();
});

test("preventive maintenance is recorded", async () => {
  const calls = mockApi({
    "GET /api/v1/mould-maintenance/?mould=": { body: data },
    "POST /api/v1/mould-maintenance/": { body: data, status: 201 },
  });
  renderAt("/mould-maintenance", <MouldMaintenancePage />);
  const form = await screen.findByRole("form", { name: "Record maintenance or a repair" });
  fireEvent.change(within(form).getByLabelText("Mould"), { target: { value: "MD-001" } });
  fireEvent.change(within(form).getByLabelText("Date"), { target: { value: "2026-11-08" } });
  fireEvent.change(within(form).getByLabelText("Cost (LKR)"), { target: { value: "12500" } });
  fireEvent.change(within(form).getByLabelText("Done by"), { target: { value: "Mould shop" } });
  fireEvent.click(within(form).getByLabelText("Done by our workshop"));
  fireEvent.change(within(form).getByLabelText("Mould afterwards"), { target: { value: "active" } });
  fireEvent.change(within(form).getByLabelText("Work done"), { target: { value: "Cleaned vents" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save the record" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/mould-maintenance/",
      expect.objectContaining({
        body: JSON.stringify({
          mould: "MD-001",
          kind: "planned",
          done_on: "2026-11-08",
          work_done: "Cleaned vents",
          cost: "12500",
          done_by: "Mould shop",
          by_workshop: true,
          status: "active",
        }),
      }),
    ),
  );
});

test("one mould's history; read only without the right to record", async () => {
  mockApi({
    "GET /api/v1/mould-maintenance/?mould=": { body: { ...data, can_record: false } },
    "GET /api/v1/mould-maintenance/?mould=MD-001": { body: { ...data, can_record: false } },
  });
  renderAt("/mould-maintenance", <MouldMaintenancePage />);
  fireEvent.click(await screen.findByRole("button", { name: "History of MD-001" }));
  expect(await screen.findByRole("table", { name: "Maintenance history of MD-001" })).toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "Record maintenance or a repair" })).not.toBeInTheDocument();
});
