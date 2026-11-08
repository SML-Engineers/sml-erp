import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { StockAdjustmentDoc } from "../api/stockOps";
import { mockApi, renderAt } from "../test-utils";
import StockWorkPage from "./StockWorkPage";

const writeOff: StockAdjustmentDoc = {
  id: 3,
  number: "SA26110001",
  kind: "write_off",
  status: "awaiting_approval",
  store: { id: 2, code: "IM-MAIN" },
  adjustment_date: "2026-11-04",
  reason: "Bags torn and wet",
  count: null,
  total_value: "0.00",
  journal_entry: null,
  created_by: "Sunil",
  can_edit: false,
  can_submit: false,
  can_approve: true,
  lines: [
    {
      item: { id: 11, code: "PP-H110", name: "Polypropylene", unit: "kg" },
      lot_no: "A",
      quantity: "-10.000",
      unit_cost: null,
      value: "0.00",
      notes: "",
    },
  ],
};

test("the Director approves a write-off", async () => {
  const calls = mockApi({
    "GET /api/v1/stock-adjustments/": { body: [writeOff] },
    "GET /api/v1/stores/": { body: [] },
    "GET /api/v1/items/": { body: [] },
    "POST /api/v1/stock-adjustments/3/approve/": { body: { ...writeOff, status: "posted", can_approve: false } },
  });
  renderAt("/stores-work?tab=adjustments", <StockWorkPage />, "/stores-work");
  const card = await screen.findByRole("region", { name: "SA26110001" });
  expect(within(card).getByText(/Waiting for the Director/)).toBeInTheDocument();
  fireEvent.click(within(card).getByRole("button", { name: "Approve" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/stock-adjustments/3/approve/", expect.objectContaining({ method: "POST" })),
  );
});
