import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { DNDetail, OrderForDelivery } from "../api/deliveryNotes";
import { mockApi, renderAt } from "../test-utils";
import DeliveryNotePage from "./DeliveryNotePage";

const caps = {
  id: 11, line_no: 1, description: "Cap, PP, white", drawing_no: "", unit: "pcs", ordered: "10000.000",
  delivered_before: "6000.000", to_deliver: "4000.000", quantity: null,
  schedule: [{ due_date: "2026-11-03", quantity: "6000.000" }, { due_date: "2026-12-03", quantity: "4000.000" }],
};
const moulds = { ...caps, id: 12, line_no: 2, description: "Cap mould", ordered: "2.000", delivered_before: "0.000", to_deliver: "2.000", schedule: [] };

const order: OrderForDelivery = {
  id: 3, number: "SO26110301", customer: "Unilever Sri Lanka", customer_po: "UL/PO/7781", delivery_address: "Grandpass, Colombo 14",
  lines: [caps, moulds],
};

const draft: DNDetail = {
  id: 8, number: "DN26110301", delivery_date: "2026-11-03", status: "draft", status_label: "Draft",
  order: { id: 3, number: "SO26110301", customer_po: "UL/PO/7781" }, division: "IM", customer: { id: 1, name: "Unilever Sri Lanka" },
  vehicle_no: "LH-4521", created_by: "Sunil", driver: "", delivery_address: "Grandpass, Colombo 14", notes: "",
  issued_by: null, issued_at: null, received_by: "", received_on: null, signed_copy: null, cancel_reason: "",
  lines: [{ ...caps, quantity: "4000.000" }, moulds], can_edit: true, can_receive: false, can_cancel: false,
};

test("the stores make a delivery note from the order's remaining quantities", async () => {
  const calls = mockApi({
    "GET /api/v1/delivery-notes/orders/?order=3": { body: order },
    "POST /api/v1/delivery-notes/": { status: 201, body: draft },
    "GET /api/v1/delivery-notes/8/": { body: draft },
  });
  renderAt("/delivery-notes/new?order=3", <DeliveryNotePage />, "/delivery-notes/:id");
  const form = await screen.findByRole("form", { name: "Delivery note details" });
  const table = within(form).getByRole("table", { name: "What is delivered" });
  expect(within(table).getByText("4,000")).toBeInTheDocument(); // still to deliver
  fireEvent.change(within(form).getByLabelText("Vehicle no."), { target: { value: "LH-4521" } });
  fireEvent.change(within(form).getByLabelText("Delivered now, line 1"), { target: { value: "4000" } });
  fireEvent.click(within(form).getByRole("button", { name: "Make the draft delivery note" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/delivery-notes/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/delivery-notes/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    order: 3,
    vehicle_no: "LH-4521",
    delivery_address: "Grandpass, Colombo 14",
    lines: [
      { order_line: 11, quantity: "4000" },
      { order_line: 12, quantity: "" },
    ],
  });
});

test("an issued note is printed, then the signed copy is recorded", async () => {
  const issued: DNDetail = { ...draft, status: "issued", status_label: "Issued", issued_by: "Sunil", can_edit: false, can_receive: true, can_cancel: true };
  const calls = mockApi({
    "GET /api/v1/delivery-notes/8/": { body: issued },
    "POST /api/v1/delivery-notes/8/received/": { body: { ...issued, status: "received", received_by: "N. Perera", received_on: "2026-11-03", signed_copy: "dn.pdf", can_receive: false } },
  });
  renderAt("/delivery-notes/8", <DeliveryNotePage />, "/delivery-notes/:id");
  const lines = await screen.findByRole("table", { name: "What is delivered" });
  expect(within(lines).queryByText("Cap mould")).not.toBeInTheDocument(); // not on this note
  expect(screen.getByRole("link", { name: "Print for the customer to sign" })).toHaveAttribute("href", "/api/v1/delivery-notes/8/pdf/");
  fireEvent.change(screen.getByLabelText("Received by (name)"), { target: { value: "N. Perera" } });
  fireEvent.click(screen.getByRole("button", { name: "Record the customer's signature" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/delivery-notes/8/received/", expect.objectContaining({ method: "POST" })));
  expect(await screen.findByRole("link", { name: "Signed copy" })).toBeInTheDocument();
});
