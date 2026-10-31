import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { Customer } from "../api/customers";
import type { CostingLine, CostingPage, QuotationDetail } from "../api/quotations";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import QuotationCostingPage from "./QuotationCostingPage";
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
      id: 31, line_no: 1, description: "Cap, PP, white", drawing_no: "NP-77", drawing_rev: "B", quantity: "100.000", unit: "pcs",
      min_order_qty: null, unit_price: "2.35", tax_code: null, amount: "235.00", tax_amount: "0.00", total: "235.00",
      breaks: [{ quantity: "1000.000", unit_price: "2.10" }],
    },
  ],
  files: [],
  can_edit: true,
  can_see_costing: false,
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

// --- Costing (P15-04) --------------------------------------------------------------------

const costingPage: CostingPage = {
  quotation_id: 12, number: "QL26103101", revision: 0, division: "WS", currency: "LKR", exchange_rate: "1.000000",
  quote_date: "2026-10-31", can_edit: true,
  defaults: { overhead_pct: "15.00", margin_pct: "20.00", setup_rate: "1500.00" },
  materials: [{ id: 3, code: "EN8", name: "EN8 steel bar", form: "round_bar", density: "7.850", rate: "450.00" }],
  machines: [
    { id: 5, code: "C-LAT-01", name: "CNC lathe", rate: "3000.00" },
    { id: 6, code: "M-MIL-01", name: "Milling 1", rate: "2400.00" },
  ],
  lines: [
    {
      line_no: 1, description: "Shaft, EN8", drawing_no: "UL-2210", quantity: "10.000", unit: "pcs", unit_price: "3000.00",
      costing: null, results: null,
    },
  ],
};

const costedLine: CostingLine = {
  ...costingPage.lines[0],
  costing: {
    rates_date: "2026-10-31", material: { id: 3, code: "EN8", name: "EN8 steel bar" }, material_rate: "450.00", density: "7.850",
    form: "round_bar", size_a_mm: "50.00", size_b_mm: null, length_mm: "100.00", cutting_allowance_mm: "5.00",
    entered_weight_kg: null, weight_kg: "1.6184", setup_hours: "2.00", setup_rate: "1500.00", overhead_pct: "15.00",
    margin_pct: "20.00", notes: "",
    operations: [{ machine: { id: 5, code: "C-LAT-01", name: "CNC lathe" }, description: "Turn", minutes: "12.000", rate: "3000.00" }],
    extras: [{ description: "Transport", amount: "2000.00", per_order: true }],
    updated_by: "Sales", updated_at: "2026-10-31T10:00:00",
  },
  results: [
    {
      quantity: "10.000", material: "728.28", machining: "840.00", setup: "300.00", subcontract: "285.00", direct_cost: "2153.28",
      overhead: "322.99", cost: "2476.27", margin: "495.25", suggested_price_lkr: "2971.52", suggested_price: "2971.52",
      quoted_price: "3000.00", quoted_price_lkr: "3000.00", quoted_margin_pct: "21.15", below_cost: false,
    },
    {
      quantity: "50.000", material: "728.28", machining: "840.00", setup: "60.00", subcontract: "125.00", direct_cost: "1753.28",
      overhead: "262.99", cost: "2016.27", margin: "403.25", suggested_price_lkr: "2419.52", suggested_price: "2419.52",
      quoted_price: "1900.00", quoted_price_lkr: "1900.00", quoted_margin_pct: "-5.77", below_cost: true,
    },
  ],
};

test("the quotation links to its costing only for those who may see it", async () => {
  mockApi(formApi({ "GET /api/v1/quotations/12/": { body: { ...saved, can_see_costing: true } } }));
  renderAt("/quotations/12", <QuotationPage />, "/quotations/:id");
  const link = await screen.findByRole("link", { name: "Costing" });
  expect(link).toHaveAttribute("href", "/quotations/12/costing");
});

test("an executive who cannot see the costing gets no link", async () => {
  mockApi(formApi({ "GET /api/v1/quotations/12/": { body: saved } }));
  renderAt("/quotations/12", <QuotationPage />, "/quotations/:id");
  await screen.findByRole("form", { name: "Quotation details" });
  expect(screen.queryByRole("link", { name: "Costing" })).not.toBeInTheDocument();
});

