import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { PayrollList, PayrollRun, TaxTables } from "../api/payroll";
import { mockApi, renderAt } from "../test-utils";
import PayrollPage from "./PayrollPage";
import TaxTablesPage from "./TaxTablesPage";

const totals = {
  gross: "73325.00", epf_employee: "5400.00", epf_employer: "8100.00", etf: "2025.00", apit: "0.00",
  deductions: "250.00", net: "67675.00", employees: 1,
};

const run: PayrollRun = {
  id: 4, division: "WS", month: "2026-10", period: { month: "2026-10", start: "2026-09-21", end: "2026-10-20" },
  status: "draft", status_label: "Draft", created_by: "HR Officer", worked_out_at: "2026-11-06T09:00:00Z",
  approved_at: null, totals, statutory: { epf_employee: "8.00", epf_employer: "12.00", etf: "3.00" },
  returned: false, history: [], can_work_out: true, can_submit: true, can_approve: false, sees_people: true,
  lines: [
    {
      employee: { id: 7, number: "E001", name: "Kamal Perera", category: "shop_office" },
      days_employed: 30, days_in_period: 30, day_rate: "2200.00", hourly_rate: "275.00", gross: "73325.00",
      epf_earnings: "67500.00", apit_earnings: "73325.00", epf_employee: "5400.00", epf_employer: "8100.00",
      etf: "2025.00", apit: "0.00", deductions: "250.00", net: "67675.00",
      items: [
        { code: "BASIC", name: "Basic salary", kind: "earning", amount: "60000.00", basis: "Monthly amount since January 2024" },
        { code: "OT_WORKING", name: "Overtime, working days", kind: "earning", amount: "825.00", basis: "2:00 h x 275.00 x 1.50" },
        { code: "EPF_EE", name: "EPF (employee)", kind: "deduction", amount: "5400.00", basis: "8.00% of 67,500.00" },
      ],
    },
  ],
  entries: [],
  components: [
    { code: "INCENTIVE", name: "Incentive", kind: "earning" },
    { code: "ADVANCE", name: "Salary advance recovery", kind: "deduction" },
  ],
};

const list: PayrollList = { results: [run], divisions: ["WS", "IM"], last_month: "2026-10", can_prepare: true };

test("HR prepares a division's pay month", async () => {
  const calls = mockApi({
    "GET /api/v1/payroll/": { body: list },
    "POST /api/v1/payroll/": { body: run },
    "GET /api/v1/payroll/4/": { body: run },
  });
  renderAt("/payroll", <PayrollPage />, "/payroll");
  expect(await screen.findByRole("link", { name: "2026-10" })).toBeInTheDocument();
  expect(screen.getByText("67,675.00")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Division"), { target: { value: "IM" } });
  fireEvent.click(screen.getByRole("button", { name: "Prepare" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/payroll/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ division: "IM", month: "2026-10" }) }),
    ),
  );
});

test("each figure shows where it came from, and HR types in an amount for the month", async () => {
  const calls = mockApi({
    "GET /api/v1/payroll/4/": { body: run },
    "POST /api/v1/payroll/4/entries/": { body: run },
  });
  renderAt("/payroll/4", <PayrollPage />, "/payroll/:id");
  expect(await screen.findByRole("heading", { name: /Payroll WS 2026-10/ })).toBeInTheDocument();
  expect(screen.getByText("Pay month Oct 2026: 21 Sep – 20 Oct")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "E001 Kamal Perera" }));
  expect(screen.getByText("2:00 h x 275.00 x 1.50")).toBeInTheDocument();
  expect(screen.getByText("Day rate 2,200.00 (monthly pay ÷ 30); hourly rate 275.00.")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Amount (LKR)"), { target: { value: "3000" } });
  fireEvent.change(screen.getByLabelText("Note"), { target: { value: "Target met" } });
  fireEvent.click(screen.getByRole("button", { name: "Enter for the month" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/payroll/4/entries/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ employee: 7, component: "INCENTIVE", amount: "3000", note: "Target met" }),
      }),
    ),
  );
});

test("the Director approves a payroll waiting for him", async () => {
  const waiting = { ...run, status: "awaiting" as const, status_label: "Waiting for the Director", can_work_out: false, can_submit: false, can_approve: true };
  const calls = mockApi({
    "GET /api/v1/payroll/4/": { body: waiting },
    "POST /api/v1/payroll/4/approve/": { body: { ...waiting, status: "approved", can_approve: false } },
  });
  renderAt("/payroll/4", <PayrollPage />, "/payroll/:id");
  fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/payroll/4/approve/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "" }) }),
    ),
  );
});

test("the Accountant sees the totals only", async () => {
  mockApi({ "GET /api/v1/payroll/4/": { body: { ...run, sees_people: false, lines: [], can_work_out: false, can_submit: false } } });
  renderAt("/payroll/4", <PayrollPage />, "/payroll/:id");
  expect(await screen.findByText("You see the totals only.")).toBeInTheDocument();
  expect(screen.queryByRole("table", { name: "Employees in the payroll" })).not.toBeInTheDocument();
});

test("the Accountant enters an APIT table", async () => {
  const tables: TaxTables = {
    tables: [
      {
        id: 1, kind: "primary", kind_label: "Table 01: primary employment", effective_from: "2025-04-01",
        reason: "IRD APIT Table 01", bands: [{ up_to: "150000.00", rate: "0.00", constant: "0.00" }, { up_to: null, rate: "36.00", constant: "94000.00" }],
      },
    ],
    statutory: [{ effective_from: "2024-01-01", epf_employee: "8.00", epf_employer: "12.00", etf: "3.00", reason: "EPF Act" }],
  };
  const calls = mockApi({
    "GET /api/v1/payroll-tax-tables/": { body: tables },
    "POST /api/v1/payroll-tax-tables/": { body: {} },
  });
  renderAt("/payroll-tax-tables", <TaxTablesPage />);
  expect(await screen.findByText("From 2024-01-01: EPF employee 8.00%, employer 12.00%; ETF 3.00%")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Applies from"), { target: { value: "2026-04-01" } });
  fireEvent.change(screen.getByLabelText("Source (e.g. IRD APIT Table 07, 2025/26)"), { target: { value: "IRD Table 07" } });
  fireEvent.change(screen.getByLabelText("Band 1: up to"), { target: { value: "100000" } });
  fireEvent.change(screen.getByLabelText("Band 1: rate %"), { target: { value: "6" } });
  fireEvent.change(screen.getByLabelText("Band 2: rate %"), { target: { value: "36" } });
  fireEvent.change(screen.getByLabelText("Band 2: less"), { target: { value: "30000" } });
  fireEvent.click(screen.getByRole("button", { name: "Save the table" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/payroll-tax-tables/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          kind: "secondary",
          effective_from: "2026-04-01",
          reason: "IRD Table 07",
          bands: [
            { up_to: "100000", rate: "6", constant: "0" },
            { up_to: null, rate: "36", constant: "30000" },
          ],
        }),
      }),
    ),
  );
});
