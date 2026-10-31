import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { Customer } from "../api/customers";
import type { CostingLine, CostingPage, CostingResult, QuotationDetail } from "../api/quotations";
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
  notes: "", discount_pct: "0.00", discount_total: "0.00", subtotal: "235.00", tax_total: "0.00", created_by_id: 1, created_at: "",
  lines: [
    {
      id: 31, line_no: 1, description: "Cap, PP, white", drawing_no: "NP-77", drawing_rev: "B", quantity: "100.000", unit: "pcs",
      min_order_qty: null, unit_price: "2.35", is_tooling: false, tax_code: null, amount: "235.00", discount: "0.00", tax_amount: "0.00", total: "235.00",
      breaks: [{ quantity: "1000.000", unit_price: "2.10" }],
    },
  ],
  files: [],
  can_edit: true,
  can_see_costing: false,
  approved_at: null,
  sent_at: null,
  outcome: null,
  is_final: false,
  can_submit: true,
  can_approve: false,
  can_mark_sent: false,
  can_record_outcome: false,
  can_revise: false,
  can_email: false,
  can_make_proforma: false,
  proformas: [],
  emails: [],
  approval: null,
  revisions: [{ id: 12, revision: 0, status: "draft", quote_date: "2026-10-31" }],
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
  quote_date: "2026-10-31", can_edit: true, default_method: "machining",
  defaults: { overhead_pct: "15.00", margin_pct: "20.00", setup_rate: "1500.00" },
  materials: [{ id: 3, code: "EN8", name: "EN8 steel bar", kind: "metal", form: "round_bar", density: "7.850", rate: "450.00" }],
  machines: [
    { id: 5, code: "C-LAT-01", name: "CNC lathe", rate: "3000.00" },
    { id: 6, code: "M-MIL-01", name: "Milling 1", rate: "2400.00" },
  ],
  lines: [
    {
      line_no: 1, description: "Shaft, EN8", drawing_no: "UL-2210", quantity: "10.000", unit: "pcs", unit_price: "3000.00",
      is_tooling: false, costing: null, results: null,
    },
  ],
};

