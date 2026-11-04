import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { FinancialDashboard as Data } from "../api/financialReports";
import { mockApi, renderAt } from "../test-utils";
import FinancialDashboard from "./FinancialDashboard";

const company: Data = {
  today: "2026-11-04", division: null, company: true,
  divisions: [{ code: "WS", name: "Workshop" }, { code: "IM", name: "Injection moulding" }],
  this_month: { from: "2026-11-01", to: "2026-11-04", income: "1000.00", costs: "700.00", profit: "300.00" },
  year_to_date: { from: "2026-04-01", to: "2026-11-04", label: "2026-27", income: "9000.00", costs: "6000.00", profit: "3000.00", budget_profit: "2500.00" },
  cash: { balance: "78600.00", accounts: null },
  receivables: { total: "5000.00", overdue: "1200.00", count: 3 },
  payables: { total: "4000.00", overdue: "0.00", count: 2 },
};

test("the finance tiles open their reports and switch to a division", async () => {
  const calls = mockApi({
    "GET /api/v1/reports/dashboard/": { body: company },
    "GET /api/v1/reports/dashboard/?division=WS": { body: { ...company, division: "WS", cash: { balance: "0.00", accounts: 0 } } },
  });
  renderAt("/", <FinancialDashboard />, "/");
  const month = await screen.findByRole("link", { name: /Profit this month/ });
  expect(month).toHaveAttribute("href", "/reports/financial?tab=pl&from=2026-11-01&to=2026-11-04");
  expect(screen.getByRole("link", { name: /Customers owe us/ })).toHaveTextContent("Overdue 1,200.00");
  expect(screen.getByRole("link", { name: /Profit 2026-27 so far/ })).toHaveTextContent("Budget so far: 2,500.00");
  fireEvent.click(screen.getByRole("button", { name: "WS" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/reports/dashboard/?division=WS", expect.anything()));
  await waitFor(() =>
    expect(screen.getByRole("link", { name: /Profit this month/ })).toHaveAttribute(
      "href",
      "/reports/financial?tab=pl&from=2026-11-01&to=2026-11-04&division=WS",
    ),
  );
});