test("saving the draft sends each line's id so its costing is kept", async () => {
  const calls = mockApi(formApi({ "GET /api/v1/quotations/12/": { body: saved }, "PUT /api/v1/quotations/12/": { body: saved } }));
  renderAt("/quotations/12", <QuotationPage />, "/quotations/:id");
  const form = await screen.findByRole("form", { name: "Quotation details" });
  fireEvent.click(within(form).getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/quotations/12/", expect.objectContaining({ method: "PUT" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/quotations/12/" && i?.method === "PUT")!;
  expect(JSON.parse(String(init!.body)).lines[0].id).toBe(31);
});

test("the creator costs a line: material by size, operations and subcontract", async () => {
  const calls = mockApi({
    "GET /api/v1/quotations/12/costing/": { body: costingPage },
    "PUT /api/v1/quotations/12/costing/1/": { body: { ...costingPage, lines: [costedLine] } },
  });
  renderAt("/quotations/12/costing", <QuotationCostingPage />, "/quotations/:id/costing");
  const form = await screen.findByRole("form", { name: "Costing of line 1" });
  expect(screen.getByText(/never shown to the customer/)).toBeInTheDocument();

  fireEvent.change(within(form).getByLabelText("Material"), { target: { value: "3" } });
  fireEvent.change(within(form).getByLabelText("Diameter (mm)"), { target: { value: "50" } });
  fireEvent.change(within(form).getByLabelText("Length per piece (mm)"), { target: { value: "100" } });
  fireEvent.change(within(form).getByLabelText("Cutting allowance (mm)"), { target: { value: "5" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add an operation" }));
  fireEvent.change(within(form).getByLabelText("Machine, operation 1"), { target: { value: "5" } });
  fireEvent.change(within(form).getByLabelText("Minutes per piece, operation 1"), { target: { value: "12" } });
  fireEvent.change(within(form).getByLabelText("Setup hours (whole order)"), { target: { value: "2" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add a subcontract cost" }));
  fireEvent.change(within(form).getByLabelText("Subcontract cost 1"), { target: { value: "Transport" } });
  fireEvent.change(within(form).getByLabelText("Amount, subcontract cost 1"), { target: { value: "2000" } });
  fireEvent.click(within(form).getByLabelText("Whole order"));
  expect(within(form).getByLabelText("Margin %")).toHaveAttribute("placeholder", "20.00");
  fireEvent.click(within(form).getByRole("button", { name: "Save costing" }));

  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/quotations/12/costing/1/", expect.objectContaining({ method: "PUT" })),
  );
  const [, init] = calls.mock.calls.find(([url]) => url === "/api/v1/quotations/12/costing/1/")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    material: 3,
    size_a_mm: "50",
    length_mm: "100",
    cutting_allowance_mm: "5",
    weight_kg: null,
    setup_hours: "2",
    margin_pct: null, // the division's default
    operations: [{ machine: 5, minutes: "12" }],
    extras: [{ description: "Transport", amount: "2000", per_order: true }],
  });

  const table = await screen.findByRole("table", { name: "Price build-up, line 1" });
  expect(within(table).getByRole("columnheader", { name: "10 pcs" })).toBeInTheDocument();
  const suggested = within(table).getByRole("row", { name: /Suggested price/ });
  expect(suggested).toHaveTextContent("2,971.52");
  expect(suggested).toHaveTextContent("2,419.52");
  expect(within(table).getByRole("row", { name: /Margin of the price quoted/ })).toHaveTextContent("21.15%");
  expect(screen.getByText(/below cost for 50/)).toBeInTheDocument();
});

test("those who only look see the costing without changing it", async () => {
  mockApi({ "GET /api/v1/quotations/12/costing/": { body: { ...costingPage, can_edit: false, lines: [costedLine] } } });
  renderAt("/quotations/12/costing", <QuotationCostingPage />, "/quotations/:id/costing");
  const section = await screen.findByRole("region", { name: "Costing, line 1" });
  expect(within(section).getByText(/EN8 EN8 steel bar: 1.6184 kg per piece/)).toBeInTheDocument();
  expect(within(section).getByText(/C-LAT-01/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save costing" })).not.toBeInTheDocument();
});
