import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { CompanyAccount } from "../api/banking";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import BankAccountsPage from "./BankAccountsPage";

const accountant: CurrentUser = {
  ...sampleUser,
  access: { areas: { banking: ["enter", "manage", "view"] }, actions: [], divisions: "all" },
};

const cashier: CurrentUser = {
  ...sampleUser,
  access: { areas: { banking: ["view"] }, actions: ["record_payment"], divisions: "all" },
};

const current: CompanyAccount = {
  id: 1,
  code: "COM-CUR",
  name: "Commercial Bank current",
  kind: "current",
  bank_name: "Commercial Bank",
  branch: "Seeduwa",
  account_number: "1000234567",
  currency: "LKR",
  division: null,
  custodian: null,
  float_amount: null,
  ledger_account: null,
  is_active: true,
  default_for: ["WS"],
  cheque_books: [
    {
      id: 5,
      first: "100001",
      last: "100050",
      first_number: 100001,
      last_number: 100050,
      digits: 6,
      received_on: "2026-10-01",
      is_active: true,
      summary: { leaves: 50, used: 2, left: 48, next: "100003" },
    },
  ],
  in_use: true,
};

const api = (extra: Parameters<typeof mockApi>[0] = {}) => ({
  "GET /api/v1/company-accounts/": { body: [current] },
  "GET /api/v1/company-accounts/custodians/": { body: [{ id: 3, name: "Kamal" }] },
  "GET /api/v1/company-accounts/ledgers/": {
    body: [
      { id: 40, number: "1030", name: "Commercial Bank current", linked_to: null },
      { id: 41, number: "1010", name: "Cash on hand", linked_to: "CASH" },
    ],
  },
  "GET /api/v1/company-accounts/division-defaults/": {
    body: [
      { division: "WS", account: { id: 1, code: "COM-CUR" } },
      { division: "IM", account: null },
    ],
  },
  "GET /api/v1/company-accounts/1/cheques/": {
    body: {
      next: "100003",
      used: [
        { id: 1, number: "100001", status: "issued", reason: "", used_by: "cashier@sml.lk", used_at: "" },
        { id: 2, number: "100002", status: "spoiled", reason: "wrong amount", used_by: "cashier@sml.lk", used_at: "" },
      ],
    },
  },
  ...extra,
});

test("the accountant adds petty cash with a custodian and float", async () => {
  const calls = mockApi(api({ "POST /api/v1/company-accounts/": { status: 201, body: current } }));
  renderAt("/bank-accounts", <BankAccountsPage me={accountant} />);

  const form = await screen.findByRole("region", { name: "Add account" });
  fireEvent.change(within(form).getByLabelText("Kind"), { target: { value: "petty_cash" } });
  expect(within(form).queryByLabelText("Account number")).not.toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Code"), { target: { value: "PETTY-WS" } });
  fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Workshop petty cash" } });
  fireEvent.change(await within(form).findByLabelText("Custodian"), { target: { value: "3" } });
  fireEvent.change(within(form).getByLabelText("Float (LKR)"), { target: { value: "25000" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add account" }));

  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/company-accounts/", expect.objectContaining({ method: "POST" })),
  );
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    kind: "petty_cash",
    custodian: 3,
    float_amount: "25000",
  });
});

test("the cashier sees the next cheque and records a spoiled one, but cannot add books", async () => {
  const calls = mockApi(
    api({ "POST /api/v1/company-accounts/1/cheques/": { status: 201, body: {} } }),
  );
  renderAt("/bank-accounts", <BankAccountsPage me={cashier} />);

  fireEvent.click(await screen.findByRole("button", { name: "COM-CUR" }));
  const books = await screen.findByRole("group", { name: "Cheque books" });
  expect(await within(books).findByText("100003")).toBeInTheDocument();
  expect(within(books).queryByRole("form", { name: "Add cheque book" })).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Add account" })).not.toBeInTheDocument();

  const spoil = within(books).getByRole("form", { name: "Record a spoiled cheque" });
  fireEvent.change(within(books).getByLabelText("Reason"), { target: { value: "torn" } });
  fireEvent.change(within(spoil).getByLabelText("Cheque number"), { target: { value: "100003" } });
  fireEvent.click(within(spoil).getByRole("button", { name: "Record a spoiled cheque" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/company-accounts/1/cheques/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ number: 100003, reason: "torn" }) }),
    ),
  );
});

test("each division's default bank account is shown", async () => {
  mockApi(api());
  renderAt("/bank-accounts", <BankAccountsPage me={cashier} />);

  const panel = await screen.findByRole("region", { name: "Default bank account of each division" });
  await waitFor(() => expect(within(panel).getByLabelText("WS")).toHaveValue("1"));
  expect(within(panel).getByLabelText("IM")).toHaveValue("");
  expect(within(panel).getByLabelText("WS")).toBeDisabled();
});

test("the accountant links an account to its Bank ledger in the chart of accounts", async () => {
  const unused = { ...current, in_use: false, cheque_books: [] };
  const calls = mockApi(
    api({
      "GET /api/v1/company-accounts/": { body: [unused] },
      "PATCH /api/v1/company-accounts/1/": {
        body: { ...unused, ledger_account: { id: 40, number: "1030", name: "Commercial Bank current" } },
      },
    }),
  );
  renderAt("/bank-accounts", <BankAccountsPage me={accountant} />);

  fireEvent.click(await screen.findByRole("button", { name: "COM-CUR" }));
  const link = await screen.findByRole("form", { name: "Save ledger account" });
  expect(within(link).getByText("Not linked yet")).toBeInTheDocument();
  const select = within(link).getByLabelText("Ledger account");
  await within(link).findByRole("option", { name: "1030 Commercial Bank current" });
  // a ledger already linked to another company account is not offered
  expect(within(link).queryByRole("option", { name: "1010 Cash on hand" })).not.toBeInTheDocument();
  fireEvent.change(select, { target: { value: "40" } });
  fireEvent.click(within(link).getByRole("button", { name: "Save ledger account" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/company-accounts/1/",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ ledger_account: 40 }) }),
    ),
  );
});