const noMoulding = {
  method: "machining" as const, masterbatch: null, masterbatch_rate: null, masterbatch_pct: "0.00", part_weight_g: null,
  runner_weight_g: null, cavities: null, machine: null, machine_rate: null, cycle_time_s: null, reject_pct: "0.00",
  packing_amount: "0.00", packing_per: "piece" as const, pcs_per_carton: null, tooling: "none" as const, tooling_cost: "0.00",
  tooling_qty: null,
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
    ...noMoulding,
    updated_by: "Sales", updated_at: "2026-10-31T10:00:00",
  },
  results: [
    {
      quantity: "10.000", material: "728.28", machining: "840.00", hours_per_1000: null, rejects: "0.00", packing: "0.00", tooling: "0.00", setup: "300.00", subcontract: "285.00", direct_cost: "2153.28",
      overhead: "322.99", cost: "2476.27", margin: "495.25", suggested_price_lkr: "2971.52", suggested_price: "2971.52",
      quoted_price: "3000.00", quoted_price_lkr: "3000.00", quoted_margin_pct: "21.15", below_cost: false,
    },
    {
      quantity: "50.000", material: "728.28", machining: "840.00", hours_per_1000: null, rejects: "0.00", packing: "0.00", tooling: "0.00", setup: "60.00", subcontract: "125.00", direct_cost: "1753.28",
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

const mouldingPage: CostingPage = {
  ...costingPage,
  division: "IM",
  default_method: "moulding",
  materials: [
    { id: 8, code: "PP-H110", name: "Polypropylene", kind: "resin", form: "granules", density: null, rate: "420.00" },
    { id: 9, code: "MB-WHITE", name: "White masterbatch", kind: "masterbatch", form: "granules", density: null, rate: "1800.00" },
  ],
  machines: [{ id: 11, code: "IM-250", name: "250 t press", rate: "2880.00" }],
  lines: [
    { line_no: 1, description: "Cap, PP, white", drawing_no: "", quantity: "10000.000", unit: "pcs", unit_price: "18.00", is_tooling: false, costing: null, results: null },
  ],
};

test("a moulded line is costed from resin, cavities, cycle time, packing and the mould", async () => {
  const mouldResult: CostingResult = {
    quantity: "10000.000", material: "5.47", machining: "4.00", hours_per_1000: "1.39", rejects: "0.28", setup: "0.36", packing: "0.24",
    subcontract: "0.00", direct_cost: "10.35", overhead: "1.04", cost: "11.39", margin: "2.85", tooling: "3.00",
    suggested_price_lkr: "17.24", suggested_price: "17.24", quoted_price: "18.00", quoted_price_lkr: "18.00", quoted_margin_pct: "31.69",
    below_cost: false,
  };
  const calls = mockApi({
    "GET /api/v1/quotations/12/costing/": { body: mouldingPage },
    "PUT /api/v1/quotations/12/costing/1/": {
      body: {
        ...mouldingPage,
        lines: [
          {
            ...mouldingPage.lines[0],
            costing: { ...costedLine.costing!, ...noMoulding, method: "moulding", material: { id: 8, code: "PP-H110", name: "Polypropylene" }, tooling: "amortised", tooling_cost: "900000.00", tooling_qty: "300000.000" },
            results: [mouldResult],
          },
        ],
      },
    },
  });
  renderAt("/quotations/12/costing", <QuotationCostingPage />, "/quotations/:id/costing");
  const form = await screen.findByRole("form", { name: "Costing of line 1" });
  expect(within(form).getByLabelText("Costing for")).toHaveValue("moulding"); // IM moulds
  fireEvent.change(within(form).getByLabelText("Resin"), { target: { value: "8" } });
  expect(within(within(form).getByLabelText("Resin")).queryByRole("option", { name: /MB-WHITE/ })).not.toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Part weight (g)"), { target: { value: "10" } });
  fireEvent.change(within(form).getByLabelText("Runner weight per shot (g)"), { target: { value: "8" } });
  fireEvent.change(within(form).getByLabelText("Cavities"), { target: { value: "4" } });
  fireEvent.change(within(form).getByLabelText("Masterbatch"), { target: { value: "9" } });
  fireEvent.change(within(form).getByLabelText("Masterbatch % (on top of the resin)"), { target: { value: "2" } });
  fireEvent.change(within(form).getByLabelText("Machine"), { target: { value: "11" } });
  fireEvent.change(within(form).getByLabelText("Cycle time (seconds)"), { target: { value: "20" } });
  fireEvent.change(within(form).getByLabelText("Rejects %"), { target: { value: "3" } });
  fireEvent.change(within(form).getByLabelText("Packing cost (LKR)"), { target: { value: "120" } });
  fireEvent.change(within(form).getByLabelText("Packing cost is"), { target: { value: "carton" } });
  fireEvent.change(within(form).getByLabelText("Pieces per carton"), { target: { value: "500" } });
  fireEvent.change(within(form).getByLabelText("How the mould is charged"), { target: { value: "amortised" } });
  fireEvent.change(within(form).getByLabelText("Mould cost (LKR)"), { target: { value: "900000" } });
  fireEvent.change(within(form).getByLabelText("Spread over (pieces)"), { target: { value: "300000" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save costing" }));

  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/quotations/12/costing/1/", expect.objectContaining({ method: "PUT" })),
  );
  const [, init] = calls.mock.calls.find(([url]) => url === "/api/v1/quotations/12/costing/1/")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    method: "moulding",
    material: 8,
    masterbatch: 9,
    masterbatch_pct: "2",
    part_weight_g: "10",
    runner_weight_g: "8",
    cavities: "4",
    machine: 11,
    cycle_time_s: "20",
    reject_pct: "3",
    packing_amount: "120",
    packing_per: "carton",
    pcs_per_carton: "500",
    tooling: "amortised",
    tooling_cost: "900000",
    tooling_qty: "300000",
    operations: [],
  });
  const table = await screen.findByRole("table", { name: "Price build-up, line 1" });
  expect(within(table).getByRole("row", { name: /Rejects/ })).toHaveTextContent("0.28");
  expect(within(table).getByRole("row", { name: /Mould share/ })).toHaveTextContent("3.00");
  expect(within(table).getByRole("row", { name: /Suggested price/ })).toHaveTextContent("17.24");
  expect(screen.getByText("Machine time: 1.39 hours per 1,000 pieces.")).toBeInTheDocument();
});

test("a quotation line can be marked as tooling, charged once", async () => {
  const calls = mockApi(formApi({ "GET /api/v1/quotations/12/": { body: saved }, "PUT /api/v1/quotations/12/": { body: saved } }));
  renderAt("/quotations/12", <QuotationPage />, "/quotations/:id");
  const form = await screen.findByRole("form", { name: "Quotation details" });
  fireEvent.click(within(form).getByLabelText("Tooling, line 1"));
  fireEvent.click(within(form).getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/quotations/12/", expect.objectContaining({ method: "PUT" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/quotations/12/" && i?.method === "PUT")!;
  expect(JSON.parse(String(init!.body)).lines[0].is_tooling).toBe(true);
});

// --- Approval, outcome and revisions (P15-06) ---------------------------------------------

test("the creator sends a saved draft to the Director", async () => {
  const waitingOne: QuotationDetail = {
    ...saved,
    status: "awaiting_approval",
    can_edit: false,
    can_submit: false,
    approval: { status: "in_progress", waiting_with: "Director", history: [] },
  };
  const calls = mockApi(
    formApi({ "GET /api/v1/quotations/12/": { body: saved }, "POST /api/v1/quotations/12/submit/": { body: waitingOne } }),
  );
  renderAt("/quotations/12", <QuotationPage />, "/quotations/:id");
  const panel = await screen.findByRole("region", { name: "Approval and status" });
  expect(within(panel).getByText(/cannot be printed as final or sent/)).toBeInTheDocument();
  fireEvent.change(within(panel).getByLabelText("Note for the Director (optional)"), { target: { value: "Urgent" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Send to the Director for approval" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/quotations/12/submit/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url]) => url === "/api/v1/quotations/12/submit/")!;
  expect(JSON.parse(String(init!.body))).toEqual({ comment: "Urgent" });
  expect(await screen.findByText("Waiting for approval by the Director.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
});

test("the Director sees the warnings and approves or returns", async () => {
  const waitingOne: QuotationDetail = {
    ...saved,
    status: "awaiting_approval",
    can_edit: false,
    can_submit: false,
    can_approve: true,
    can_see_costing: true,
    approval: {
      status: "in_progress",
      waiting_with: "Director",
      history: [{ action: "submit", action_label: "Submitted", level: 1, by: "Sales", at: "2026-10-31T10:00:00", reason: "Urgent" }],
    },
    review: {
      margin_pct: "13.04",
      value_lkr: "76469.00",
      min_margin_pct: "20.00",
      limit_lkr: "50000.00",
      warnings: ["Margin 13.04% is below the minimum of 20.00%."],
    },
  };
  const calls = mockApi({
    "GET /api/v1/quotations/12/": { body: waitingOne },
    "POST /api/v1/quotations/12/approve/": { body: { ...waitingOne, status: "approved", can_approve: false, is_final: true, approval: null } },
  });
  renderAt("/quotations/12", <QuotationPage />, "/quotations/:id");
  const panel = await screen.findByRole("region", { name: "Approval and status" });
  expect(within(panel).getByText(/13.04%/, { selector: "strong" })).toBeInTheDocument();
  expect(within(panel).getByRole("list", { name: "Warnings for the Director" })).toHaveTextContent("below the minimum of 20.00%");
  expect(within(panel).getByRole("list", { name: "Approval history" })).toHaveTextContent("Submitted · Sales");
  fireEvent.click(within(panel).getByRole("button", { name: "Approve" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/quotations/12/approve/", expect.objectContaining({ method: "POST" })));
  await waitFor(() => expect(screen.queryByText(/cannot be printed as final/)).not.toBeInTheDocument());
});

test("an approved quotation is marked sent, then won or lost with the reason", async () => {
  const sent: QuotationDetail = { ...saved, status: "sent", can_edit: false, can_submit: false, is_final: true, can_record_outcome: true, can_revise: true };
  const calls = mockApi({
    "GET /api/v1/quotations/12/": { body: sent },
    "POST /api/v1/quotations/12/outcome/": {
      body: { ...sent, status: "lost", can_record_outcome: false, outcome: { reason: "price", reason_label: "Price", note: "15% cheaper", at: "", by: "Sales" } },
    },
  });
  renderAt("/quotations/12", <QuotationPage />, "/quotations/:id");
  const outcome = await screen.findByRole("group", { name: "Outcome" });
  fireEvent.change(within(outcome).getByLabelText("Outcome"), { target: { value: "lost" } });
  fireEvent.change(within(outcome).getByLabelText("Why"), { target: { value: "price" } });
  fireEvent.change(within(outcome).getByLabelText("Note"), { target: { value: "15% cheaper" } });
  fireEvent.click(within(outcome).getByRole("button", { name: "Record the outcome" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/quotations/12/outcome/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url]) => url === "/api/v1/quotations/12/outcome/")!;
  expect(JSON.parse(String(init!.body))).toEqual({ outcome: "lost", reason: "price", note: "15% cheaper" });
  expect(await screen.findByText(/15% cheaper/, { selector: "p" })).toBeInTheDocument();
});

test("a revision opens as a new draft with the same number", async () => {
  const approvedOne: QuotationDetail = { ...saved, status: "approved", can_edit: false, can_submit: false, is_final: true, can_revise: true };
  const rev1: QuotationDetail = {
    ...saved,
    id: 13,
    revision: 1,
    revisions: [
      { id: 12, revision: 0, status: "revised", quote_date: "2026-10-31" },
      { id: 13, revision: 1, status: "draft", quote_date: "2026-10-31" },
    ],
  };
  mockApi(
    formApi({
      "GET /api/v1/quotations/12/": { body: approvedOne },
      "POST /api/v1/quotations/12/revise/": { status: 201, body: rev1 },
      "GET /api/v1/quotations/13/": { body: rev1 },
    }),
  );
  renderAt("/quotations/12", <QuotationPage />, "/quotations/:id");
  fireEvent.click(await screen.findByRole("button", { name: "Make a revision" }));
  expect(await screen.findByRole("heading", { name: "Quotation QL26103101 Rev 1" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Rev 0" })).toHaveAttribute("href", "/quotations/12");
});

test("approvers can list the quotations waiting for them", async () => {
  const director: CurrentUser = { ...sampleUser, access: { areas: { sales: ["approve", "view"] }, actions: [], divisions: "all" } };
  mockApi({
    "GET /api/v1/quotations/": { body: [] },
    "GET /api/v1/quotations/?waiting=me": { body: [saved] },
  });
  renderAt("/quotations", <QuotationsPage me={director} />);
  fireEvent.click(await screen.findByLabelText("Waiting for my approval"));
  const table = await screen.findByRole("table", { name: "Quotations" });
  expect(await within(table).findByRole("link", { name: "QL26103101" })).toBeInTheDocument();
});

// --- Printed quotation and email (P15-07) --------------------------------------------------

test("every quotation can be printed; a draft prints marked NOT APPROVED", async () => {
  mockApi(formApi({ "GET /api/v1/quotations/12/": { body: saved } }));
  renderAt("/quotations/12", <QuotationPage />, "/quotations/:id");
  const link = await screen.findByRole("link", { name: "Print (PDF)" });
  expect(link).toHaveAttribute("href", "/api/v1/quotations/12/pdf/");
  expect(screen.getByText(/Prints as NOT APPROVED/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Email to the customer" })).not.toBeInTheDocument();
});

test("an approved quotation is emailed to the customer with its PDF", async () => {
  const approvedOne: QuotationDetail = { ...saved, status: "approved", can_edit: false, can_submit: false, is_final: true, can_email: true, can_mark_sent: true };
  const calls = mockApi({
    "GET /api/v1/quotations/12/": { body: approvedOne },
    "GET /api/v1/quotations/12/email/": {
      body: { from: "SML Engineers <sales@smlengineers.lk>", ready: true, to: ["lars@nordic.se"], cc: [], subject: "Quotation QL26103101 from SML", body: "Dear Lars," },
    },
    "POST /api/v1/quotations/12/email/": {
      body: {
        ...approvedOne,
        status: "sent",
        can_mark_sent: false,
        emails: [{ to: "lars@nordic.se", cc: "", subject: "Quotation QL26103101 from SML", status: "sent", error: "", sent_at: "2026-10-31T15:00:00", by: "Sales" }],
      },
    },
  });
  renderAt("/quotations/12", <QuotationPage />, "/quotations/:id");
  fireEvent.click(await screen.findByRole("button", { name: "Email to the customer" }));
  const form = await screen.findByRole("form", { name: "Email to the customer" });
  expect(within(form).getByLabelText("To (separate addresses with commas)")).toHaveValue("lars@nordic.se");
  fireEvent.change(within(form).getByLabelText("Copy to"), { target: { value: "anna@nordic.se; boss@nordic.se" } });
  fireEvent.click(within(form).getByRole("button", { name: "Send" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/quotations/12/email/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/quotations/12/email/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toEqual({
    to: ["lars@nordic.se"],
    cc: ["anna@nordic.se", "boss@nordic.se"],
    subject: "Quotation QL26103101 from SML",
    body: "Dear Lars,",
  });
  expect(await screen.findByRole("list", { name: "Emails sent" })).toHaveTextContent("lars@nordic.se");
});

// --- Discount (P15-07b) ----------------------------------------------------------------------

test("a discount % is entered on the quotation and shown in the totals", async () => {
  const discounted: QuotationDetail = { ...saved, discount_pct: "3.00", discount_total: "7.05", subtotal: "227.95", total_amount: "227.95" };
  const calls = mockApi(formApi({ "GET /api/v1/quotations/12/": { body: saved }, "PUT /api/v1/quotations/12/": { body: discounted } }));
  renderAt("/quotations/12", <QuotationPage />, "/quotations/:id");
  const form = await screen.findByRole("form", { name: "Quotation details" });
  fireEvent.change(within(form).getByLabelText("Discount % (on every line, before tax)"), { target: { value: "3" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/quotations/12/", expect.objectContaining({ method: "PUT" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/quotations/12/" && i?.method === "PUT")!;
  expect(JSON.parse(String(init!.body)).discount_pct).toBe("3");
  expect(await screen.findByText(/Discount 3.00%/)).toBeInTheDocument();
});

// --- Proforma from an accepted quotation (P15-08) -------------------------------------------

test("an accepted quotation makes a proforma invoice", async () => {
  const won: QuotationDetail = { ...saved, status: "accepted", can_edit: false, can_submit: false, is_final: true, can_make_proforma: true };
  const calls = mockApi({
    "GET /api/v1/quotations/12/": { body: won },
    "POST /api/v1/proformas/": { status: 201, body: { id: 40 } },
  });
  renderAt("/quotations/12", <QuotationPage />, "/quotations/:id");
  fireEvent.click(await screen.findByRole("button", { name: "Make a proforma invoice" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/proformas/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url]) => url === "/api/v1/proformas/")!;
  expect(JSON.parse(String(init!.body))).toEqual({ quotation: 12 });
});
