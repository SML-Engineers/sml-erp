import { screen, within } from "@testing-library/react";

import type { MachinesToday } from "../api/machineJobs";
import { mockApi, renderAt } from "../test-utils";
import MachinesPanel from "./MachinesPanel";

const today: MachinesToday = {
  now: "2026-11-15T10:00:00+05:30",
  counts: { running: 1, idle: 1, maintenance: 1 },
  running: [
    {
      code: "M-LAT-01",
      name: "Lathe 1",
      section: "M-LAT",
      section_type: "machining",
      status: "running",
      jobs: [
        {
          id: 2,
          machine: "M-LAT-01",
          section: "M-LAT",
          kind: "job",
          job: "JO26110001",
          operation: 20,
          operation_name: "Turn",
          order: null,
          item: null,
          mould: null,
          operator: "Sunil Perera",
          drawing_no: "",
          description: "Turn",
          notes: "",
          started_at: new Date(Date.now() - 30 * 60_000).toISOString(),
          started_by: "Tharindu",
          ended_at: null,
          ended_by: null,
          minutes: 30,
          hours: "0.50",
          completed: null,
          rejected: null,
          start_counter: null,
          end_counter: null,
          second_allowed_by: null,
          second_reason: "",
        },
      ],
    },
  ],
  idle: ["M-LAT-02"],
  maintenance: ["IMM-250"],
  finished: [],
  hours: [
    { machine: "M-LAT-01", name: "Lathe 1", minutes: 120, pct: "20.0" },
    { machine: "M-LAT-02", name: "Lathe 2", minutes: 0, pct: "0.0" },
  ],
};

test("the dashboard shows what every machine is doing and the hours today", async () => {
  mockApi({ "GET /api/v1/machine-jobs/today/": { body: today } });
  renderAt("/", <MachinesPanel />);
  const panel = await screen.findByRole("region", { name: "Machines now" });
  expect(within(panel).getAllByText("M-LAT-02").length).toBeGreaterThan(0);
  expect(within(panel).getByText("IMM-250")).toBeInTheDocument();
  const running = within(panel).getByRole("table", { name: "Running now" });
  const row = within(running).getAllByRole("row")[1];
  expect(row).toHaveTextContent("JO26110001/20 Turn");
  expect(row).toHaveTextContent("30 min");
  expect(row).toHaveTextContent("Sunil Perera");
  expect(row).toHaveTextContent("Tharindu");
  const hours = within(panel).getByRole("table", { name: "Hours each machine ran today" });
  expect(within(hours).getAllByRole("row")[1]).toHaveTextContent("2 h 00 min");
  expect(within(hours).getAllByRole("row")[1]).toHaveTextContent("20.0%");
});
