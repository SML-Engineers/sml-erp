import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { InvoiceDetail } from "../api/taxInvoices";
import { mockApi, renderAt } from "../test-utils";
import TaxInvoicePage from "./TaxInvoicePage";
import TaxInvoicesPage from "./TaxInvoicesPage";

const draft: InvoiceDetail = {
  id: 4, number: "", status: "draft", invoice_date: "2026-11-03", due_date: "2026-12-03", division: "WS",
  customer: { id: 1, name: "Lanka Tiles PLC" }, order: { id: 3, number: "SO26110301" }, customer_po: "LT/PO/1201",
  total_amount: "139487.43", created_by: "Nimal", supply_date: "2026-11-03", place_of_supply: "Factory, Ranala",
  terms: "Due on receipt", notes: "", customer_tin: "114455667", subtotal: "115750.00", discount_total: "0.00",
  tax_total: "23737.43", amount_in_words: "Rupees One Hundred Thirty Nine Thousand Four Hundred Eighty Seven and Cents Forty Three Only",
  lines: [
    {
      line_no: 1, delivery_note: { id: 8, number: "DN26110301" }, product_code: "DS-114", description: "Drive shaft, EN8",
      po_no: "LT/PO/1201", unit: "pcs", quantity: "50.000", rate: "2315.00", amount: "115750.00", discount: "0.00",
      tax_code: "VAT-SSCL", tax_amount: "23737.43", account: { id: 40, number: "4010", name: "Machined parts" },
    },
  ],
  taxes: [
    { label: "SSCL", rate: "2.125", on_tax: false, amount: "2459.69" },
    { label: "VAT", rate: "18", on_tax: true, amount: "21277.74" },
  ],
  journal_entry: null, issued_by: null, issued_at: null, can_edit: true, can_issue: true, can_email: false, emails: [],
};

test("delivered notes are ticked and a draft invoice is prepared", async () => {
  const calls = mockApi({
    "GET /api/v1/tax-invoices/": { body: [] },
    "GET /api/v1/tax-invoices/orders/": {
      body: [
        {
          id: 3, number: "SO26110301", division: "WS", customer: "Lanka Tiles PLC", customer_po: "LT/PO/1201", currency: "LKR",
          delivery_notes: [
            { id: 8, number: "DN26110301", delivery_date: "2026-11-03" },
            { id: 9, number: "DN26110302", delivery_date: "2026-11-03" },
          ],
        },
      ],
    },
    "POST /api/v1/tax-invoices/": { status: 201, body: draft },
  });
  renderAt("/tax-invoices", <TaxInvoicesPage />);
  const waiting = await screen.findByRole("region", { name: "Delivered, not yet invoiced" });
  fireEvent.click(within(waiting).getByLabelText(/DN26110302/));
  fireEvent.click(within(waiting).getByRole("button", { name: "Prepare the invoice" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/tax-invoices/", expect.objectContaining({ body: JSON.stringify({ order: 3, delivery_notes: [8] }) })),
  );
});

test("the Accountant issues the draft and it gets its number", async () => {
  let current = draft;
  const issued: InvoiceDetail = {
    ...draft, number: "26NOV_W1_01", status: "issued", can_edit: false, can_issue: false, can_email: true,
    journal_entry: { id: 70, number: "JV26110040" }, issued_by: "Kumari Silva",
  };
  const calls = mockApi({
    "GET /api/v1/tax-invoices/4/": () => ({ body: current }),
    "POST /api/v1/tax-invoices/4/issue/": () => {
      current = issued;
      return { body: issued };
    },
  });
  renderAt("/tax-invoices/4", <TaxInvoicePage />, "/tax-invoices/:id");
  expect(await screen.findByRole("heading", { name: "Draft 4" })).toBeInTheDocument();
  const lines = screen.getByRole("table", { name: "Invoice lines" });
  expect(within(lines).getByText("SSCL 2.125%")).toBeInTheDocument();
  expect(within(lines).getByText("139,487.43")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Issue the tax invoice" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/tax-invoices/4/issue/", expect.objectContaining({ method: "POST" })));
  expect(await screen.findByRole("heading", { name: "Tax invoice 26NOV_W1_01" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "JV26110040" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Tax invoice PDF" })).toHaveAttribute("href", "/api/v1/tax-invoices/4/pdf/");
});

test("the invoice's history shows the customer viewed it, and a OnePay link is recorded", async () => {
  const issued: InvoiceDetail = {
    ...draft, number: "26NOV_W1_01", status: "issued", can_edit: false, can_issue: false, can_email: true,
    tracking: {
      state: "overdue", open: "139487.43", viewed: true,
      events: [
        { at: "2026-11-03T10:00:00", kind: "emailed", text: "Emailed to ap@lankatiles.lk", url: "" },
        { at: "2026-11-04T09:00:00", kind: "viewed", text: "Viewed by the customer (1 time)", url: "" },
      ],
    },
  };
  const calls = mockApi({
    "GET /api/v1/tax-invoices/4/": { body: issued },
    "POST /api/v1/tax-invoices/4/card-links/": { body: issued },
  });
  renderAt("/tax-invoices/4", <TaxInvoicePage />, "/tax-invoices/:id");
  const history = await screen.findByRole("list", { name: "What happened" });
  expect(history).toHaveTextContent("Viewed by the customer (1 time)");
  expect(screen.getByRole("heading", { name: /Tracking · Overdue/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Record a OnePay link sent" }));
  const form = screen.getByRole("form", { name: "Record a OnePay link sent" });
  fireEvent.change(within(form).getByLabelText("OnePay link"), { target: { value: "https://onepay.lk/p/AB12" } });
  fireEvent.change(within(form).getByLabelText(/^Amount/), { target: { value: "139487.43" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/tax-invoices/4/card-links/", expect.objectContaining({ method: "POST" })),
  );
});
