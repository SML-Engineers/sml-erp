import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { ReorderRow, RequestDetail } from "../api/purchaseRequests";
import { mockApi, renderAt } from "../test-utils";
import PurchaseRequestPage from "./PurchaseRequestPage";
import ReorderPage from "./ReorderPage";

const low: ReorderRow = {
  id: 3,
  item: { id: 11, code: "48-BL-08", name: "Black MB 45% carbon" },
  unit: "kg",
  store: { id: 2, code: "IM-MAIN", name: "Moulding: Main store" },
  division: "IM",
  level: "100.000",
  quantity: "500.000",
  usual_supplier: { id: 5, code: "S0001", name: "SDD Polymer (Pvt) Ltd" },
  suggested_supplier: { id: 5, code: "S0001", name: "SDD Polymer (Pvt) Ltd" },
  on_hand: "80.000",
  on_order: "0.000",
  requested: "0.000",
  low: true,
  alerted_at: "2026-11-03T08:05:00Z",
};

const request: RequestDetail = {
  id: 7,
  number: "PR26110001",
  status: "awaiting_approval",
  division: "IM",
  store: "IM-MAIN",
  supplier: { id: 5, code: "S0001", name: "SDD Polymer (Pvt) Ltd" },
  needed_by: null,
  from_reorder: true,
  created_by: "Sunil",
  created_at: "2026-11-03T08:10:00Z",
  purchase_order: null,
  reason: "Stock of 48-BL-08 at its reorder level",
  end_reason: "",
  approved_at: null,
  lines: [
    {
      line_no: 1,
      item: { id: 11, code: "48-BL-08", name: "Black MB 45% carbon" },
      unit: "kg",
      quantity: "500.000",
      notes: "",
      last_price: "590.00",
    },
  ],
  approvals: [],
  can_edit: false,
  can_approve: true,
  can_order: false,
  can_cancel: false,
};

test("an item at its reorder level is one click from a purchase request", async () => {
  const calls = mockApi({
    "GET /api/v1/reorder-levels/?low=1": { body: [low] },
    "GET /api/v1/items/": { body: [] },
    "GET /api/v1/stores/": { body: [] },
    "GET /api/v1/payees/": { body: [] },
    "POST /api/v1/reorder-levels/3/request/": { status: 201, body: { ...request, status: "draft" } },
  });
  renderAt("/reorder", <ReorderPage />);
  const table = await screen.findByRole("table", { name: "Reorder levels" });
  expect(within(table).getByText("At or below its reorder level")).toBeInTheDocument();
  fireEvent.click(within(table).getByRole("button", { name: "Raise a purchase request" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/reorder-levels/3/request/", expect.objectContaining({ method: "POST" })),
  );
});

test("the approver approves a purchase request", async () => {
  const calls = mockApi({
    "GET /api/v1/purchase-requests/7/": { body: request },
    "POST /api/v1/purchase-requests/7/approve/": { body: { ...request, status: "approved", can_approve: false } },
  });
  renderAt("/purchase-requests/7", <PurchaseRequestPage />, "/purchase-requests/:id");
  expect(await screen.findByText("590.00")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Approve" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/purchase-requests/7/approve/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ comment: "" }) }),
    ),
  );
});
