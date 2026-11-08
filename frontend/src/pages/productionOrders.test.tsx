import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { OrderList, ProductionOrder } from "../api/productionOrders";
import { mockApi, renderAt } from "../test-utils";
import ProductionOrdersPage from "./ProductionOrdersPage";

const row = {
  id: 7,
  number: "MO26110001",
  item: "CAP-28",
  item_name: "Cap 28 mm",
  quantity: "10000",
  unit: "pcs",
  division: "IM",
  purpose: "sales" as const,
  sales_order: "SO26110801",
  customer: "Unilever Sri Lanka",
  first_due: "2026-11-22",
  status: "released" as const,
  status_label: "Released",
};
const list: OrderList = { results: [row], can_plan: true, statuses: [{ value: "released", label: "Released" }] };
const order: ProductionOrder = {
  ...row,
  made: "3960",
  sales_line: {
    id: 3,
    order: "SO26110801",
    line_no: 1,
    customer: "Unilever Sri Lanka",
    description: "Cap, PP, white",
    quantity: "10000",
    unit: "pcs",
  },
  dues: [
    { due_date: "2026-11-22", quantity: "6000" },
    { due_date: "2026-12-06", quantity: "4000" },
  ],
  notes: "",
  end_reason: "",
  bom: { id: 4, revision: 1, item: "CAP-28", status: "approved" },
  mould: "MD-001",
  family_shots: "",
  requirements: [
    {
      seq: 10,
      code: "PP-H",
      name: "PP homopolymer",
      line_type: "raw",
      required: "47.25",
      unit: "kg",
      on_hand: "60",
      coming: "0",
      other_orders: "47.25",
      shortage: "34.5",
      customer_supplied: false,
      buy: true,
    },
    {
      seq: 30,
      code: "BAG-1K",
      name: "Polybag",
      line_type: "packing",
      required: "10",
      unit: "pcs",
      on_hand: "100",
      coming: "0",
      other_orders: "0",
      shortage: "0",
      customer_supplied: false,
      buy: true,
    },
  ],
  short: true,
  created_by: "Planner",
  released_by: "Planner",
  released_at: "2026-11-08T10:00:00Z",
  can_edit: false,
  can_release: false,
  can_complete: true,
  can_close: false,
  can_cancel: true,
  can_request: true,
};

test("an order shows its due dates and what it is short of; the stores raise a request", async () => {
  const calls = mockApi({
    "GET /api/v1/production-orders/?q=&status=open": { body: list },
    "GET /api/v1/production-orders/7/": { body: order },
    "POST /api/v1/production-orders/7/purchase-request/": {
      body: { ...order, short: false, purchase_request: { id: 1, number: "PR26110001" } },
    },
  });
  renderAt("/production-orders?order=7", <ProductionOrdersPage />, "/production-orders");
  const panel = await screen.findByRole("region", { name: "Production order MO26110001" });
  expect(within(panel).getByText(/For SO26110801 line 1, Unilever Sri Lanka/)).toBeInTheDocument();
  expect(within(panel).getByText(/6,000 by 2026-11-22; 4,000 by 2026-12-06/)).toBeInTheDocument();
  expect(within(panel).getByText(/3,960 made so far/)).toBeInTheDocument();
  const needs = within(panel).getByRole("table", { name: "Materials for the order" });
  expect(within(within(needs).getByText("PP-H").closest("tr")!).getByText("34.5")).toBeInTheDocument();
  fireEvent.click(within(panel).getByRole("button", { name: "Raise a purchase request" }));
  expect(await within(panel).findByText(/Purchase request PR26110001 made as a draft/)).toBeInTheDocument();
  expect(calls).toHaveBeenCalledWith("/api/v1/production-orders/7/purchase-request/", expect.objectContaining({ method: "POST" }));
});

