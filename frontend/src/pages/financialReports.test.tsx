import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { BalanceSheet, GeneralLedger, TrialBalance } from "../api/financialReports";
import { mockApi, renderAt } from "../test-utils";
import FinancialReportsPage from "./FinancialReportsPage";

const ref = (id: number, number: string, name: string, account_type: string, label: string) => ({
  id, number, name, account_type, account_type_label: label,
});
const cash = ref(1, "1010", "Cash on hand", "bank", "Bank");
const capital = ref(2, "3000", "Share capital", "equity", "Equity");

const tb: TrialBalance = {
  as_at: "2026-11-03", compare_date: null, division: null,
  rows: [
    { account: cash, debit: "1000000.00", credit: "0.00", compare_debit: "0.00", compare_credit: "0.00" },
    { account: capital, debit: "0.00", credit: "1000000.00", compare_debit: "0.00", compare_credit: "0.00" },
  ],
  total_debit: "1000000.00", total_credit: "1000000.00", compare_total_debit: "0.00", compare_total_credit: "0.00",
};

const bs: BalanceSheet = {
  as_at: "2026-11-03", compare_date: "2026-10-31", division: null,
  sections: [
    { key: "assets", title: "Assets", rows: [{ label: "1010 Cash on hand", kind: "account", account: cash, amount: "1000000.00", compare: "900000.00" }], total: "1000000.00", compare_total: "900000.00" },
    { key: "liabilities", title: "Liabilities", rows: [], total: "0.00", compare_total: "0.00" },
    {
      key: "equity", title: "Equity",
      rows: [
        { label: "3000 Share capital", kind: "account", account: capital, amount: "900000.00", compare: "900000.00" },
        { label: "x", kind: "profit", account: null, amount: "100000.00", compare: "0.00" },
      ],
      total: "1000000.00", compare_total: "900000.00",
    },
  ],
};

const gl: GeneralLedger = {
  from: "2026-11-01", to: "2026-11-03", division: null,
  accounts: [
    {
      account: cash, opening: "900000.00", closing: "1000000.00", total_debit: "100000.00", total_credit: "0.00",
      lines: [
        {
          entry: { id: 40, number: "JV26110001" }, entry_date: "2026-11-02", narration: "Accrue repairs", description: "", division: null,
          supplier: null, debit: "100000.00", credit: "0.00", balance: "1000000.00", source_type: "manual_journal",
          source_id: "MJ26110201", source_page: "/journals/manual/5",
        },
      ],
    },
  ],
};

const common = {
  "GET /api/v1/divisions/": { body: [{ id: 1, code: "IM", name: "Plastic Injection Moulding" }] },
  "GET /api/v1/chart-of-accounts/": { body: [] },
};

test("the trial balance balances and each figure opens its ledger", async () => {
  mockApi({ ...common, "GET /api/v1/reports/trial-balance/?as_at=2026-11-03": { body: tb } });
  renderAt("/reports/financial?as_at=2026-11-03", <FinancialReportsPage />, "/reports/financial");
  const table = await screen.findByRole("table", { name: "Trial balance" });
  const foot = within(table).getAllByRole("row").at(-1)!;
  expect(within(foot).getAllByText("1,000,000.00")).toHaveLength(2);
  const link = within(table).getAllByRole("link", { name: "1,000,000.00" })[0];
  expect(link.getAttribute("href")).toContain("tab=gl&account=1&from=2026-11-01&to=2026-11-03");
  expect(screen.getByRole("link", { name: "Excel" }).getAttribute("href")).toContain("/reports/trial-balance/?as_at=2026-11-03&export=xlsx");
});

test("the balance sheet shows the comparison and the profit in equity", async () => {
  mockApi({ ...common, "GET /api/v1/reports/balance-sheet/?as_at=2026-11-03&compare=month": { body: bs } });
  renderAt("/reports/financial?tab=bs&as_at=2026-11-03&compare=month", <FinancialReportsPage />, "/reports/financial");
  const table = await screen.findByRole("table", { name: "Balance sheet" });
  expect(within(table).getByRole("columnheader", { name: "2026-10-31" })).toBeInTheDocument();
  expect(within(table).getByText("Profit to date, not yet closed to retained earnings")).toBeInTheDocument();
  expect(within(table).getByText("Total equity")).toBeInTheDocument();
});

test("a ledger line opens its entry and its document", async () => {
  const calls = mockApi({
    ...common,
    "GET /api/v1/reports/general-ledger/?from=2026-11-01&to=2026-11-03&account=1": { body: gl },
    "GET /api/v1/reports/general-ledger/?from=2026-11-01&to=2026-11-03&division=IM&account=1": { body: { ...gl, division: "IM" } },
  });
  renderAt("/reports/financial?tab=gl&account=1&from=2026-11-01&to=2026-11-03", <FinancialReportsPage />, "/reports/financial");
  const table = await screen.findByRole("table", { name: "1010 Cash on hand" });
  expect(within(table).getByText("Balance brought forward")).toBeInTheDocument();
  expect(within(table).getByRole("link", { name: "JV26110001" })).toHaveAttribute("href", "/journal?entry=40&q=JV26110001");
  expect(within(table).getByRole("link", { name: "MJ26110201" })).toHaveAttribute("href", "/journals/manual/5");
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Division" }).querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(screen.getByRole("combobox", { name: "Division" }), { target: { value: "IM" } });
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/reports/general-ledger/?from=2026-11-01&to=2026-11-03&division=IM&account=1", expect.anything()));
});
