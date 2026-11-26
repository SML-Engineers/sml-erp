import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { InvoiceDetail } from "../api/supplierInvoices";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import SupplierInvoicePage from "./SupplierInvoicePage";
import SupplierInvoicesPage from "./SupplierInvoicesPage";

const draft: InvoiceDetail = {
  id: 3,
  number: "SI26110101",
  invoice_no: "INV-77",
  invoice_date: "2026-11-01",
  due_date: "2026-12-16",
  status: "draft",
  division: "IM",
  supplier: { id: 2, code: "S0002", name: "Fasteners Lanka" },
  currency: "LKR",
  total_amount: "13000.00",
  total_lkr: "0.00",
  created_by: "Clerk",
  stated_total: "13000.00",
  subtotal: "13000.00",
  tax_total: "0.00",
  discrepancies: [],
  notes: "",
  exception_reason: "",
  cancel_reason: "",
  journal: null,
  posted_at: null,
  lines: [
    {
      line_no: 1,
      grn_line: 40,
      grn: { id: 4, number: "GRN26110101" },
      po: { id: 9, label: "PO26110101" },
      item: { code: "M6-INSERT", name: "Brass insert M6", unit: "pcs" },
      quantity: "1000.000",
      accepted_quantity: "1000.000",
      unit_price: "13.00",
      po_unit_price: "12.50",
      tax_code: null,
      po_tax_code: null,
      amount: "13000.00",
      tax_amount: "0.00",
      total: "13000.00",
      order: "",
    },
  ],
  attachments: [],
  can_edit: true,
  can_reopen: false,
  can_cancel: false,
  can_request_exception: false,
  can_approve: false,
  history: [],
};

const openLine = {
  grn_line: 40,
  grn: { id: 4, number: "GRN26110101", date: "2026-11-01" },
  po: { id: 9, label: "PO26110101", currency: "LKR" },
  item: { code: "M6-INSERT", name: "Brass insert M6", unit: "pcs" },
  accepted_quantity: "1000.000",
  open_quantity: "1000.000",
  po_unit_price: "12.50",
  po_tax_code: null,
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
  fireEvent.change(within(form).getByLabelText("Job or production order for M6-INSERT"), { target: { value: "jo26110001" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save the invoice" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/supplier-invoices/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/supplier-invoices/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    supplier: 2,
    division: "IM",
    invoice_no: "INV-77",
    stated_total: "13000",
    lines: [{ grn_line: 40, quantity: "1000.000", unit_price: "13.00", tax_code: null, order: "JO26110001" }],
  });
});

test("the Director sees the differences and approves the exception", async () => {
  const waiting: InvoiceDetail = {
    ...draft,
    status: "exception_requested",
    can_edit: false,
    can_approve: true,
    exception_reason: "Brass price rose",
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
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/supplier-invoices/3/approve/", expect.objectContaining({ method: "POST" })),
  );
  await waitFor(() => expect(document.body).toHaveTextContent(/posted as JE26110004/));
});

// Owner, 16 Nov 2026: clear statuses in the list.
test("the list says who an exception waits for, who decided and who cancelled", async () => {
  const ruwan = "Ruwan Jayasinghe";
  const row = (id: number, extra: Partial<InvoiceDetail>) => ({
    ...draft,
    id,
    number: `SI2611000${id}`,
    created_by: "Kumari Dias",
    ...extra,
  });
  mockApi({
    "GET /api/v1/supplier-invoices/": {
      body: [
        row(1, { status: "draft", people: null }),
        row(2, { status: "exception_requested", people: { waiting: { person: ruwan, role: "Director" }, last: null } }),
        row(3, { status: "held", people: { waiting: null, last: { action: "return", by: ruwan } } }),
        row(4, { status: "posted", people: { waiting: null, last: { action: "approve", by: ruwan } } }),
        row(5, { status: "cancelled", cancelled_by: "Kumari Dias", people: null }),
      ],
    },
  });
  renderAt("/supplier-invoices", <SupplierInvoicesPage me={sampleUser} />);
  const table = await screen.findByRole("table", { name: "Supplier invoices" });
  for (const text of [
    "Draft of Kumari",
    "Exception, waiting for Ruwan (Director)",
    "Held: exception returned by Ruwan",
    "Matched and posted, exception approved by Ruwan",
    "Cancelled by Kumari",
  ])
    expect(within(table).getByText(text)).toBeInTheDocument();
});

