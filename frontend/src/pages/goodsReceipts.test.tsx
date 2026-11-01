import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { GRNDetail } from "../api/goodsReceipts";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import GoodsReceiptPage from "./GoodsReceiptPage";
import GoodsReceiptsPage from "./GoodsReceiptsPage";

const draft: GRNDetail = {
  id: 4, number: "GRN26110101", receipt_date: "2026-11-01", status: "draft", division: "IM", store: "IM-QUAR",
  purchase_order: { id: 9, label: "PO26110101" }, supplier: { id: 3, code: "S0003", name: "SDD Polymer (Pvt) Ltd" },
  delivery_note_no: "", created_by: "Stores", vehicle_no: "", supplier_invoice_no: "", notes: "",
  confirmed_by: null, confirmed_at: null, reversal_reason: "", reversed_at: null,
  lines: [
    {
      line_no: 1, po_line: 21, item: { id: 5, code: "48-BL-08", name: "Black MB" }, description: "Black MB 45% carbon", unit: "kg",
      ordered_quantity: "300.000", outstanding_quantity: "300.000", received_quantity: "300.000", damaged_quantity: "0.000",
      good_quantity: "300.000", excess_quantity: "0.000", notes: "",
    },
  ],
  photos: [], can_edit: true, can_add_photo: true, can_approve_excess: false, can_request_reversal: false,
  can_approve_reversal: false, excess_history: [], reversal_history: [],
};

test("the stores person receives against an approved PO", async () => {
  const stores: CurrentUser = { ...sampleUser, access: { areas: { stores: ["enter", "view"] }, actions: [], divisions: "all" } };
  const calls = mockApi({
    "GET /api/v1/goods-receipts/": { body: [] },
    "GET /api/v1/goods-receipts/receivable/": {
      body: [
        {
          id: 9, label: "PO26110101", po_date: "2026-11-01", delivery_date: "2026-11-08", status: "approved", division: "IM",
          supplier: { id: 3, code: "S0003", name: "SDD Polymer (Pvt) Ltd" }, outstanding_lines: 1,
        },
      ],
    },
    "POST /api/v1/goods-receipts/": { status: 201, body: draft },
  });
  renderAt("/goods-receipts", <GoodsReceiptsPage me={stores} />);
  fireEvent.click(await screen.findByRole("button", { name: "Receive against PO26110101" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/goods-receipts/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ purchase_order: 9 }) }),
    ),
  );
});

test("the stores person enters the damaged quantity, saves and confirms", async () => {
  const calls = mockApi({
    "GET /api/v1/goods-receipts/4/": { body: draft },
    "PUT /api/v1/goods-receipts/4/": { body: draft },
    "POST /api/v1/goods-receipts/4/confirm/": { body: { ...draft, status: "confirmed", can_edit: false, can_request_reversal: true } },
  });
  renderAt("/goods-receipts/4", <GoodsReceiptPage />, "/goods-receipts/:id");
  const form = await screen.findByRole("form", { name: "Goods receipt details" });
  fireEvent.change(within(form).getByLabelText("Damaged, 48-BL-08"), { target: { value: "20" } });
  fireEvent.change(within(form).getByLabelText("Delivery note"), { target: { value: "DN-551" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save the GRN" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/goods-receipts/4/", expect.objectContaining({ method: "PUT" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/goods-receipts/4/" && i?.method === "PUT")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    delivery_note_no: "DN-551",
    lines: [{ po_line: 21, received_quantity: "300.000", damaged_quantity: "20" }],
  });
  fireEvent.click(screen.getByRole("button", { name: "Confirm the GRN" }));
  expect(await screen.findByRole("button", { name: "Ask to reverse (needs a reason)" })).toBeInTheDocument();
});

test("the Director sees the excess and accepts it", async () => {
  const waiting: GRNDetail = {
    ...draft, status: "awaiting_approval", can_edit: false, can_add_photo: false, can_approve_excess: true,
    lines: [{ ...draft.lines[0], received_quantity: "320.000", good_quantity: "320.000", excess_quantity: "20.000" }],
    excess_history: [{ action: "submit", action_label: "Submitted", by: "Stores", at: "2026-11-01T09:00:00", reason: "48-BL-08: 20 over" }],
  };
  const calls = mockApi({
    "GET /api/v1/goods-receipts/4/": { body: waiting },
    "POST /api/v1/goods-receipts/4/approve/": { body: { ...waiting, status: "confirmed", can_approve_excess: false } },
  });
  renderAt("/goods-receipts/4", <GoodsReceiptPage />, "/goods-receipts/:id");
  const lines = await screen.findByRole("table", { name: "Goods received" });
  expect(within(lines).getByText("20")).toBeInTheDocument();
  expect(screen.getByText(/48-BL-08: 20 over/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Accept the excess" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/goods-receipts/4/approve/", expect.objectContaining({ method: "POST" })));
  expect(await screen.findByText(/^Confirmed ·/)).toBeInTheDocument();
});
