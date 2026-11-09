import { fireEvent, screen, within } from "@testing-library/react";

import type { WipReport } from "../api/wipReport";
import { mockApi, renderAt } from "../test-utils";
import WipReportPage from "./WipReportPage";

function lastMonth(): string {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

const report: WipReport = {
  month: lastMonth(),
  month_end: "2026-10-31",
  divisions: [
    {
      division: "WS",
      jobs: [{ id: 4, number: "JO26100004", description: "Shaft, EN8", status: "In progress", wip: "3080.00" }],
      orders: "3080.00",
      ledger: "3100.00",
      difference: "20.00",
    },
  ],
  reconciled: false,
  unabsorbed: [{ division: "IM", machine: "M-INJ-02", reason: "Breakdown", hours: "2.50", amount: "3750.00" }],
  absorbed: [{ division: "WS", element: "Labour", amount: "1200.00" }],
};

test("the accountant sees open jobs against the Work in progress account at month end", async () => {
  const calls = mockApi({
    [`GET /api/v1/wip-report/?month=${lastMonth()}`]: { body: report },
    "GET /api/v1/wip-report/?month=2026-09": {
      body: { ...report, month: "2026-09", divisions: [], reconciled: true, unabsorbed: [], absorbed: [] },
    },
  });
  renderAt("/wip-report", <WipReportPage />);
  expect(await screen.findByText(/does not agree with the open jobs/)).toBeInTheDocument();
  const ws = screen.getByRole("table", { name: "Open jobs, division WS" });
  expect(within(ws).getByRole("link", { name: "JO26100004" })).toHaveAttribute("href", "/job-orders?job=4");
  expect(within(ws).getByRole("row", { name: /Difference/ })).toHaveTextContent("20.00");
  expect(screen.getByRole("table", { name: "Machine time charged to no order" })).toHaveTextContent("M-INJ-02Breakdown2.53,750.00");
  expect(screen.getByRole("table", { name: "Production costs charged to orders" })).toHaveTextContent("WSLabour1,200.00");
  fireEvent.change(screen.getByLabelText("Month"), { target: { value: "2026-09" } });
  expect(await screen.findByText("No work in progress.")).toBeInTheDocument();
  expect(screen.getByText(/agrees with the open jobs/)).toBeInTheDocument();
  expect(calls).toHaveBeenCalledWith("/api/v1/wip-report/?month=2026-09", expect.anything());
});
