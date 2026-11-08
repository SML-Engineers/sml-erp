import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { BankAccount, Payee } from "../api/payees";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import PayeesPage from "./PayeesPage";

const clerk: CurrentUser = {
  ...sampleUser,
  access: { areas: { payees: ["enter", "view"] }, actions: [], divisions: ["WS"] },
};

const accountant: CurrentUser = {
  ...sampleUser,
  access: {
    areas: { payees: ["enter", "manage", "view"] },
    actions: ["change_bank_details"],
    divisions: "all",
  },
};

const account: BankAccount = {
  id: 9,
  bank_name: "Commercial Bank",
  branch: "Negombo",
  account_name: "Ceylon Steel Ltd",
  account_number: "1000123456",
  swift_code: "",
  is_default: true,
  is_active: true,
  created_by: "accountant@sml.lk",
  created_at: "2026-10-28T00:00:00Z",
};

const steel: Payee = {
  id: 1,
  code: "S0001",
  name: "Ceylon Steel Ltd",
  category: "supplier",
  address: "",
  phone: "",
  email: "",
  contact_person: "",
  contact_phone: "",
  vat_no: "114223344-7000",
  tin: "",
  payment_terms_days: 30,
  currency: "LKR",
  notes: "",
  is_active: true,
  bank_changed_at: "2026-10-28T03:00:00Z",
  bank_changed_by: "accountant@sml.lk",
  bank_change_pending: true,
  default_account: account,
};

const api = (extra: Parameters<typeof mockApi>[0] = {}) => ({
  "GET /api/v1/payees/": { body: [steel] },
  "GET /api/v1/payees/1/bank-accounts/": { body: [account] },
  ...extra,
});

test("a duplicate VAT number is shown and must be confirmed before saving", async () => {
  let attempts = 0;
  const calls = mockApi(
    api({
      "POST /api/v1/payees/": (sent) => {
        attempts += 1;
        return (sent as { confirm_duplicates: boolean }).confirm_duplicates
          ? { status: 201, body: { ...steel, id: 2, code: "S0002" } }
          : {
              status: 409,
              body: {
                detail: "duplicate",
                needs_confirmation: true,
                warnings: ["VAT number 114223344-7000 is already used by S0001 Ceylon Steel Ltd."],
              },
            };
      },
    }),
  );
  renderAt("/payees", <PayeesPage me={clerk} />);

  fireEvent.click(await screen.findByRole("button", { name: "Add payee" }));
  const form = screen.getByRole("region", { name: "Add payee" });
  fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Ceylon Steel (Pvt)" } });
  fireEvent.change(within(form).getByLabelText("VAT registration no."), {
    target: { value: "114223344-7000" },
  });
  fireEvent.click(within(form).getByRole("button", { name: "Save" }));

  expect(await within(form).findByText(/already used by S0001/)).toBeInTheDocument();
  expect(within(form).getByRole("button", { name: "Save" })).toBeDisabled();
  fireEvent.click(within(form).getByLabelText(/this is a different payee/));
  fireEvent.click(within(form).getByRole("button", { name: "Save" }));

  await waitFor(() => expect(attempts).toBe(2));
  const posts = calls.mock.calls.filter(([, i]) => i?.method === "POST");
  expect(JSON.parse(String(posts[1][1]!.body)).confirm_duplicates).toBe(true);
});

test("a clerk sees bank details and the change flag but cannot change them", async () => {
  mockApi(api());
  renderAt("/payees", <PayeesPage me={clerk} />);

  const row = (await screen.findByRole("button", { name: "Ceylon Steel Ltd" })).closest("tr")!;
  expect(within(row).getByText("bank details changed")).toBeInTheDocument();
  fireEvent.click(within(row).getByRole("button", { name: "Ceylon Steel Ltd" }));

  const bank = await screen.findByRole("region", { name: "Bank accounts" });
  expect(await within(bank).findByText("1000123456")).toBeInTheDocument();
  expect(within(bank).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  expect(within(bank).getByText("Only the Accountant can enter or change bank details.")).toBeInTheDocument();
  expect(within(bank).queryByRole("button", { name: /checked the new bank details/ })).not.toBeInTheDocument();
});

test("the Accountant changes an account number with a reason", async () => {
  const calls = mockApi(
    api({
      "PATCH /api/v1/payees/1/bank-accounts/9/": (sent) => ({
        body: { ...account, ...(sent as object) },
      }),
    }),
  );
  renderAt("/payees", <PayeesPage me={accountant} />);

  fireEvent.click(await screen.findByRole("button", { name: "Ceylon Steel Ltd" }));
  const bank = await screen.findByRole("region", { name: "Bank accounts" });
  expect(within(bank).getByRole("button", { name: "I have checked the new bank details" })).toBeInTheDocument();
  fireEvent.click(await within(bank).findByRole("button", { name: "Edit" }));
  const form = within(bank).getByRole("form", { name: "Change bank account" });
  fireEvent.change(within(form).getByLabelText("Account number"), { target: { value: "2000987654" } });
  fireEvent.change(within(form).getByLabelText("Reason"), {
    target: { value: "supplier's letter of 2 Nov" },
  });
  fireEvent.click(within(form).getByRole("button", { name: "Save" }));

  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/payees/1/bank-accounts/9/", expect.objectContaining({ method: "PATCH" })),
  );
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "PATCH")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    account_number: "2000987654",
    reason: "supplier's letter of 2 Nov",
  });
});
