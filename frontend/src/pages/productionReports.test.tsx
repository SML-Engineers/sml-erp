import { fireEvent, screen, within } from "@testing-library/react";

import { mockApi, renderAt } from "../test-utils";
import ProductionReportsPage from "./ProductionReportsPage";

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
const now = new Date();
const start = iso(new Date(now.getFullYear(), now.getMonth(), 1));
const end = iso(now);
const range = `start=${start}&end=${end}`;

test("daily production, rejects, downtime Pareto, jobs and moulds", async () => {
  mockApi({
    "GET /api/v1/production-reports/sections/": { body: { sections: [{ code: "IM-MLD", name: "Moulding" }] } },
    [`GET /api/v1/production-reports/daily/?${range}`]: {
      body: {
        rows: [
          {
            day: end,
            section: "IM-MLD",
            machine: "IMM-250",
            shift: "G",
            good: "3960",
            rejected: "40",
            reject_pct: "1.0",
            run_h: "2.00",
            stopped_h: "6.00",
          },
        ],
        total: { good: "3960", rejected: "40", reject_pct: "1.0", run_h: "2.00", stopped_h: "6.00" },
      },
    },
    [`GET /api/v1/production-reports/rejects/?${range}&by=reason`]: {
      body: {
        by: "reason",
        rows: [{ key: "FLASH", name: "Flash", rejected: "40", made: null, reject_pct: null, share_pct: "100.0" }],
        total_rejected: "40",
      },
    },
    [`GET /api/v1/production-reports/rejects/?${range}&by=mould`]: {
      body: {
        by: "mould",
        rows: [{ key: "MD-001", name: "Cap mould", rejected: "40", made: "4000", reject_pct: "1.0", share_pct: "100.0" }],
        total_rejected: "40",
      },
    },
    [`GET /api/v1/production-reports/downtime/?${range}`]: {
      body: {
        reasons: [
          {
            key: "BREAKDOWN",
            name: "Machine breakdown",
            planned: false,
            stops: 3,
            hours: "6.00",
            share_pct: "75.0",
            cumulative_pct: "75.0",
          },
          { key: "SETUP", name: "Setting up", planned: false, stops: 1, hours: "2.00", share_pct: "25.0", cumulative_pct: "100.0" },
        ],
        machines: [{ key: "IMM-250", hours: "8.00", share_pct: "100.0", cumulative_pct: "100.0" }],
        total_h: "8.00",
      },
    },
    [`GET /api/v1/production-reports/jobs/?${range}`]: {
      body: {
        rows: [
          {
            id: 4,
            number: "JO26110001",
            part: "SH-100",
            description: "",
            status: "Completed",
            quantity: "20",
            due_date: end,
            completed_on: end,
            on_time: true,
            days_late: 0,
            estimated_h: "2.17",
            actual_h: "2.00",
            time_variance_pct: "-7.7",
            estimated_cost: null,
            actual_cost: "2000.00",
          },
        ],
        completed: 1,
        on_time: 1,
        on_time_pct: "100.0",
        late_open: 2,
      },
    },
    "GET /api/v1/production-reports/moulds/": {
      body: { rows: [{ mould: "MD-001", name: "Cap mould", state: "due", shots_since: 500000, interval: 500000, used_pct: "100.0" }] },
    },
  });
  renderAt("/production-reports", <ProductionReportsPage />);
  const daily = await screen.findByRole("table", { name: "Daily production" });
  expect(within(daily).getByRole("row", { name: /IMM-250/ })).toHaveTextContent("IM-MLDIMM-250G3,960401.0%2.006.00");
  fireEvent.click(screen.getByRole("tab", { name: "Rejects" }));
  expect(await screen.findByRole("table", { name: "Rejects by Reason" })).toHaveTextContent("FLASHFlash40100.0%");
  fireEvent.change(screen.getByLabelText("Group by"), { target: { value: "mould" } });
  expect(await screen.findByRole("table", { name: "Rejects by Mould" })).toHaveTextContent("MD-001Cap mould404,0001.0%100.0%");
  fireEvent.click(screen.getByRole("tab", { name: "Downtime" }));
  const pareto = await screen.findByRole("table", { name: "Downtime by reason" });
  expect(within(pareto).getAllByRole("row")[1]).toHaveTextContent("BREAKDOWNMachine breakdown · 3 stops6.0075.0% 75.0%");
  fireEvent.click(screen.getByRole("tab", { name: "Jobs: time and delivery" }));
  expect(await screen.findByText("On time: 100.0% (1 of 1 completed jobs)")).toBeInTheDocument();
  expect(screen.getByText(/2 open jobs past their due date/)).toBeInTheDocument();
  expect(screen.getByRole("table", { name: "Jobs: time and delivery" })).toHaveTextContent("2.172.00-7.7%–2,000.00");
  fireEvent.click(screen.getByRole("tab", { name: "Moulds due for maintenance" }));
  expect(await screen.findByRole("table", { name: "Moulds due for maintenance" })).toHaveTextContent(
    "MD-001Cap mouldDue500,000500,000100.0%",
  );
});
