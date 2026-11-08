import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { Reconciliation } from "../api/reconciliation";
import { mockApi, renderAt } from "../test-utils";
import ReconciliationPage from "./ReconciliationPage";

function lastMonthEnd(): string {
  const now = new Date();
  const end = new Date(now.getFullYear(), now.getMonth(), 0);
  return `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, "0")}-${String(end.getDate()).padStart(2, "0")}`;
}

const rec: Reconciliation = {
  account: { id: 2, code: "COM-CUR", name: "Commercial Bank current" },
  period_end: lastMonthEnd(),
  locked_to: null,
  bank_balance: "18750.00",
  book_balance: "17250.00",
  unpresented_total: "-1500.00",
  not_in_books_total: "-250.00",
  difference: "0.00",
  unpresented: [],
  lines: [
    {
      id: 7,
      date: "2026-10-08",
      description: "CHQ 000100",
      reference: "",
      money_out: "1000.00",
      money_in: "0.00",
      balance: "19000.00",
      match: null,
      suggestion: {
        entry: { id: 31, number: "JE-31" },
        date: "2026-10-06",
        narration: "Cheque 000100",
        source_type: "supplier_payment",
        source_id: "PY26100001",
        amount: "-1000.00",
        reference_found: true,
      },
      coding: null,
    },
  ],
  done: [],
};

test("the accountant accepts a suggested match", async () => {
  const calls = mockApi({
    "GET /api/v1/payments/accounts/": {
      body: [
        { id: 2, code: "COM-CUR", name: "Commercial Bank current", kind: "current", currency: "LKR", has_ledger: true, next_cheque: null },
      ],
    },
    [`GET /api/v1/reconciliation/?account=2&period_end=${lastMonthEnd()}`]: { body: rec },
    "GET /api/v1/bank-rules/": { body: [] },
    "GET /api/v1/chart-of-accounts/": { body: [] },
    "POST /api/v1/reconciliation/match/": { body: { ok: true } },
  });
  renderAt("/reconciliation", <ReconciliationPage />);
  await screen.findByRole("option", { name: "COM-CUR Commercial Bank current" });
  fireEvent.change(screen.getByLabelText("Bank account"), { target: { value: "2" } });
  const table = await screen.findByRole("table", { name: "Statement lines" });
  fireEvent.click(within(table).getByRole("button", { name: "Accept" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/reconciliation/match/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ line: 7, entry: 31 }) }),
    ),
  );
});
