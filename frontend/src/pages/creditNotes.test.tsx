import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CNDetail, InvoiceForCredit } from "../api/creditNotes";
import { mockApi, renderAt } from "../test-utils";
import CreditNotePage from "./CreditNotePage";

const line = {
  id: 21, line_no: 1, product_code: "DS-114", description: "Drive shaft, EN8", unit: "pcs", quantity: "50.000", net: "115750.00",
  tax_code: "VAT-SSCL", left_amount: "115750.00", left_quantity: "50.000", credit_amount: null, credit_quantity: null, credit_tax: null,
};

const invoice: InvoiceForCredit = {
  id: 4, number: "26NOV_W1_01", invoice_date: "2026-11-03", customer: "Lanka Tiles PLC", total_amount: "139487.43", lines: [line],
};

const draft: CNDetail = {
  id: 6, number: "", status: "draft", status_label: "Draft", kind: "return", credit_date: "2026-11-03",
  invoice: { id: 4, number: "26NOV_W1_01" }, customer: { id: 1, name: "Lanka Tiles PLC" }, division: "WS", total_amount: "13987.69",
  created_by: "Nimal", reason: "5 shafts returned", invoice_date: "2026-11-03", subtotal: "11575.00", tax_total: "2412.69",
  amount_in_words: "", lines: [{ ...line, credit_amount: "11575.00", credit_quantity: "5.000", credit_tax: "2412.69" }],
  taxes: [
    { label: "SSCL", rate: "2.125", on_tax: false, amount: "245.97" },
    { label: "VAT", rate: "18", on_tax: true, amount: "2127.75" },
  ],
  journal_entry: null, can_edit: true, can_approve: false, approval: null,
};

test("a credit note for returned goods is made from the invoice", async () => {
  const calls = mockApi({
    "GET /api/v1/credit-notes/invoice/4/": { body: invoice },
    "POST /api/v1/credit-notes/": { status: 201, body: draft },
    "GET /api/v1/credit-notes/6/": { body: draft },
  });
  renderAt("/credit-notes/new?invoice=4", <CreditNotePage />, "/credit-notes/:id");
  const form = await screen.findByRole("form", { name: "Credit note details" });
  fireEvent.change(within(form).getByLabelText("Why"), { target: { value: "return" } });
  fireEvent.change(within(form).getByLabelText("Reason (printed on the note)"), { target: { value: "5 shafts returned" } });
  fireEvent.change(within(form).getByLabelText("Quantity returned, line 1"), { target: { value: "5" } });
  fireEvent.change(within(form).getByLabelText("Amount credited, line 1"), { target: { value: "11575.00" } });
  fireEvent.click(within(form).getByRole("button", { name: "Make the draft credit note" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/credit-notes/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/credit-notes/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    invoice: 4,
    kind: "return",
    reason: "5 shafts returned",
    lines: [{ invoice_line: 21, amount: "11575.00", quantity: "5" }],
  });
});

test("the Director approves and the note is numbered", async () => {
  let current: CNDetail = { ...draft, status: "awaiting_approval", can_edit: false, can_approve: true };
  const approved: CNDetail = { ...current, status: "approved", number: "CN26110301", can_approve: false, journal_entry: { id: 90, number: "JV26110050" } };
  const calls = mockApi({
    "GET /api/v1/credit-notes/6/": () => ({ body: current }),
    "POST /api/v1/credit-notes/6/approve/": () => {
      current = approved;
      return { body: approved };
    },
  });
  renderAt("/credit-notes/6", <CreditNotePage />, "/credit-notes/:id");
  fireEvent.click(await screen.findByRole("button", { name: "Approve and post" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/credit-notes/6/approve/", expect.objectContaining({ method: "POST" })));
  expect(await screen.findByRole("heading", { name: "Credit note CN26110301" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Credit note PDF" })).toHaveAttribute("href", "/api/v1/credit-notes/6/pdf/");
});
