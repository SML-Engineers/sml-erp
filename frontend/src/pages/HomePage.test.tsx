import { screen, within } from "@testing-library/react";

import { mockApi, renderAt, sampleUser } from "../test-utils";
import HomePage from "./HomePage";

test("welcomes the user and shows the system status", async () => {
  mockApi({
    "GET /api/v1/health/": { body: { status: "ok", database: "ok", version: "0.1.0" } },
  });
  renderAt("/dashboard", <HomePage user={sampleUser} />);

  expect(screen.getByText("Welcome, Mewantha")).toBeInTheDocument();
  expect(await screen.findByText("System status: OK")).toBeInTheDocument();
  expect(screen.getByText("Version 0.1.0")).toBeInTheDocument();
});

test("says when the database is not reachable", async () => {
  mockApi({
    "GET /api/v1/health/": {
      status: 503,
      body: { status: "degraded", database: "unavailable", version: "0.1.0" },
    },
  });
  renderAt("/dashboard", <HomePage user={sampleUser} />);

  expect(await screen.findByText("System status: the database is not reachable")).toBeInTheDocument();
});

const production = {
  today: "2026-11-11",
  waiting: { shift_reports: 2, corrections: 1, issue_more: 1, deviations: 0, boms: 0, routings: 1 },
  made_today: { good: "3960", rejected: "40", reject_pct: "1.00", run_h: "2.00", stopped_h: "0.25" },
  moulds_due: 0,
};

test("the Production Manager sees production, not the sales and purchasing summaries", async () => {
  // Owner, 11 Nov 2026.
  const calls = mockApi({
    "GET /api/v1/health/": { body: { status: "ok", database: "ok", version: "0.1.0" } },
    "GET /api/v1/production-reports/dashboard/": { body: production },
  });
  const manager = {
    ...sampleUser,
    access: {
      areas: { dashboard: ["view"], sales: ["view"], purchasing: ["view"], production_approvals: ["approve", "view"] },
      actions: [],
      divisions: "all",
    },
  } as typeof sampleUser;
  renderAt("/dashboard", <HomePage user={manager} />);
  const panel = await screen.findByRole("region", { name: "Production" });
  const reports = within(panel).getByRole("link", { name: /Shift reports to approve/ });
  expect(reports).toHaveTextContent("2");
  expect(reports).toHaveTextContent("1 correction asked for");
  expect(reports).toHaveAttribute("href", "/shift-report");
  expect(within(panel).getByRole("link", { name: /Requests to issue more/ })).toHaveAttribute("href", "/job-orders");
  expect(within(panel).getByRole("link", { name: /BOMs and routings to approve/ })).toHaveAttribute("href", "/routings");
  expect(within(panel).getByRole("link", { name: /Good pieces made today/ })).toHaveTextContent("3,960");
  expect(within(panel).getByRole("link", { name: /Good pieces made today/ })).toHaveTextContent("40 rejected (1.00%), 0.25 h downtime");
  expect(screen.queryByRole("region", { name: "Sales" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Purchasing and stores" })).not.toBeInTheDocument();
  expect(calls).not.toHaveBeenCalledWith(expect.stringContaining("/sales/dashboard/"), expect.anything());
});

test("viewing production reports alone does not bring the Production Manager's tiles", async () => {
  mockApi({
    "GET /api/v1/health/": { body: { status: "ok", database: "ok", version: "0.1.0" } },
  });
  const director = {
    ...sampleUser,
    access: { areas: { dashboard: ["view"], production_approvals: ["view"] }, actions: [], divisions: "all" },
  } as typeof sampleUser;
  renderAt("/dashboard", <HomePage user={director} />);
  await screen.findByText("System status: OK");
  expect(screen.queryByRole("region", { name: "Production" })).not.toBeInTheDocument();
});

test("the Production Planner also sees production, not the sales and purchasing figures", async () => {
  // Owner, 12 Nov 2026.
  mockApi({
    "GET /api/v1/health/": { body: { status: "ok", database: "ok", version: "0.1.0" } },
    "GET /api/v1/production-reports/dashboard/": { body: production },
  });
  const planner = {
    ...sampleUser,
    access: {
      areas: {
        dashboard: ["view"],
        sales: ["view"],
        purchasing: ["view"],
        stores: ["view"],
        production_planning: ["enter", "view"],
        production_approvals: ["view"],
      },
      actions: [],
      divisions: "all",
    },
  } as typeof sampleUser;
  renderAt("/dashboard", <HomePage user={planner} />);
  expect(await screen.findByRole("region", { name: "Production" })).toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Sales" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Purchasing and stores" })).not.toBeInTheDocument();
});

test("everyone sees what waits for their approval, with a link to each", async () => {
  // Owner, 12 Nov 2026.
  mockApi({
    "GET /api/v1/health/": { body: { status: "ok", database: "ok", version: "0.1.0" } },
    "GET /api/v1/approvals/waiting/": {
      body: [
        { document_type: "voucher", label: "Payment voucher", count: 2 },
        { document_type: "shift_report", label: "Work shift report", count: 1 },
      ],
    },
  });
  renderAt("/dashboard", <HomePage user={sampleUser} />);
  const panel = await screen.findByRole("region", { name: "Waiting for your approval" });
  expect(within(panel).getByRole("link", { name: /Payment voucher/ })).toHaveAttribute("href", "/vouchers/review");
  expect(within(panel).getByRole("link", { name: /Work shift report/ })).toHaveAttribute("href", "/shift-report");
  expect(within(panel).getByRole("link", { name: /Payment voucher/ })).toHaveTextContent("2");
});

test("nothing waiting shows no panel", async () => {
  mockApi({
    "GET /api/v1/health/": { body: { status: "ok", database: "ok", version: "0.1.0" } },
    "GET /api/v1/approvals/waiting/": { body: [] },
  });
  renderAt("/dashboard", <HomePage user={sampleUser} />);
  await screen.findByText("System status: OK");
  expect(screen.queryByRole("region", { name: "Waiting for your approval" })).not.toBeInTheDocument();
});
