import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { AccountType, LedgerAccount } from "../api/accounts";
import type { CurrentUser } from "../api/auth";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import ChartOfAccountsPage from "./ChartOfAccountsPage";

const accountant: CurrentUser = {
  ...sampleUser,
  access: { areas: { accounting: ["enter", "manage", "view"] }, actions: [], divisions: "all" },
};

const director: CurrentUser = {
  ...sampleUser,
  access: { areas: { accounting: ["view"] }, actions: [], divisions: "all" },
};

const types: AccountType[] = [
  {
    code: "bank",
    label: "Bank",
    section: "assets",
    section_label: "Balance sheet: assets",
    normal_balance: "debit",
    detail_types: [{ id: 1, name: "Cash on hand", is_active: true }],
  },
  {
    code: "accounts_payable",
    label: "Accounts payable",
    section: "liabilities",
    section_label: "Balance sheet: liabilities",
    normal_balance: "credit",
    detail_types: [{ id: 2, name: "Accounts payable", is_active: true }],
  },
  {
    code: "expense",
    label: "Expense",
    section: "profit_and_loss",
    section_label: "Profit and loss",
    normal_balance: "debit",
    detail_types: [
      { id: 3, name: "Repairs and maintenance", is_active: true },
      { id: 4, name: "Old detail", is_active: false },
    ],
  },
];

function account(over: Partial<LedgerAccount> & Pick<LedgerAccount, "id" | "number" | "name">): LedgerAccount {
  return {
    full_name: over.name,
    depth: 0,
    parent: null,
    account_type: "expense",
    account_type_label: "Expense",
    section: "profit_and_loss",
    detail_type: { id: 3, name: "Repairs and maintenance" },
    description: "",
    default_division: null,
    system_role: null,
    is_active: true,
    merged_into: null,
    in_use: false,
    company_account: null,
    ...over,
  };
}

const cash = account({
  id: 1,
  number: "1010",
  name: "Cash on hand",
  account_type: "bank",
  account_type_label: "Bank",
  section: "assets",
  detail_type: { id: 1, name: "Cash on hand" },
});
const payable = account({
  id: 2,
  number: "2000",
  name: "Accounts payable",
  account_type: "accounts_payable",
  account_type_label: "Accounts payable",
  section: "liabilities",
  detail_type: { id: 2, name: "Accounts payable" },
  system_role: "accounts_payable",
  in_use: true,
});
const repairs = account({ id: 3, number: "6200", name: "Repairs and maintenance" });
const machine = account({
  id: 4,
  number: "6210",
  name: "Machine repairs",
  full_name: "Repairs and maintenance:Machine repairs",
  depth: 1,
  parent: 3,
});
const vehicles = account({ id: 5, number: "6230", name: "Vehicle repairs", full_name: "Repairs and maintenance:Vehicle repairs", depth: 1, parent: 3 });

const api = (extra: Parameters<typeof mockApi>[0] = {}) => ({
  "GET /api/v1/chart-of-accounts/": { body: [cash, payable, repairs, machine, vehicles] },
  "GET /api/v1/chart-of-accounts/types/": { body: types },
  "GET /api/v1/divisions/": { body: [{ id: 1, code: "WS", name: "Workshop" }] },
  ...extra,
});

test("the chart is listed as a tree with system accounts marked", async () => {
  mockApi(api());
  renderAt("/chart-of-accounts", <ChartOfAccountsPage me={director} />);

  const table = await screen.findByRole("table", { name: "Chart of accounts" });
  const row = within(table).getByRole("button", { name: "Machine repairs" }).closest("span")!;
  expect(row).toHaveStyle({ paddingLeft: "1.25rem" });
  const payableRow = within(table).getByRole("button", { name: "Accounts payable" }).closest("tr")!;
  expect(within(payableRow).getByText("System")).toBeInTheDocument();
  // the Director views the chart but cannot change it
  expect(screen.queryByRole("button", { name: "New account" })).not.toBeInTheDocument();
  fireEvent.click(within(table).getByRole("button", { name: "Machine repairs" }));
  const panel = await screen.findByRole("region", { name: "6210 Repairs and maintenance:Machine repairs" });
  expect(within(panel).queryByRole("form", { name: "Edit account" })).not.toBeInTheDocument();
});

