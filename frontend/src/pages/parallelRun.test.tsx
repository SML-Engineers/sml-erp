import { fireEvent, screen, within } from "@testing-library/react";

import type { Comparison } from "../api/migration";
import { mockApi, renderAt } from "../test-utils";
import ParallelRunPage from "./ParallelRunPage";

const comparison: Comparison = {
  as_at: "2027-04-30",
  accounts: [
    { label: "1010 Cash", quickbooks: "499000.00", erp: "500000.00", difference: "1000.00", agrees: false },
    { label: "1100 Debtors", quickbooks: "150000.00", erp: "150000.00", difference: "0.00", agrees: true },
  ],
  unknown_accounts: [],
  customers: { rows: [{ label: "Lanka Tiles PLC", quickbooks: "150000.00", erp: "150000.00", difference: "0.00", agrees: true }], unknown: [] },
  suppliers: null,
  differences: { accounts: 1, customers: 0, suppliers: null },
};

test("only the differences are listed until all are asked for", async () => {
  mockApi({ "POST /api/v1/parallel-run/": { body: comparison } });
  renderAt("/parallel-run", <ParallelRunPage />);
  fireEvent.change(screen.getByLabelText("Trial balance (required)"), { target: { files: [new File(["x"], "tb.xlsx")] } });
  fireEvent.click(screen.getByRole("button", { name: "Compare" }));
  const accounts = await screen.findByRole("table", { name: "Accounts" });
  expect(within(accounts).getByText("1010 Cash")).toBeInTheDocument();
  expect(within(accounts).queryByText("1100 Debtors")).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Customers" })).toHaveTextContent("Everything agrees");
  fireEvent.click(screen.getByRole("checkbox", { name: /Show the lines that agree/ }));
  expect(within(accounts).getByText("1100 Debtors")).toBeInTheDocument();
});