test("asks before deleting a draft invoice, and before matching and posting (testing T49)", async () => {
  const calls = mockApi({
    "GET /api/v1/supplier-invoices/3/": { body: draft },
    "DELETE /api/v1/supplier-invoices/3/": { status: 204, body: null },
  });
  renderAt("/supplier-invoices/3", <SupplierInvoicePage />, "/supplier-invoices/:id", { ask: true });
  fireEvent.click(await screen.findByRole("button", { name: "Delete the draft" }));
  const dialog = await screen.findByRole("alertdialog", { name: "Delete the draft of invoice INV-77 of Fasteners Lanka (LKR 13,000.00)?" });
  fireEvent.click(within(dialog).getByRole("button", { name: "No, go back" }));
  expect(calls).not.toHaveBeenCalledWith("/api/v1/supplier-invoices/3/", expect.objectContaining({ method: "DELETE" }));

  fireEvent.click(screen.getByRole("button", { name: /Match and post/ }));
  const match = await screen.findByRole("alertdialog", { name: "Match and post invoice INV-77 of Fasteners Lanka for LKR 13,000.00?" });
  fireEvent.click(within(match).getByRole("button", { name: "No, go back" }));
  expect(calls).not.toHaveBeenCalledWith("/api/v1/supplier-invoices/3/match/", expect.anything());
});

// Owner, 22 Nov 2026: the supplier's credit note is matched to our debit note later.
const posted: InvoiceDetail = {
  ...draft,
  status: "posted",
  can_edit: false,
  journal: "JE26110004",
  debit_notes: [
    { id: 7, number: "DN26112501", return: { id: 5, number: "RTN26112501" }, quantity: "10.000", total_lkr: "1000.00", credit_note: null },
  ],
  can_record_credit_note: true,
  can_remove_credit_note: false,
};

