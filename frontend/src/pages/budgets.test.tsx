import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { BudgetDetail } from "../api/budgets";
import { mockApi, renderAt } from "../test-utils";
import BudgetPage from "./BudgetPage";

const months = ["2027-04", "2027-05", "2027-06", "2027-07", "2027-08", "2027-09", "2027-10", "2027-11", "2027-12", "2028-01", "2028-02", "2028-03"];
const draft: BudgetDetail = {
  id: 4, year_start: "2027-04-01", label: "2027-28", version: 1, status: "draft", notes: "", created_by: "Accountant",
  created_at: "2027-03-01T09:00:00Z", approved_at: null, income: "0.00", costs: "0.00", months, rows: [],
  can_edit: true, can_approve: false, approval: null,
  accounts: [{ id: 11, number: "4010", name: "Sales", account_type: "income" }],
  divisions: ["HO", "IM", "WS"],
};

test("the Accountant types a row and saves it", async () => {
  const calls = mockApi({
    "GET /api/v1/budgets/4/": { body: draft },
    "PUT /api/v1/budgets/4/": { body: draft },
  });
  renderAt("/budgets/4", <BudgetPage />, "/budgets/:id");
  fireEvent.click(await screen.findByRole("button", { name: "Add a row" }));
  fireEvent.change(screen.getByLabelText("Account, row 1"), { target: { value: "11" } });
  fireEvent.change(screen.getByLabelText("Division, row 1"), { target: { value: "WS" } });
  fireEvent.change(screen.getByLabelText("Row 1, Apr 27"), { target: { value: "1000" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/budgets/4/",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ notes: "", rows: [{ account: 11, division: "WS", amounts: { "2027-04": "1000" } }] }),
      }),
    ),
  );
});

test("the Director approves a budget waiting for approval", async () => {
  const waiting: BudgetDetail = {
    ...draft, status: "awaiting_approval", can_edit: false, can_approve: true, income: "1000.00",
    rows: [{ account: draft.accounts![0], division: "WS", amounts: { "2027-04": "1000.00" }, total: "1000.00" }],
    approval: { status: "in_progress", history: [{ action: "submit", action_label: "Submitted", by: "Accountant", at: "2027-03-02T10:00:00Z", reason: "" }] },
  };
  const calls = mockApi({
    "GET /api/v1/budgets/4/": { body: waiting },
    "POST /api/v1/budgets/4/approve/": { body: { ...waiting, status: "approved", can_approve: false } },
  });
  renderAt("/budgets/4", <BudgetPage />, "/budgets/:id");
  expect(await screen.findByText("Sales")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/budgets/4/approve/", expect.objectContaining({ method: "POST" })),
  );
});