test("the accountant adds a sub-account; only accounts of the same type can be its parent", async () => {
  const calls = mockApi(
    api({
      "POST /api/v1/chart-of-accounts/": (sent) => ({
        status: 201,
        body: account({ id: 9, number: "6211", name: "CNC machines", ...(sent as object), parent: 4 }),
      }),
    }),
  );
  renderAt("/chart-of-accounts", <ChartOfAccountsPage me={accountant} />);

  fireEvent.click(await screen.findByRole("button", { name: "New account" }));
  const form = await screen.findByRole("form", { name: "New account" });
  fireEvent.change(within(form).getByLabelText("Type"), { target: { value: "expense" } });
  const detail = within(form).getByLabelText("Detail type");
  // an inactive detail type is not offered for a new account
  expect(within(detail).queryByRole("option", { name: "Old detail" })).not.toBeInTheDocument();
  fireEvent.change(detail, { target: { value: "3" } });
  const parent = within(form).getByLabelText("Sub-account of");
  expect(within(parent).queryByRole("option", { name: "1010 Cash on hand" })).not.toBeInTheDocument();
  fireEvent.change(parent, { target: { value: "4" } });
  fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "CNC machines" } });
  fireEvent.change(within(form).getByLabelText("Number (optional)"), { target: { value: "6211" } });
  await within(form).findByRole("option", { name: "WS Workshop" });
  fireEvent.change(within(form).getByLabelText("Default division"), { target: { value: "WS" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add account" }));

  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/chart-of-accounts/", expect.objectContaining({ method: "POST" })),
  );
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    account_type: "expense",
    detail_type: 3,
    parent: 4,
    name: "CNC machines",
    number: "6211",
    default_division: "WS",
  });
});

test("an account is merged into another of the same type, with a reason", async () => {
  const calls = mockApi(
    api({ "POST /api/v1/chart-of-accounts/5/merge/": { body: machine } }),
  );
  renderAt("/chart-of-accounts", <ChartOfAccountsPage me={accountant} />);

  fireEvent.click(await screen.findByRole("button", { name: "Vehicle repairs" }));
  const panel = await screen.findByRole("region", { name: "6230 Repairs and maintenance:Vehicle repairs" });
  const merge = within(panel).getByRole("form", { name: "Merge" });
  const into = within(merge).getByLabelText("Merge into");
  expect(within(into).queryByRole("option", { name: "1010 Cash on hand" })).not.toBeInTheDocument();
  fireEvent.change(into, { target: { value: "4" } });
  fireEvent.change(within(panel).getAllByLabelText("Reason").at(-1)!, { target: { value: "duplicate" } });
  fireEvent.click(within(merge).getByRole("button", { name: "Merge" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/chart-of-accounts/5/merge/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ into: 4, reason: "duplicate" }) }),
    ),
  );
});

test("a system account cannot be made inactive, deleted or merged away", async () => {
  mockApi(api());
  renderAt("/chart-of-accounts", <ChartOfAccountsPage me={accountant} />);

  fireEvent.click(await screen.findByRole("button", { name: "Accounts payable" }));
  const panel = await screen.findByRole("region", { name: "2000 Accounts payable" });
  expect(within(panel).getByText(/The system posts to this account/)).toBeInTheDocument();
  expect(within(panel).queryByRole("button", { name: "Make inactive" })).not.toBeInTheDocument();
  expect(within(panel).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  expect(within(panel).queryByRole("form", { name: "Merge" })).not.toBeInTheDocument();
  expect(within(panel).getByLabelText("Type")).toBeDisabled();
});

test("a refused import lists every refused row", async () => {
  mockApi(
    api({
      "POST /api/v1/chart-of-accounts/import/": {
        status: 400,
        body: { detail: "Nothing was imported.", errors: ["Row 3: A sub-account must have the same type as its parent."] },
      },
    }),
  );
  renderAt("/chart-of-accounts", <ChartOfAccountsPage me={accountant} />);

  fireEvent.click(await screen.findByRole("button", { name: "Import from Excel" }));
  const panel = await screen.findByRole("region", { name: "Import from Excel" });
  const file = new File(["x"], "chart.xlsx");
  fireEvent.change(within(panel).getByLabelText("Excel file (.xlsx)"), { target: { files: [file] } });
  fireEvent.click(within(panel).getByRole("button", { name: "Import" }));
  const alert = await within(panel).findByRole("alert");
  expect(alert).toHaveTextContent("Nothing was imported.");
  expect(alert).toHaveTextContent("Row 3: A sub-account must have the same type as its parent.");
});
