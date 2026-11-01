import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { PODetail } from "../api/purchaseOrders";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import PurchaseOrderPage from "./PurchaseOrderPage";
import PurchaseOrdersPage from "./PurchaseOrdersPage";

const draft: PODetail = {
  id: 9, number: "PO26110101", revision: 0, label: "PO26110101", po_date: "2026-11-01", delivery_date: "2026-11-08",
  status: "draft", division: "IM", supplier: { id: 3, code: "S0003", name: "SDD Polymer (Pvt) Ltd" }, currency: "LKR",
  total_amount: "177000.00", total_lkr: "177000.00", created_by: "Buyer", deliver_to: "SML Engineers\nSeeduwa",
  pay_mode: "online", payment_terms: "Net 30", exchange_rate: "1.000000", notes: "", subtotal: "177000.00", tax_total: "0.00",
  approved_at: null, end_reason: "", parent: null, revisions: [],
  lines: [
    {
      line_no: 1, item: { id: 5, code: "48-BL-08" }, description: "Black MB 45% carbon", unit: "kg", quantity: "300.000",
      unit_price: "590.00", amount: "177000.00", tax_code: null, tax_amount: "0.00", total: "177000.00", received_quantity: "0.000",
    },
  ],
  can_edit: true, can_approve: false, can_revise: false, can_cancel: true, can_close: false, approval: null,
  can_email: false, emails: [],
};

const formApi = {
  "GET /api/v1/items/": { body: [{ id: 5, code: "48-BL-08", name: "Black MB 45% carbon", unit: "kg" }] },
  "GET /api/v1/taxes/": { body: { components: [], codes: [] } },
  "GET /api/v1/payees/": { body: [{ id: 3, code: "S0003", name: "SDD Polymer (Pvt) Ltd" }] },
  "GET /api/v1/divisions/": {
    body: [
      { id: 1, code: "HO", name: "Head Office", division_type: "shared" },
      { id: 2, code: "IM", name: "Moulding", division_type: "production" },
    ],
  },
};

test("the buyer raises a PO and sends it to the Director", async () => {
  const calls = mockApi({
    ...formApi,
    "POST /api/v1/purchase-orders/": { status: 201, body: draft },
    "GET /api/v1/purchase-orders/9/": { body: draft },
    "POST /api/v1/purchase-orders/9/submit/": { body: { ...draft, status: "awaiting_approval", can_edit: false, can_cancel: false } },
  });
  renderAt("/purchase-orders/new", <PurchaseOrderPage />, "/purchase-orders/:id");
  const form = await screen.findByRole("form", { name: "Purchase order details" });
  fireEvent.change(within(form).getByRole("combobox", { name: "Supplier" }), { target: { value: "sdd" } });
  fireEvent.mouseDown(await within(form).findByRole("option", { name: "S0003 SDD Polymer (Pvt) Ltd" }));
  const division = within(form).getByLabelText("Division");
  await waitFor(() => expect(within(division).getAllByRole("option")).toHaveLength(2));
  fireEvent.change(division, { target: { value: "IM" } });
  fireEvent.change(within(form).getByLabelText("Delivery date"), { target: { value: "2026-11-08" } });
  fireEvent.change(within(form).getByRole("combobox", { name: "Item, line 1" }), { target: { value: "black" } });
  fireEvent.mouseDown(await within(form).findByRole("option", { name: "48-BL-08 Black MB 45% carbon (kg)" }));
  fireEvent.change(within(form).getByLabelText("Quantity, line 1"), { target: { value: "300" } });
  fireEvent.change(within(form).getByLabelText("Rate, line 1"), { target: { value: "590" } });
  fireEvent.click(within(form).getByRole("button", { name: "Make the draft PO" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/purchase-orders/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/purchase-orders/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    supplier: 3,
    division: "IM",
    delivery_date: "2026-11-08",
    pay_mode: "online",
    lines: [{ item: 5, quantity: "300", unit_price: "590", tax_code: null }],
  });
});

test("the Director approves a waiting PO", async () => {
  const waiting: PODetail = {
    ...draft, status: "awaiting_approval", can_edit: false, can_cancel: false, can_approve: true,
    approval: { status: "in_progress", history: [{ action: "submit", action_label: "Submitted", by: "Buyer", at: "2026-11-01T09:00:00", reason: "" }] },
  };
  const calls = mockApi({
    "GET /api/v1/purchase-orders/9/": { body: waiting },
    "POST /api/v1/purchase-orders/9/approve/": { body: { ...waiting, status: "approved", can_approve: false, can_revise: true } },
  });
  renderAt("/purchase-orders/9", <PurchaseOrderPage />, "/purchase-orders/:id");
  const lines = await screen.findByRole("table", { name: "Items ordered" });
  expect(within(lines).getByText("48-BL-08")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Comment or reason"), { target: { value: "Price as agreed" } });
  fireEvent.click(screen.getByRole("button", { name: "Approve the PO" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/purchase-orders/9/approve/",
      expect.objectContaining({ body: JSON.stringify({ comment: "Price as agreed" }) }),
    ),
  );
  expect(await screen.findByRole("button", { name: "Revise (needs a reason)" })).toBeInTheDocument();
});

test("the list links to each PO; only buyers see New purchase order", async () => {
  const buyer: CurrentUser = { ...sampleUser, access: { areas: { purchasing: ["enter", "view"] }, actions: [], divisions: "all" } };
  mockApi({ "GET /api/v1/purchase-orders/": { body: [draft] } });
  renderAt("/purchase-orders", <PurchaseOrdersPage me={buyer} />);
  const table = await screen.findByRole("table", { name: "Purchase orders" });
  expect(within(table).getByRole("link", { name: "PO26110101" })).toHaveAttribute("href", "/purchase-orders/9");
  expect(within(table).getByText("LKR 177,000.00")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "New purchase order" })).toHaveAttribute("href", "/purchase-orders/new");
});

test("the buyer emails an approved PO to the supplier and can print it", async () => {
  const approved: PODetail = { ...draft, status: "approved", can_edit: false, can_cancel: true, can_revise: true, can_email: true };
  const calls = mockApi({
    "GET /api/v1/purchase-orders/9/": { body: approved },
    "GET /api/v1/purchase-orders/9/email/": {
      body: { from: "purchasing@sml.lk", ready: true, to: ["sales@sddpolymer.lk"], cc: [], subject: "Purchase order PO26110101 from SML", body: "Dear SDD" },
    },
    "POST /api/v1/purchase-orders/9/email/": {
      body: { ...approved, emails: [{ to: "sales@sddpolymer.lk", subject: "PO", status: "sent", error: "", sent_at: "2026-11-01T10:00:00", by: "Buyer" }] },
    },
  });
  renderAt("/purchase-orders/9", <PurchaseOrderPage />, "/purchase-orders/:id");
  expect(await screen.findByRole("link", { name: "Print (PDF)" })).toHaveAttribute("href", "/api/v1/purchase-orders/9/pdf/");
  expect(screen.queryByText(/Prints marked DRAFT/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Email the PO to the supplier" }));
  const form = await screen.findByRole("form", { name: "Email to the supplier" });
  expect(within(form).getByDisplayValue("sales@sddpolymer.lk")).toBeInTheDocument();
  fireEvent.submit(form);
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/purchase-orders/9/email/", expect.objectContaining({ method: "POST" })));
  expect(await screen.findByText(/sales@sddpolymer.lk · Buyer/)).toBeInTheDocument();
});
