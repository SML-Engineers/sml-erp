import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { MigrationReport, OpeningDoc } from "../api/migration";
import { mockApi, renderAt } from "../test-utils";
import MigrationPage from "./MigrationPage";

const report: MigrationReport = {
  as_at: "2026-10-31", accounts: 5, debits: "980000.00", credits: "986750.00", receivables: "150000.00", payables: "80000.00",
  stock_in_trial_balance: "0.00", stock_in_item_list: null, customers: 1, suppliers: 1,
  errors: ["The trial balance does not balance: debits 980,000.00, credits 986,750.00 (out by 6,750.00)."], warnings: [],
};
const waiting: OpeningDoc = {
  id: 2, as_at: "2026-10-31", status: "awaiting_approval", report: { ...report, errors: [] }, created_by: "Accountant",
  journal_entry: null, total_debit: "650000.00", total_credit: "650000.00",
  lines: [{ account: "1010 Cash", party: "", description: "QuickBooks: Cash", debit: "500000.00", credit: "0.00" }],
  can_send: false, can_approve: true, history: [{ action: "Submitted", by: "Accountant", at: "2026-11-05T09:00:00", reason: "" }],
};

test("the check lists what to correct, and the Director approves the opening balances", async () => {
  const calls = mockApi({
    "GET /api/v1/migration/": { body: { can_enter: true, documents: [waiting] } },
    "POST /api/v1/migration/": { body: { report, document: null } },
    "POST /api/v1/migration/2/approve/": { body: { ...waiting, status: "posted", can_approve: false } },
  });
  renderAt("/migration", <MigrationPage />);
  const input = await screen.findByLabelText("Trial balance (required)");
  fireEvent.change(input, { target: { files: [new File(["x"], "tb.xlsx")] } });
  fireEvent.click(screen.getByRole("button", { name: "Check the files" }));
  expect(await screen.findByRole("list", { name: "To correct first" })).toHaveTextContent("out by 6,750.00");
  expect(screen.getByRole("button", { name: "Make the opening balances" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Approve and post" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/migration/2/approve/", expect.objectContaining({ method: "POST" })));
});
