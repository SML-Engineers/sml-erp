import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { SalesOrderDetail } from "../api/salesOrders";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import SalesOrderPage from "./SalesOrderPage";
import SalesOrdersPage from "./SalesOrdersPage";

const executive: CurrentUser = { ...sampleUser, access: { areas: { sales: ["enter", "view"] }, actions: [], divisions: "all" } };

const draft: SalesOrderDetail = {
  id: 50,
  number: "SO26103101",
  order_date: "2026-10-31",
  status: "draft",
  source: "quotation",
  division: "IM",
  customer: { id: 4, code: "C0004", name: "Unilever Sri Lanka" },
  customer_po: "",
  currency: "LKR",
  total_amount: "23500.00",
  total_lkr: "23500.00",
  next_delivery: null,
  created_by: "Sales",
  quotation: { id: 12, label: "QL26103101 Rev 0" },
  proforma: null,
  contact: null,
  po_date: null,
  exchange_rate: "1.000000",
  payment_terms: "30 days",
  incoterm: "EXW",
  delivery_address: "Grandpass, Colombo 14",
  notes: "",
  discount_pct: "0.00",
  discount_total: "0.00",
  subtotal: "23500.00",
  tax_total: "0.00",
  cancel_reason: "",
  confirmed_at: null,
  lines: [
    {
      line_no: 1,
      quotation_line: 31,
      description: "Cap, PP, white",
      drawing_no: "",
      quantity: "10000.000",
      unit: "pcs",
      unit_price: "2.35",
      tax_code: null,
      is_tooling: false,
      amount: "23500.00",
      discount: "0.00",
      tax_amount: "0.00",
      total: "23500.00",
      schedule: [{ due_date: "2026-10-31", quantity: "10000.000" }],
    },
  ],
  quotation_lines: [{ id: 31, line_no: 1, description: "Cap, PP, white", quantity: "10000.000" }],
  can_edit: true,
  can_approve: false,
  can_complete: false,
  can_cancel: true,
  approval: null,
  advances: [],
};

test("the creator splits a line into call-offs, adds the PO and confirms", async () => {
  const opened: SalesOrderDetail = { ...draft, status: "open", customer_po: "UL/PO/7781", can_edit: false, can_complete: true };
  const calls = mockApi({
    "GET /api/v1/sales-orders/50/": { body: draft },
    "PUT /api/v1/sales-orders/50/": (sent) => ({
      body: {
        ...draft,
        customer_po: "UL/PO/7781",
        lines: [{ ...draft.lines[0], schedule: (sent as { lines: { schedule: [] }[] }).lines[0].schedule }],
      },
    }),
    "POST /api/v1/sales-orders/50/confirm/": { body: opened },
  });
  renderAt("/sales-orders/50", <SalesOrderPage />, "/sales-orders/:id");
  const form = await screen.findByRole("form", { name: "Sales order details" });
  expect(screen.getByText(/records no sale/)).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Customer's PO no."), { target: { value: "UL/PO/7781" } });
  fireEvent.change(within(form).getByLabelText("Delivery 1 date, line 1"), { target: { value: "2026-11-07" } });
  fireEvent.change(within(form).getByLabelText("Delivery 1 quantity, line 1"), { target: { value: "4000" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add a delivery" }));
  fireEvent.change(within(form).getByLabelText("Delivery 2 date, line 1"), { target: { value: "2026-11-21" } });
  fireEvent.change(within(form).getByLabelText("Delivery 2 quantity, line 1"), { target: { value: "6000" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/sales-orders/50/", expect.objectContaining({ method: "PUT" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/sales-orders/50/" && i?.method === "PUT")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    customer_po: "UL/PO/7781",
    lines: [
      {
        quotation_line: 31,
        quantity: "10000.000",
        schedule: [
          { due_date: "2026-11-07", quantity: "4000" },
          { due_date: "2026-11-21", quantity: "6000" },
        ],
      },
    ],
  });
  expect(JSON.parse(String(init!.body)).lines[0]).not.toHaveProperty("unit_price");

  fireEvent.click(await screen.findByRole("button", { name: "Confirm the order" }));
  expect(await screen.findByRole("button", { name: "Mark completed" })).toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "Sales order details" })).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Sales order" })).toHaveTextContent("UL/PO/7781");
});

