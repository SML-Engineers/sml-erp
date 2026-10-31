import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { ProformaDetail } from "../api/proformas";
import { mockApi, renderAt } from "../test-utils";
import ProformaPage from "./ProformaPage";

const draft: ProformaDetail = {
  id: 40, number: "PI261031-01", issue_date: "2026-10-31", status: "draft", division: "IM",
  customer: { id: 4, code: "C0004", name: "Rhino Roofing Products Ltd" }, quotation: { id: 12, label: "QL26103101 Rev 0" },
  currency: "LKR", total_amount: "645268.25", total_lkr: "645268.25", created_by: "Sales", contact: { id: 7, name: "Sunil" },
  exchange_rate: "1.000000", rate_date: null, customer_po: "", payment_terms: "50% advance", delivery_lead_time: "", incoterm: "EXW",
  port_of_loading: "", port_of_destination: "", bank_account: null, advance_pct: "0.00", advance_amount: "0.00", notes: "",
  discount_pct: "3.00", discount_total: "16500.00", subtotal: "533500.00", tax_total: "111768.25", cancel_reason: "",
  lines: [
    {
      line_no: 1, quotation_line: 31, description: "Mould for CLIP, 32 cavities", drawing_no: "", quantity: "1.000", unit: "pcs",
      unit_price: "550000.00", is_tooling: true, amount: "550000.00", discount: "16500.00", tax_amount: "111768.25", total: "645268.25",
      cartons: null, qty_per_carton: null, net_weight_kg: null, gross_weight_kg: null, carton_length_cm: null, carton_width_cm: null,
      carton_height_cm: null, volume_m3: null,
    },
  ],
  packing_totals: { cartons: null, net_weight_kg: null, gross_weight_kg: null, volume_m3: null },
  quotation_lines: [{ id: 31, line_no: 1, description: "Mould for CLIP, 32 cavities", quantity: "1.000", unit_price: "550000.00", breaks: [] }],
  can_edit: true,
  bank_choices: [{ id: 1, code: "COM-CUR", name: "SML current", bank_name: "Commercial Bank", currency: "LKR" }],
  can_cancel: false,
  can_email: false,
  emails: [],
  advances: [],
  can_make_sales_order: false,
  sales_orders: [],
};

test("the creator fills in the packing list, bank and advance, then issues", async () => {
  const issued: ProformaDetail = { ...draft, status: "issued", can_edit: false, can_cancel: true, can_email: true };
  const calls = mockApi({
    "GET /api/v1/proformas/40/": { body: draft },
    "PUT /api/v1/proformas/40/": {
      body: { ...draft, advance_pct: "50.00", advance_amount: "322634.13", packing_totals: { cartons: "1", net_weight_kg: "180", gross_weight_kg: "210", volume_m3: "0.480" } },
    },
    "POST /api/v1/proformas/40/issue/": { body: issued },
  });
  renderAt("/proformas/40", <ProformaPage />, "/proformas/:id");
  const form = await screen.findByRole("form", { name: "Proforma details" });
  expect(screen.getByText(/records no sale/)).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Cartons, line 1"), { target: { value: "1" } });
  fireEvent.change(within(form).getByLabelText("Net weight (kg), line 1"), { target: { value: "180" } });
  fireEvent.change(within(form).getByLabelText("Gross weight (kg), line 1"), { target: { value: "210" } });
  fireEvent.change(within(form).getByLabelText("Bank account for payment (printed)"), { target: { value: "1" } });
  fireEvent.change(within(form).getByLabelText("Advance %"), { target: { value: "50" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/proformas/40/", expect.objectContaining({ method: "PUT" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/proformas/40/" && i?.method === "PUT")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    bank_account: 1,
    advance_pct: "50",
    lines: [{ quotation_line: 31, quantity: "1.000", cartons: "1", net_weight_kg: "180", gross_weight_kg: "210" }],
  });
  expect(await screen.findByText(/Packing: 1 cartons/)).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Issue the proforma" }));
  expect(await screen.findByRole("button", { name: "Cancel the proforma" })).toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "Proforma details" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Print with packing list (PDF)" })).toHaveAttribute("href", "/api/v1/proformas/40/pdf/");
});

test("an issued proforma is cancelled with a reason", async () => {
  const issued: ProformaDetail = { ...draft, status: "issued", can_edit: false, can_cancel: true };
  const calls = mockApi({
    "GET /api/v1/proformas/40/": { body: issued },
    "POST /api/v1/proformas/40/cancel/": { body: { ...issued, status: "cancelled", can_cancel: false, cancel_reason: "Order changed" } },
  });
  renderAt("/proformas/40", <ProformaPage />, "/proformas/:id");
  fireEvent.change(await screen.findByLabelText("Reason for cancelling"), { target: { value: "Order changed" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancel the proforma" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/proformas/40/cancel/", expect.objectContaining({ method: "POST" })));
  expect(await screen.findByText("Cancelled: Order changed")).toBeInTheDocument();
});

test("an issued proforma makes a sales order in one click", async () => {
  const issued: ProformaDetail = { ...draft, status: "issued", can_edit: false, can_make_sales_order: true };
  const calls = mockApi({
    "GET /api/v1/proformas/40/": { body: issued },
    "POST /api/v1/sales-orders/": { status: 201, body: { id: 51 } },
  });
  renderAt("/proformas/40", <ProformaPage />, "/proformas/:id");
  fireEvent.click(await screen.findByRole("button", { name: "Make a sales order" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/sales-orders/", expect.objectContaining({ method: "POST", body: JSON.stringify({ proforma: 40 }) })),
  );
});
