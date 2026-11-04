import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { RevaluationRow } from "../api/revaluation";
import { mockApi, renderAt } from "../test-utils";
import RevaluationPage from "./RevaluationPage";

const draft: RevaluationRow = {
  id: 3, month_end: "2026-10-31", status: "draft", open_items_total: "25000.00", balances_total: "10000.00",
  journal_entry: null, reversal_entry: null, balances_entry: null, prepared_by: "Accountant", posted_by: null,
  lines: [
    { id: 1, kind: "receivable", document: "W1-0042", link: "/tax-invoices/42", party: "Mahindra Gears", division: "WS", currency: "USD", open_amount: "2500.00", carried_lkr: "750000.00", rate: "310", rate_date: "2026-10-31", revalued_lkr: "775000.00", difference: "25000.00", balance_from: "" },
  ],
};

function lastMonth(): string {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

test("the statement's balance is sent and the checked month is posted", async () => {
  const calls = mockApi({
    [`GET /api/v1/revaluations/?month_end=${lastMonth()}`]: {
      body: {
        suggested_month: "2026-10-31",
        accounts: [{ id: 7, code: "com-usd", name: "Commercial Bank USD", currency: "USD", statement_balance: "1000.00", statement_date: "2026-10-31" }],
        runs: [draft],
      },
    },
    "POST /api/v1/revaluations/": { status: 201, body: draft },
    "POST /api/v1/revaluations/3/post/": { body: { ...draft, status: "posted", journal_entry: "JE-1", reversal_entry: "JE-2" } },
  });
  renderAt("/revaluation", <RevaluationPage />);
  expect(await screen.findByLabelText("Balance of com-usd")).toHaveValue("1000.00");
  fireEvent.click(screen.getByRole("button", { name: /Work out/ }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/revaluations/",
      expect.objectContaining({ method: "POST", body: expect.stringContaining('"7":"1000.00"') }),
    ),
  );
  const month = screen.getByRole("region", { name: "2026-10-31" });
  expect(within(month).getByRole("link", { name: "W1-0042" })).toBeInTheDocument();
  fireEvent.click(within(month).getByRole("button", { name: "Checked: post it" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/revaluations/3/post/", expect.objectContaining({ method: "POST" })),
  );
});