test("the clerk records the supplier's credit note against our debit note", async () => {
  const recorded = {
    ...posted,
    debit_notes: [
      {
        ...posted.debit_notes![0],
        credit_note: {
          number: "SCN-0055",
          date: "2026-11-26",
          file_name: "cn.pdf",
          recorded_by: "Nimal",
          recorded_at: "2026-11-26T04:00:00Z",
        },
      },
    ],
  };
  const calls = mockApi({
    "GET /api/v1/supplier-invoices/3/": { body: posted },
    "POST /api/v1/supplier-invoices/3/debit-notes/7/credit-note/": { status: 201, body: recorded },
  });
  renderAt("/supplier-invoices/3", <SupplierInvoicePage />, "/supplier-invoices/:id");
  const panel = await screen.findByRole("region", { name: "Debit notes" });
  expect(within(panel).getByText("Waiting for the supplier's credit note.")).toBeInTheDocument();
  const form = within(panel).getByRole("form", { name: "Record the supplier's credit note for DN26112501" });
  fireEvent.change(within(form).getByLabelText("Supplier's credit note no."), { target: { value: "SCN-0055" } });
  fireEvent.change(within(form).getByLabelText("Its date"), { target: { value: "2026-11-26" } });
  const pdf = new File(["%PDF-1.4"], "cn.pdf", { type: "application/pdf" });
  fireEvent.change(within(form).getByLabelText("Scan (PDF, JPG or PNG)"), { target: { files: [pdf] } });
  fireEvent.click(within(form).getByRole("button", { name: "Record credit note" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/supplier-invoices/3/debit-notes/7/credit-note/",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  const sent = calls.mock.calls.find(([u]) => u === "/api/v1/supplier-invoices/3/debit-notes/7/credit-note/")![1]!.body as FormData;
  expect([sent.get("number"), sent.get("date"), (sent.get("file") as File).name]).toEqual(["SCN-0055", "2026-11-26", "cn.pdf"]);
  expect(await within(panel).findByText(/Supplier's credit note SCN-0055 of 2026-11-26, recorded by Nimal/)).toBeInTheDocument();
  expect(within(panel).getByRole("link", { name: "cn.pdf" })).toHaveAttribute(
    "href",
    "/api/v1/supplier-invoices/3/debit-notes/7/credit-note/",
  );
});

test("the Accountant is asked before removing a recorded credit note", async () => {
  const withCredit: InvoiceDetail = {
    ...posted,
    can_record_credit_note: true,
    can_remove_credit_note: true,
    debit_notes: [
      {
        ...posted.debit_notes![0],
        credit_note: {
          number: "SCN-0055",
          date: "2026-11-26",
          file_name: "cn.pdf",
          recorded_by: "Nimal",
          recorded_at: "2026-11-26T04:00:00Z",
        },
      },
    ],
  };
  const calls = mockApi({
    "GET /api/v1/supplier-invoices/3/": { body: withCredit },
    "POST /api/v1/supplier-invoices/3/debit-notes/7/credit-note/remove/": { body: posted },
  });
  renderAt("/supplier-invoices/3", <SupplierInvoicePage />, "/supplier-invoices/:id", { ask: true });
  const form = await screen.findByRole("form", { name: "Remove credit note SCN-0055" });
  expect(screen.queryByRole("form", { name: /Record the supplier's credit note/ })).not.toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "wrong number" } });
  fireEvent.click(within(form).getByRole("button", { name: "Remove credit note" }));
  const question = "Remove the supplier's credit note SCN-0055 from debit note DN26112501? It can then be recorded again.";
  fireEvent.click(within(await screen.findByRole("alertdialog", { name: question })).getByRole("button", { name: "No, go back" }));
  expect(calls).not.toHaveBeenCalledWith(expect.stringContaining("/remove/"), expect.anything());
  fireEvent.click(within(form).getByRole("button", { name: "Remove credit note" }));
  fireEvent.click(within(await screen.findByRole("alertdialog", { name: question })).getByRole("button", { name: "Remove credit note" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/supplier-invoices/3/debit-notes/7/credit-note/remove/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "wrong number" }) }),
    ),
  );
});

test("someone who may not record credit notes only sees that one is awaited", async () => {
  mockApi({ "GET /api/v1/supplier-invoices/3/": { body: { ...posted, can_record_credit_note: false } } });
  renderAt("/supplier-invoices/3", <SupplierInvoicePage />, "/supplier-invoices/:id");
  expect(await screen.findByText("Waiting for the supplier's credit note.")).toBeInTheDocument();
  expect(screen.queryByRole("form", { name: /Record the supplier's credit note/ })).not.toBeInTheDocument();
});

// Testing T39 (21 Nov 2026): "posted as JV26110022" could not be opened from the invoice.
test("the journal entry an invoice was posted as opens from it, for those who can see the journal", async () => {
  const done = { ...posted, debit_notes: [], journal: "JV26110022" };
  mockApi({ "GET /api/v1/supplier-invoices/3/": { body: done } });
  const accountant = { ...sampleUser, access: { areas: { accounting: ["view" as const] }, actions: [], divisions: "all" as const } };
  const first = renderAt("/supplier-invoices/3", <SupplierInvoicePage />, "/supplier-invoices/:id", { me: accountant });
  expect(await screen.findByRole("link", { name: "JV26110022" })).toHaveAttribute("href", "/journal?q=JV26110022");
  first.unmount();

  renderAt("/supplier-invoices/3", <SupplierInvoicePage />, "/supplier-invoices/:id", { me: sampleUser });
  expect(await screen.findByText("JV26110022")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "JV26110022" })).not.toBeInTheDocument();
});