test("a new order for a sales order line", async () => {
  const calls = mockApi({
    "GET /api/v1/production-orders/?q=&status=open": { body: { ...list, results: [] } },
    "GET /api/v1/production-orders/sales-lines/?q=": {
      body: {
        results: [
          {
            ...order.sales_line,
            division: "IM",
            planned: "0",
            left: "10000",
            schedule: [{ due_date: "2026-11-22", quantity: "10000" }],
          },
        ],
      },
    },
    "POST /api/v1/production-orders/": { body: { ...order, status: "draft", status_label: "Draft" }, status: 201 },
    "GET /api/v1/production-orders/7/": { body: { ...order, status: "draft", status_label: "Draft" } },
  });
  renderAt("/production-orders", <ProductionOrdersPage />);
  fireEvent.click(await screen.findByRole("button", { name: "New production order" }));
  const form = screen.getByRole("form", { name: "New production order" });
  fireEvent.change(within(form).getByLabelText("Part"), { target: { value: "CAP-28" } });
  fireEvent.change(within(form).getByLabelText("Quantity"), { target: { value: "10000" } });
  fireEvent.change(within(form).getByLabelText("For"), { target: { value: "sales" } });
  const line = await within(form).findByRole("option", {
    name: /SO26110801 line 1 — Unilever Sri Lanka — Cap, PP, white \(10,000 pcs left to plan\)/,
  });
  fireEvent.change(within(form).getByLabelText("Sales order line"), { target: { value: (line as HTMLOptionElement).value } });
  expect(within(form).getByText(/Delivery schedule: 10,000 by 2026-11-22/)).toBeInTheDocument();
  fireEvent.click(within(form).getByRole("button", { name: "Save the order" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/production-orders/",
      expect.objectContaining({ body: JSON.stringify({ item: "CAP-28", quantity: "10000", purpose: "sales", notes: "", sales_line: 3 }) }),
    ),
  );
  expect(await screen.findByRole("region", { name: "Production order MO26110001" })).toBeInTheDocument();
});

test("a draft is released and a released order cancelled with a reason", async () => {
  const draft = { ...order, status: "draft" as const, status_label: "Draft", can_edit: true, can_release: true, can_complete: false };
  const calls = mockApi({
    "GET /api/v1/production-orders/?q=&status=open": { body: list },
    "GET /api/v1/production-orders/7/": { body: draft },
    "POST /api/v1/production-orders/7/release/": { body: order },
    "POST /api/v1/production-orders/7/cancel/": {
      body: { ...order, status: "cancelled", status_label: "Cancelled", end_reason: "Not needed" },
    },
  });
  renderAt("/production-orders?order=7", <ProductionOrdersPage />, "/production-orders");
  const panel = await screen.findByRole("region", { name: "Production order MO26110001" });
  expect(within(panel).getByRole("table", { name: "Materials for the order" })).toBeInTheDocument();
  expect(within(panel).getByText("Materials the BOM in force would need")).toBeInTheDocument();
  fireEvent.click(within(panel).getByRole("button", { name: "Release" }));
  expect(await within(panel).findByRole("button", { name: "Mark completed" })).toBeInTheDocument();
  fireEvent.change(within(panel).getByLabelText("Reason for cancelling"), { target: { value: "Not needed" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Cancel the order" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/production-orders/7/cancel/",
      expect.objectContaining({ body: JSON.stringify({ reason: "Not needed" }) }),
    ),
  );
  expect(await within(panel).findByText("Cancelled: Not needed")).toBeInTheDocument();
});

test("where used lists the orders making and needing an item", async () => {
  mockApi({
    "GET /api/v1/production-orders/?q=&status=open": { body: list },
    "GET /api/v1/production-orders/where-used/?item=PP-H": {
      body: {
        item: "PP-H",
        name: "PP homopolymer",
        making: [],
        making_total: "0",
        needing: [{ id: 7, number: "MO26110001", item: "CAP-28", required: "47.25", unit: "kg" }],
      },
    },
  });
  renderAt("/production-orders", <ProductionOrdersPage />);
  const panel = await screen.findByRole("region", { name: "Where used" });
  fireEvent.change(within(panel).getByLabelText("Item code"), { target: { value: "PP-H" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Look up" }));
  expect(await within(panel).findByText("Released orders that need it: MO26110001 (47.25 kg)")).toBeInTheDocument();
  expect(within(panel).getByText("No open order makes it.")).toBeInTheDocument();
});