test("the Director approves a repeat order typed in", async () => {
  const waiting: SalesOrderDetail = {
    ...draft,
    source: "direct",
    quotation: null,
    quotation_lines: [],
    status: "awaiting_approval",
    can_edit: false,
    can_cancel: false,
    can_approve: true,
    customer_po: "UL/PO/8001",
    approval: {
      status: "pending",
      history: [{ action: "submit", action_label: "Submitted", by: "Sales", at: "2026-10-31T09:00:00", reason: "" }],
    },
  };
  const calls = mockApi({
    "GET /api/v1/sales-orders/50/": { body: waiting },
    "POST /api/v1/sales-orders/50/approve/": { body: { ...waiting, status: "open", can_approve: false } },
  });
  renderAt("/sales-orders/50", <SalesOrderPage />, "/sales-orders/:id");
  expect(await screen.findByText(/the Director approves its prices/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Comment or reason"), { target: { value: "Same as last time" } });
  fireEvent.click(screen.getByRole("button", { name: "Approve the order" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/sales-orders/50/approve/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ comment: "Same as last time" }) }),
    ),
  );
  expect(await screen.findByText(/^Open ·/)).toBeInTheDocument();
});

test("the list links to each order; a repeat order is typed in from it", async () => {
  const calls = mockApi({
    "GET /api/v1/sales-orders/": { body: [{ ...draft, status: "open", customer_po: "UL/PO/7781", next_delivery: "2026-11-07" }] },
    "GET /api/v1/customers/": { body: [{ id: 4, code: "C0004", name: "Unilever Sri Lanka" }] },
    "GET /api/v1/divisions/": {
      body: [
        { id: 1, code: "HO", name: "Head Office", division_type: "shared" },
        { id: 2, code: "IM", name: "Moulding", division_type: "production" },
      ],
    },
    "POST /api/v1/sales-orders/": { status: 201, body: { ...draft, id: 51, source: "direct" } },
  });
  renderAt("/sales-orders", <SalesOrdersPage me={executive} />);
  const table = await screen.findByRole("table", { name: "Sales orders" });
  expect(within(table).getByRole("link", { name: "SO26103101" })).toHaveAttribute("href", "/sales-orders/50");
  expect(within(table).getByText("2026-11-07")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "New repeat order" }));
  const form = screen.getByRole("form", { name: "New repeat order" });
  fireEvent.change(within(form).getByRole("combobox", { name: "Customer" }), { target: { value: "unilever" } });
  fireEvent.mouseDown(await within(form).findByRole("option", { name: "C0004 Unilever Sri Lanka" }));
  const division = within(form).getByLabelText("Division");
  await waitFor(() => expect(within(division).getAllByRole("option")).toHaveLength(2)); // no Head Office
  fireEvent.change(division, { target: { value: "IM" } });
  fireEvent.change(within(form).getByLabelText("Description"), { target: { value: "Cap, PP, white" } });
  fireEvent.change(within(form).getByLabelText("Quantity"), { target: { value: "20000" } });
  fireEvent.change(within(form).getByLabelText("Unit price"), { target: { value: "2.30" } });
  fireEvent.change(within(form).getByLabelText("Delivery date"), { target: { value: "2026-11-10" } });
  fireEvent.click(within(form).getByRole("button", { name: "Make the draft order" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/sales-orders/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/sales-orders/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    customer: 4,
    division: "IM",
    lines: [
      { description: "Cap, PP, white", quantity: "20000", unit_price: "2.30", schedule: [{ due_date: "2026-11-10", quantity: "20000" }] },
    ],
  });
});
