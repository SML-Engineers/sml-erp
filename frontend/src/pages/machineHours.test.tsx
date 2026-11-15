import { screen, within } from "@testing-library/react";

import type { MachineHours } from "../api/machineJobs";
import { factoryToday } from "../lib/time";
import { mockApi, renderAt } from "../test-utils";
import MachineHoursPage from "./MachineHoursPage";

const today = factoryToday();
const url = `/api/v1/machine-jobs/hours/?start=${today.slice(0, 8)}01&end=${today}&by=day`;

const hours: MachineHours = {
  start: `${today.slice(0, 8)}01`,
  end: today,
  by: "day",
  periods: [today],
  show_cost: true,
  machines: [
    {
      machine: "M-LAT-01",
      name: "Lathe 1",
      section: "M-LAT",
      hours: "2.00",
      downtime_hours: "0.25",
      utilisation: "20.0",
      periods: [{ period: today, hours: "2.00", downtime_hours: "0.25", utilisation: "20.0" }],
      cost_vs_estimate: { actual: "2400.00", estimate: "1800.00", over: true },
    },
  ],
  jobs: [
    {
      id: 1,
      machine: "M-LAT-01",
      kind: "job",
      job: "JO26110001",
      job_id: 7,
      operation: 20,
      operation_name: "Turn",
      order: null,
      order_id: null,
      started_at: `${today}T08:00:00+05:30`,
      ended_at: `${today}T10:00:00+05:30`,
      hours: "2.00",
      estimate_hours: "1.50",
      over: true,
      over_pct: "33.3",
      rate: "1200.00",
      cost: "2400.00",
      estimate_cost: "1800.00",
    },
  ],
};

test("machine hours show utilisation, estimate against actual and the cost", async () => {
  mockApi({ [`GET ${url}`]: { body: hours } });
  renderAt("/machine-hours", <MachineHoursPage />);
  const machines = await screen.findByRole("region", { name: "Hours per machine" });
  const row = within(machines).getAllByRole("row")[1];
  expect(row).toHaveTextContent("M-LAT-01");
  expect(row).toHaveTextContent("20.0%");
  expect(row).toHaveTextContent("2,400.00 / 1,800.00");
  const jobs = screen.getByRole("region", { name: "Jobs and orders" });
  expect(within(jobs).getByRole("link", { name: "JO26110001/20" })).toHaveAttribute("href", "/job-orders?job=7");
  expect(within(jobs).getByText("+33.3%")).toBeInTheDocument();
  expect(within(jobs).getByRole("link", { name: "Order profitability" })).toBeInTheDocument();
});

test("without cost access no cost columns are shown", async () => {
  mockApi({
    [`GET ${url}`]: {
      body: {
        ...hours,
        show_cost: false,
        machines: hours.machines.map(({ cost_vs_estimate: _, ...m }) => m),
        jobs: hours.jobs.map(({ cost: _c, estimate_cost: _e, rate: _r, ...j }) => j),
      },
    },
  });
  renderAt("/machine-hours", <MachineHoursPage />);
  await screen.findByRole("region", { name: "Hours per machine" });
  expect(screen.queryByText("Machine cost (LKR)")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Order profitability" })).not.toBeInTheDocument();
});
