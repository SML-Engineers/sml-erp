import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { JournalDetail, JournalSummary } from "../api/journal";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import JournalPage from "./JournalPage";
import PeriodsPage from "./PeriodsPage";

const accountant: CurrentUser = {
  ...sampleUser,
  access: { areas: { accounting: ["enter", "manage", "view"] }, actions: [], divisions: "all" },
};

const director: CurrentUser = {
  ...sampleUser,
  access: { areas: { accounting: ["view"] }, actions: ["close_period"], divisions: "all" },
};

const entry: JournalSummary = {
  id: 7,
  number: "JV26100001",
  entry_date: "2026-10-21",
  source_type: "manual",
  source_id: "",
  narration: "Machine repair, CNC lathe",
  amount: "115750.00",
  posted_by: "Nimal",
  posted_at: "2026-10-21T10:00:00Z",
  reversal_of: null,
  reversed_by: null,
};

const detail: JournalDetail = {
  ...entry,
  lines: [
    {
      line_no: 1,
      account: { id: 4, number: "6210", name: "Machine repairs" },
      division: "WS",
      supplier: null,
      description: "",
      debit: "115750.00",
      credit: "0.00",
    },
    {
      line_no: 2,
      account: { id: 1, number: "1010", name: "Cash on hand" },
      division: null,
      supplier: null,
      description: "",
      debit: "0.00",
      credit: "115750.00",
    },
  ],
};

const journalApi = (extra: Parameters<typeof mockApi>[0] = {}) => ({
  "GET /api/v1/journal/": { body: [entry] },
  "GET /api/v1/journal/7/": { body: detail },
  ...extra,
});

test("an entry's lines are shown and the accountant reverses it with a reason", async () => {
  const calls = mockApi(
    journalApi({
      "POST /api/v1/journal/7/reverse/": {
        status: 201,
        body: { ...entry, id: 8, number: "JV26100002", reversal_of: { id: 7, number: "JV26100001" } },
      },
    }),
  );
  renderAt("/journal", <JournalPage me={accountant} />);

  fireEvent.click(await screen.findByRole("button", { name: "JV26100001" }));
  const panel = await screen.findByRole("region", { name: "JV26100001 · 2026-10-21" });
  const lines = within(panel).getByRole("table", { name: "Lines" });
  expect(within(lines).getAllByText("115,750.00")).toHaveLength(4); // two lines and both totals
  const reverse = within(panel).getByRole("form", { name: "Reverse entry" });
  fireEvent.change(within(reverse).getByLabelText("Reason"), { target: { value: "entered twice" } });
  fireEvent.click(within(reverse).getByRole("button", { name: "Reverse entry" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/journal/7/reverse/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "entered twice" }) }),
    ),
  );
});

test("the Director views entries but cannot reverse them; a reversed entry says so", async () => {
  const reversed = { ...detail, reversed_by: { id: 8, number: "JV26100002" } };
  mockApi(journalApi({ "GET /api/v1/journal/7/": { body: reversed } }));
  renderAt("/journal", <JournalPage me={director} />);

  fireEvent.click(await screen.findByRole("button", { name: "JV26100001" }));
  const panel = await screen.findByRole("region", { name: "JV26100001 · 2026-10-21" });
  expect(within(panel).getByText("Reversed by JV26100002")).toBeInTheDocument();
  expect(within(panel).queryByRole("form", { name: "Reverse entry" })).not.toBeInTheDocument();
});

const year = new Date().getFullYear();
const months = {
  year,
  months: [
    { month: "2001-01", is_closed: false, changed_by: null, changed_at: null, entries: 12 },
    { month: "2001-02", is_closed: true, changed_by: "Director", changed_at: "2001-03-02T00:00:00Z", entries: 3 },
  ],
};

test("the Director closes an ended month and reopens a closed one with a reason", async () => {
  const calls = mockApi({
    [`GET /api/v1/accounting-periods/?year=${year}`]: { body: months },
    "POST /api/v1/accounting-periods/2001-02/reopen/": { body: months },
  });
  renderAt("/accounting-periods", <PeriodsPage me={director} />);

  expect(await screen.findByRole("button", { name: "Close 2001-01" })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "late supplier invoice" } });
  fireEvent.click(screen.getByRole("button", { name: "Reopen 2001-02" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/accounting-periods/2001-02/reopen/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "late supplier invoice" }) }),
    ),
  );
});

test("the Accountant sees the periods but cannot close them", async () => {
  mockApi({ [`GET /api/v1/accounting-periods/?year=${year}`]: { body: months } });
  renderAt("/accounting-periods", <PeriodsPage me={accountant} />);

  const table = await screen.findByRole("table", { name: "Accounting periods" });
  expect(within(table).getByText("Closed")).toBeInTheDocument();
  expect(within(table).queryByRole("button")).not.toBeInTheDocument();
});
