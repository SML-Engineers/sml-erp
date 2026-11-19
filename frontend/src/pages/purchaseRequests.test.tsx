import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { ReorderRow, RequestDetail } from "../api/purchaseRequests";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import PurchaseRequestPage from "./PurchaseRequestPage";
import PurchaseRequestsPage from "./PurchaseRequestsPage";
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
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/reorder-levels/3/request/", expect.objectContaining({ method: "POST" })));
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

// Owner, 18 Nov 2026: Kumari could see the form but saving said "You do not have access".
test("only someone who may raise requests sees the New purchase request form", async () => {
  mockApi({ "GET /api/v1/purchase-requests/": { body: [] } });
  const viewer: CurrentUser = { ...sampleUser, access: { areas: { purchasing: ["view"] }, actions: [], divisions: "all" } };
  const { unmount } = renderAt("/purchase-requests", <PurchaseRequestsPage me={viewer} />);
  expect(await screen.findByText("No purchase requests.")).toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "New purchase request" })).not.toBeInTheDocument();
  unmount();

  const stores: CurrentUser = { ...sampleUser, access: { areas: { stores: ["enter", "view"] }, actions: [], divisions: "all" } };
  renderAt("/purchase-requests", <PurchaseRequestsPage me={stores} />);
  expect(await screen.findByRole("form", { name: "New purchase request" })).toBeInTheDocument();
});

// Owner, 16 Nov 2026: clear statuses in the list.
test("the list says whose draft a request is, who it waits for and who decided", async () => {
  const ruwan = "Ruwan Jayasinghe";
  const row = (id: number, extra: Partial<RequestDetail>) => ({
    ...request,
    id,
    number: `PR2611000${id}`,
    created_by: "Kamal Silva",
    ...extra,
  });
  mockApi({
    "GET /api/v1/purchase-requests/": {
      body: [
        row(1, { status: "draft", people: null }),
        row(2, { status: "awaiting_approval", people: { waiting: { person: ruwan, role: "Director" }, last: null } }),
        row(3, { status: "approved", people: { waiting: null, last: { action: "approve", by: ruwan } } }),
        row(4, { status: "rejected", people: { waiting: null, last: { action: "reject", by: ruwan } } }),
      ],
    },
  });
  renderAt("/purchase-requests", <PurchaseRequestsPage me={sampleUser} />);
  const table = await screen.findByRole("table");
  for (const text of ["Draft of Kamal", "Waiting for Ruwan (Director)", "Approved by Ruwan", "Rejected by Ruwan"])
    expect(within(table).getByText(text)).toBeInTheDocument();
});
