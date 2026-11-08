import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { RecurringJournal } from "../api/recurringJournals";
import { mockApi, renderAt } from "../test-utils";
import RecurringJournalPage from "./RecurringJournalPage";

const account = (id: number, number: string, full_name: string, account_type: string) => ({
  id,
  number,
  name: full_name,
  full_name,
  depth: 0,
  parent: null,
  account_type,
  account_type_label: account_type,
  section: "assets",
  detail_type: { id: 1, name: "x" },
  description: "",
  default_division: null,
  default_tax_code: null,
  system_role: null,
  is_active: true,
  merged_into: null,
  in_use: true,
  company_account: null,
});

const formApi = {
  "GET /api/v1/chart-of-accounts/": {
    body: [account(1, "6220", "Factory rent", "expense"), account(2, "2170", "Accrued expenses", "other_current_liability")],
  },
  "GET /api/v1/payees/": { body: [] },
  "GET /api/v1/divisions/": { body: [{ id: 1, code: "WS", name: "Workshop", division_type: "production" }] },
};

const rent: RecurringJournal = {
  id: 3,
  name: "Factory rent",
  narration: "Accrue factory rent",
  frequency: "monthly",
  day_of_month: 31,
  start_date: "2026-11-01",
  end_date: null,
  next_date: "2026-11-30",
  reverse_next_month: true,
  is_active: true,
  created_by: "Kumari Silva",
  amount: "150000.00",
  made: [{ id: 9, number: "MJ26103101", entry_date: "2026-10-31", status: "posted" }],
  lines: [
    {
      line_no: 1,
      account: { id: 1, number: "6220", name: "Factory rent", account_type: "expense" },
      division: "WS",
      supplier: null,
      description: "",
      debit: "150000.00",
      credit: "0.00",
    },
    {
      line_no: 2,
      account: { id: 2, number: "2170", name: "Accrued expenses", account_type: "other_current_liability" },
      division: null,
      supplier: null,
      description: "",
      debit: "0.00",
      credit: "150000.00",
    },
  ],
};

async function choose(form: HTMLElement, label: string, typed: string, option: string) {
  fireEvent.change(within(form).getByRole("combobox", { name: label }), { target: { value: typed } });
  fireEvent.mouseDown(await within(form).findByRole("option", { name: option }));
}

test("the Accountant sets up a monthly accrual on the last day", async () => {
  const calls = mockApi({
    ...formApi,
    "POST /api/v1/recurring-journals/": { status: 201, body: rent },
    "GET /api/v1/recurring-journals/3/": { body: rent },
  });
  renderAt("/journals/recurring/new", <RecurringJournalPage />, "/journals/recurring/:id");
  const form = await screen.findByRole("form", { name: "Recurring journal details" });
  fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Factory rent" } });
  fireEvent.change(within(form).getByLabelText("Narration"), { target: { value: "Accrue factory rent" } });
  fireEvent.click(within(form).getByLabelText(/reverse it automatically/));
  await choose(form, "Account, line 1", "rent", "6220 Factory rent");
  fireEvent.change(within(form).getByLabelText("Debit, line 1"), { target: { value: "150000" } });
  await waitFor(() => expect(within(form).getByLabelText("Division, line 1").querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(within(form).getByLabelText("Division, line 1"), { target: { value: "WS" } });
  await choose(form, "Account, line 2", "accrued", "2170 Accrued expenses");
  fireEvent.change(within(form).getByLabelText("Credit, line 2"), { target: { value: "150000" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save the recurring journal" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/recurring-journals/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/recurring-journals/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    name: "Factory rent",
    frequency: "monthly",
    day_of_month: 31,
    end_date: null,
    reverse_next_month: true,
    lines: [
      { account: 1, debit: "150000", division: "WS" },
      { account: 2, credit: "150000", division: null },
    ],
  });
  expect(await screen.findByText(/next journal on 2026-11-30/)).toBeInTheDocument();
});

test("a template shows the journals it made and can be stopped", async () => {
  const calls = mockApi({
    ...formApi,
    "GET /api/v1/recurring-journals/3/": { body: rent },
    "POST /api/v1/recurring-journals/3/active/": { body: { ...rent, is_active: false } },
  });
  renderAt("/journals/recurring/3", <RecurringJournalPage />, "/journals/recurring/:id");
  const made = await screen.findByRole("region", { name: "Journals made" });
  expect(within(made).getByRole("link", { name: "MJ26103101" })).toHaveAttribute("href", "/journals/manual/9");
  fireEvent.click(screen.getByRole("button", { name: "Stop making journals" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/recurring-journals/3/active/",
      expect.objectContaining({ body: JSON.stringify({ active: false }) }),
    ),
  );
  expect(await screen.findByRole("button", { name: "Start making journals again" })).toBeInTheDocument();
});
