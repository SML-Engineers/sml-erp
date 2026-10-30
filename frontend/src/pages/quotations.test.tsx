import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { Customer } from "../api/customers";
import type { QuotationDetail } from "../api/quotations";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import QuotationPage from "./QuotationPage";
import QuotationsPage from "./QuotationsPage";

const executive: CurrentUser = {
  ...sampleUser,
  access: { areas: { sales: ["enter", "view"] }, actions: [], divisions: "all" },
};

const viewer: CurrentUser = {
  ...sampleUser,
  access: { areas: { sales: ["view"] }, actions: [], divisions: "all" },
};

const nordic: Customer = {
  id: 4, code: "C0004", name: "Nordic Plast AB", billing_address: "", delivery_address: "", phone: "", email: "",
  vat_no: "", tin: "", currency: "EUR", payment_terms_days: 60, credit_limit: null, is_export: true, country: "Sweden",
  incoterm: "FOB", port_of_destination: "Gothenburg", notes: "", is_active: true,
  main_contact: { id: 7, name: "Lars", position: "", phone: "", email: "", is_main: true, is_active: true }, in_use: false,
};

const saved: QuotationDetail = {
  id: 12, number: "QL26103101", revision: 0, status: "draft", quote_date: "2026-10-31", valid_until: "2026-11-07",
  division: "IM", customer: { id: 4, code: "C0004", name: "Nordic Plast AB" }, enquiry_ref: "", currency: "EUR",
  total_amount: "235.00", total_lkr: "76469.00", created_by: "Sales", contact: { id: 7, name: "Lars", email: "" },
  exchange_rate: "325.400000", rate_date: "2026-10-29", payment_terms: "60 days", delivery_lead_time: "", incoterm: "FOB",
  notes: "", subtotal: "235.00", tax_total: "0.00", created_by_id: 1, created_at: "",
  lines: [
    {
      line_no: 1, description: "Cap, PP, white", drawing_no: "NP-77", drawing_rev: "B", quantity: "100.000", unit: "pcs",
      min_order_qty: null, unit_price: "2.35", tax_code: null, amount: "235.00", tax_amount: "0.00", total: "235.00",
      breaks: [{ quantity: "1000.000", unit_price: "2.10" }],
    },
  ],
  files: [],
  can_edit: true,
};

const formApi = (extra: Parameters<typeof mockApi>[0] = {}) => ({
  "GET /api/v1/customers/": { body: [nordic] },
  "GET /api/v1/customers/4/contacts/": { body: [nordic.main_contact] },
  "GET /api/v1/divisions/": {
    body: [
      { id: 1, code: "HO", name: "Head Office", division_type: "shared" },
      { id: 2, code: "IM", name: "Moulding", division_type: "production" },
    ],
  },
  "GET /api/v1/currencies/": {
    body: [
      { code: "LKR", name: "Sri Lankan rupee", symbol: "Rs", decimal_places: 2 },
      { code: "EUR", name: "Euro", symbol: "€", decimal_places: 2 },
    ],
  },
  "GET /api/v1/taxes/": { body: { components: [], codes: [] } },
  ...extra,
});

test("a quotation for an export customer starts from the customer's terms", async () => {
  const calls = mockApi(
    formApi({
      "POST /api/v1/quotations/": { status: 201, body: saved },
      "GET /api/v1/quotations/12/": { body: saved },
    }),
  );
  renderAt("/quotations/new", <QuotationPage />, "/quotations/:id");
  const form = await screen.findByRole("form", { name: "Quotation details" });

  fireEvent.change(within(form).getByRole("combobox", { name: "Customer" }), { target: { value: "nordic" } });
  fireEvent.mouseDown(await within(form).findByRole("option", { name: "C0004 Nordic Plast AB" }));
  // Only production divisions can be chosen.
  await within(form).findByRole("option", { name: "IM Moulding" });
  expect(within(form).queryByRole("option", { name: "HO Head Office" })).not.toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Division"), { target: { value: "IM" } });
  await waitFor(() => expect(within(form).getByLabelText("Currency")).toHaveValue("EUR"));
  expect(within(form).getByLabelText("Payment terms")).toHaveValue("60 days");

  fireEvent.change(within(form).getByLabelText("Description, line 1"), { target: { value: "Cap, PP, white" } });
  fireEvent.change(within(form).getByLabelText("Quantity, line 1"), { target: { value: "100" } });
  fireEvent.change(within(form).getByLabelText("Unit price, line 1"), { target: { value: "2.35" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add a quantity break" }));
  const breaks = within(form).getByRole("group", { name: "Quantity breaks, line 1" });
  fireEvent.change(within(breaks).getByLabelText("Quantity"), { target: { value: "1000" } });
  fireEvent.change(within(breaks).getByLabelText("Unit price"), { target: { value: "2.10" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save draft" }));

  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/quotations/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/quotations/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    customer: 4,
    contact: 7,
    division: "IM",
    currency: "EUR",
    incoterm: "FOB",
    lines: [{ description: "Cap, PP, white", quantity: "100", unit_price: "2.35", breaks: [{ quantity: "1000", unit_price: "2.10" }] }],
  });
  expect(await screen.findByRole("heading", { name: "Quotation QL26103101" })).toBeInTheDocument();
  expect(screen.getByText(/1 EUR = LKR 325.400000/)).toBeInTheDocument();
});

test("a quotation the user cannot change is shown read-only", async () => {
  mockApi(formApi({ "GET /api/v1/quotations/12/": { body: { ...saved, status: "sent", can_edit: false } } }));
  renderAt("/quotations/12", <QuotationPage />, "/quotations/:id");
  const details = await screen.findByRole("region", { name: "Quotation details" });
  expect(within(details).getByText("Cap, PP, white")).toBeInTheDocument();
  expect(within(details).getByText(/1,000 @ 2.10/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
});

test("the list links to each quotation; only sales staff who enter see New quotation", async () => {
  mockApi({ "GET /api/v1/quotations/": { body: [saved] } });
  const { unmount } = renderAt("/quotations", <QuotationsPage me={executive} />);
  const table = await screen.findByRole("table", { name: "Quotations" });
  expect(within(table).getByRole("link", { name: "QL26103101" })).toHaveAttribute("href", "/quotations/12");
  expect(within(table).getByText("EUR 235.00")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "New quotation" })).toBeInTheDocument();
  unmount();
  renderAt("/quotations", <QuotationsPage me={viewer} />);
  await screen.findByRole("table", { name: "Quotations" });
  expect(screen.queryByRole("link", { name: "New quotation" })).not.toBeInTheDocument();
});
