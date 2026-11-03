import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { Contact, Customer } from "../api/customers";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import CustomersPage from "./CustomersPage";

const executive: CurrentUser = {
  ...sampleUser,
  access: { areas: { sales: ["enter", "view"] }, actions: [], divisions: ["WS"] },
};

const manager: CurrentUser = {
  ...sampleUser,
  access: { areas: { sales: ["approve", "view"] }, actions: [], divisions: "all" },
};

const viewer: CurrentUser = {
  ...sampleUser,
  access: { areas: { sales: ["view"] }, actions: [], divisions: "all" },
};

const nimali: Contact = {
  id: 5, name: "Nimali Fernando", position: "Buyer", phone: "0771234567", email: "", is_main: true, is_active: true,
};

const unilever: Customer = {
  id: 1,
  code: "C0001",
  name: "Unilever Sri Lanka",
  billing_address: "258 M Vincent Perera Mawatha, Colombo 14",
  delivery_address: "",
  phone: "0112345678",
  email: "",
  vat_no: "114000111-7000",
  tin: "",
  currency: "LKR",
  payment_terms_days: 30,
  credit_limit: "500000.00",
  is_export: false,
  country: "",
  incoterm: "",
  port_of_destination: "",
  notes: "",
  is_active: true,
  main_contact: nimali,
  in_use: false,
};

const api = (extra: Parameters<typeof mockApi>[0] = {}) => ({
  "GET /api/v1/customers/": { body: [unilever] },
  "GET /api/v1/customers/1/contacts/": { body: [nimali] },
  "GET /api/v1/currencies/": {
    body: [
      { code: "LKR", name: "Sri Lankan rupee", symbol: "Rs", decimal_places: 2 },
      { code: "EUR", name: "Euro", symbol: "€", decimal_places: 2 },
    ],
  },
  ...extra,
});

test("the list shows each customer with its main contact", async () => {
  mockApi(api());
  renderAt("/customers", <CustomersPage me={executive} />);
  const table = await screen.findByRole("table", { name: "Customers" });
  expect(await within(table).findByText("Nimali Fernando")).toBeInTheDocument();
  expect(within(table).getByText("C0001")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Export to Excel" })).toHaveAttribute("href", "/api/v1/customers/export/");
});

test("an export customer is added with its currency, country and delivery term", async () => {
  const calls = mockApi(
    api({ "POST /api/v1/customers/": { status: 201, body: { ...unilever, id: 2, code: "C0002", name: "Nordic Plast AB" } } }),
  );
  renderAt("/customers", <CustomersPage me={executive} />);

  fireEvent.click(await screen.findByRole("button", { name: "Add customer" }));
  const form = screen.getByRole("region", { name: "Add customer" });
  fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Nordic Plast AB" } });
  await within(form).findByRole("option", { name: "EUR – Euro" });
  fireEvent.change(within(form).getByLabelText("Currency"), { target: { value: "EUR" } });
  expect(within(form).queryByLabelText("Country")).not.toBeInTheDocument(); // only for export customers
  fireEvent.click(within(form).getByLabelText("Export customer"));
  fireEvent.change(within(form).getByLabelText("Country"), { target: { value: "Sweden" } });
  fireEvent.change(within(form).getByLabelText("Delivery term (Incoterm)"), { target: { value: "FOB" } });
  expect(within(form).getByLabelText("Credit limit")).toBeDisabled(); // the Accountant's or the Director's
  fireEvent.click(within(form).getByRole("button", { name: "Save" }));

  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/customers/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/customers/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    name: "Nordic Plast AB",
    currency: "EUR",
    is_export: true,
    country: "Sweden",
    incoterm: "FOB",
    credit_limit: null,
    payment_terms_days: 30,
  });
});

test("a likely duplicate is shown and must be confirmed", async () => {
  mockApi(
    api({
      "POST /api/v1/customers/": (sent) =>
        (sent as { confirm_duplicates: boolean }).confirm_duplicates
          ? { status: 201, body: { ...unilever, id: 2, code: "C0002" } }
          : {
              status: 409,
              body: {
                detail: "There is already a customer called Unilever Sri Lanka (C0001).",
                warnings: ["There is already a customer called Unilever Sri Lanka (C0001)."],
                needs_confirmation: true,
              },
            },
    }),
  );
  renderAt("/customers", <CustomersPage me={executive} />);

  fireEvent.click(await screen.findByRole("button", { name: "Add customer" }));
  const form = screen.getByRole("region", { name: "Add customer" });
  fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Unilever Sri Lanka" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save" }));
  expect(await within(form).findByText(/already a customer called Unilever/)).toBeInTheDocument();
  expect(within(form).getByRole("button", { name: "Save" })).toBeDisabled();
  fireEvent.click(within(form).getByLabelText(/this is a different customer/));
  expect(within(form).getByRole("button", { name: "Save" })).toBeEnabled();
});

test("only the Sales Manager sees Deactivate", async () => {
  mockApi(api());
  const { unmount } = renderAt("/customers", <CustomersPage me={executive} />);
  fireEvent.click(await screen.findByRole("button", { name: "Unilever Sri Lanka" }));
  const form = await screen.findByRole("region", { name: "C0001 Unilever Sri Lanka" });
  expect(within(form).queryByRole("button", { name: "Deactivate" })).not.toBeInTheDocument();
  unmount();

  renderAt("/customers", <CustomersPage me={manager} />);
  fireEvent.click(await screen.findByRole("button", { name: "Unilever Sri Lanka" }));
  const managed = await screen.findByRole("region", { name: "C0001 Unilever Sri Lanka" });
  expect(within(managed).getByRole("button", { name: "Deactivate" })).toBeInTheDocument();
});

