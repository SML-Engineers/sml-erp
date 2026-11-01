import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { InvoiceDetail } from "../api/supplierInvoices";
import { mockApi, renderAt } from "../test-utils";
import SupplierInvoicePage from "./SupplierInvoicePage";

const draft: InvoiceDetail = {
  id: 3, number: "SI26110101", invoice_no: "INV-77", invoice_date: "2026-11-01", due_date: "2026-12-16", status: "draft", division: "IM",
  supplier: { id: 2, code: "S0002", name: "Fasteners Lanka" }, currency: "LKR", total_amount: "13000.00", total_lkr: "0.00", created_by: "Clerk",
  stated_total: "13000.00", subtotal: "13000.00", tax_total: "0.00", discrepancies: [], notes: "", exception_reason: "", cancel_reason: "",
  journal: null, posted_at: null,
  lines: [
    {
      line_no: 1, grn_line: 40, grn: { id: 4, number: "GRN26110101" }, po: { id: 9, label: "PO26110101" },
      item: { code: "M6-INSERT", name: "Brass insert M6", unit: "pcs" }, quantity: "1000.000", accepted_quantity: "1000.000",
      unit_price: "13.00", po_unit_price: "12.50", tax_code: null, po_tax_code: null, amount: "13000.00", tax_amount: "0.00", total: "13000.00",
    },
  ],
  attachments: [], can_edit: true, can_reopen: false, can_cancel: false, can_request_exception: false, can_approve: false, history: [],
};

const openLine = {
  grn_line: 40, grn: { id: 4, number: "GRN26110101", date: "2026-11-01" }, po: { id: 9, label: "PO26110101", currency: "LKR" },
  item: { code: "M6-INSERT", name: "Brass insert M6", unit: "pcs" }, accepted_quantity: "1000.000", open_quantity: "1000.000",
  po_unit_price: "12.50", po_tax_code: null,
};

test("the clerk ticks the GRN line and types the invoice as printed", async () => {
  const calls = mockApi({
    "GET /api/v1/payees/": { body: [{ id: 2, code: "S0002", name: "Fasteners Lanka" }] },
    "GET /api/v1/divisions/": { body: [{ id: 2, code: "IM", name: "Moulding", division_type: "production" }] },
    "GET /api/v1/supplier-invoices/open-lines/?supplier=2&division=IM": { body: [openLine] },
    "POST /api/v1/supplier-invoices/": { status: 201, body: draft },
    "GET /api/v1/supplier-invoices/3/": { body: draft },
  });
  renderAt("/supplier-invoices/new", <SupplierInvoicePage />, "/supplier-invoices/:id");
  const form = await screen.findByRole("form", { name: "Supplier invoice" });
  fireEvent.change(within(form).getByRole("combobox", { name: "Supplier" }), { target: { value: "fast" } });
  fireEvent.mouseDown(await within(form).findByRole("option", { name: "S0002 Fasteners Lanka" }));
  const division = within(form).getByLabelText("Division");
  await waitFor(() => expect(within(division).getAllByRole("option")).toHaveLength(2));
  fireEvent.change(division, { target: { value: "IM" } });
  fireEvent.change(within(form).getByLabelText("Supplier's invoice no."), { target: { value: "INV-77" } });
  fireEvent.change(within(form).getByLabelText("Total printed on the invoice"), { target: { value: "13000" } });
  fireEvent.click(await within(form).findByRole("checkbox", { name: "Bill M6-INSERT of GRN26110101" }));
  fireEvent.change(within(form).getByLabelText("Price, M6-INSERT"), { target: { value: "13.00" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save the invoice" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/supplier-invoices/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/supplier-invoices/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    supplier: 2,
    division: "IM",
    invoice_no: "INV-77",
    stated_total: "13000",
    lines: [{ grn_line: 40, quantity: "1000.000", unit_price: "13.00", tax_code: null }],
  });
});

test("the Director sees the differences and approves the exception", async () => {
  const waiting: InvoiceDetail = {
    ...draft, status: "exception_requested", can_edit: false, can_approve: true, exception_reason: "Brass price rose",
    discrepancies: ["Line 1 (M6-INSERT, GRN26110101): price 13.00, PO price 12.50."],
  };
  const calls = mockApi({
    "GET /api/v1/supplier-invoices/3/": { body: waiting },
    "POST /api/v1/supplier-invoices/3/approve/": { body: { ...waiting, status: "posted", can_approve: false, journal: "JE26110004" } },
  });
  renderAt("/supplier-invoices/3", <SupplierInvoicePage />, "/supplier-invoices/:id");
  expect(await screen.findByText("Line 1 (M6-INSERT, GRN26110101): price 13.00, PO price 12.50.")).toBeInTheDocument();
  expect(within(screen.getByRole("table", { name: "Goods billed" })).getByText("13.00")).toHaveClass("form-error");
  fireEvent.click(screen.getByRole("button", { name: "Approve the exception" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/supplier-invoices/3/approve/", expect.objectContaining({ method: "POST" })));
  expect(await screen.findByText(/posted as JE26110004/)).toBeInTheDocument();
});