test("a contact is added, and another made the main contact", async () => {
  const calls = mockApi(
    api({
      "POST /api/v1/customers/1/contacts/": { status: 201, body: { ...nimali, id: 6, name: "Kasun", is_main: false } },
      "PATCH /api/v1/customers/1/contacts/5/": { body: nimali },
    }),
  );
  renderAt("/customers", <CustomersPage me={executive} />);
  fireEvent.click(await screen.findByRole("button", { name: "Unilever Sri Lanka" }));

  const contacts = await screen.findByRole("region", { name: "Contacts" });
  const add = within(contacts).getByRole("form", { name: "Add a contact" });
  fireEvent.change(within(add).getByLabelText("Name"), { target: { value: "Kasun" } });
  fireEvent.change(within(add).getByLabelText("Email"), { target: { value: "kasun@unilever.com" } });
  fireEvent.click(within(add).getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/customers/1/contacts/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ name: "Kasun", position: "", phone: "", email: "kasun@unilever.com" }) }),
    ),
  );
  expect(within(contacts).getByText("main")).toBeInTheDocument();
});

test("someone who can only look sees no Add or Import buttons", async () => {
  mockApi(api());
  renderAt("/customers", <CustomersPage me={viewer} />);
  await screen.findByRole("table", { name: "Customers" });
  expect(screen.queryByRole("button", { name: "Add customer" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Import from Excel" })).not.toBeInTheDocument();
});

test("an import is checked first and refused rows are listed", async () => {
  mockApi(
    api({
      "POST /api/v1/customers/import/": {
        status: 400,
        body: { detail: "Nothing was imported.", errors: ["Row 4: The TIN must be nine digits."] },
      },
    }),
  );
  renderAt("/customers", <CustomersPage me={executive} />);
  fireEvent.click(await screen.findByRole("button", { name: "Import from Excel" }));
  const panel = screen.getByRole("region", { name: "Import from Excel" });
  const file = new File(["x"], "customers.xlsx");
  fireEvent.change(within(panel).getByLabelText("Excel file (.xlsx)"), { target: { files: [file] } });
  fireEvent.click(within(panel).getByRole("button", { name: "Check file" }));
  expect(await within(panel).findByText(/Row 4: The TIN must be nine digits/)).toBeInTheDocument();
});

test("the Sales Manager deactivates a customer with a reason", async () => {
  const calls = mockApi(api({ "POST /api/v1/customers/1/active/": { body: { ...unilever, is_active: false } } }));
  renderAt("/customers", <CustomersPage me={manager} />);
  fireEvent.click(await screen.findByRole("button", { name: "Unilever Sri Lanka" }));
  const form = await screen.findByRole("region", { name: "C0001 Unilever Sri Lanka" });
  expect(within(form).queryByRole("button", { name: "Save" })).not.toBeInTheDocument(); // approves, does not edit
  fireEvent.change(within(form).getByLabelText("Reason"), { target: { value: "Closed down" } });
  fireEvent.click(within(form).getByRole("button", { name: "Deactivate" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/customers/1/active/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ is_active: false, reason: "Closed down" }) }),
    ),
  );
});

test("the Accountant changes the credit terms, with a reason", async () => {
  const accountant: CurrentUser = {
    ...sampleUser,
    access: { areas: { sales: ["view"], accounting: ["manage", "enter", "view"] }, actions: ["set_credit_terms"], divisions: "all" },
  };
  const calls = mockApi(
    api({ "POST /api/v1/customers/1/credit-terms/": { body: { ...unilever, credit_limit: "750000.00", payment_terms_days: 45 } } }),
  );
  renderAt("/customers", <CustomersPage me={accountant} />);
  fireEvent.click(await screen.findByRole("button", { name: "Unilever Sri Lanka" }));
  const terms = await screen.findByRole("region", { name: "Credit terms" });
  fireEvent.change(within(terms).getByLabelText("Credit limit"), { target: { value: "750,000" } });
  fireEvent.change(within(terms).getByLabelText("Payment terms (days; 0 = on receipt)"), { target: { value: "45" } });
  fireEvent.change(within(terms).getByLabelText("Reason"), { target: { value: "Agreed with the Director" } });
  fireEvent.click(within(terms).getByRole("button", { name: "Save the credit terms" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/customers/1/credit-terms/", expect.objectContaining({ method: "POST" })),
  );
  const [, init] = calls.mock.calls.find(([url]) => url === "/api/v1/customers/1/credit-terms/")!;
  expect(JSON.parse(String(init!.body))).toEqual({
    credit_limit: "750000",
    payment_terms_days: 45,
    reason: "Agreed with the Director",
  });
});

test("a salesperson does not see the credit terms box", async () => {
  mockApi(api());
  renderAt("/customers", <CustomersPage me={executive} />);
  fireEvent.click(await screen.findByRole("button", { name: "Unilever Sri Lanka" }));
  await screen.findByRole("region", { name: "C0001 Unilever Sri Lanka" });
  expect(screen.queryByRole("region", { name: "Credit terms" })).not.toBeInTheDocument();
});
