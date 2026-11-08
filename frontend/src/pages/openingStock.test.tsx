import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { OSDetail } from "../api/openingStock";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import OpeningStockPage from "./OpeningStockPage";
import OpeningStocksPage from "./OpeningStocksPage";

const accountant: CurrentUser = {
  ...sampleUser,
  access: { areas: { accounting: ["manage", "enter", "view"], stores: ["view"] }, actions: [], divisions: "all" },
};

const loaded: OSDetail = {
  id: 3,
  number: "OS26110201",
  count_date: "2026-11-02",
  status: "draft",
  notes: "",
  lines: 1,
  value: "525210.00",
  created_by: "Kumari Silva",
  journal_entry: null,
  rows: [
    {
      line_no: 1,
      item: { id: 1, code: "PP-H-25", name: "PP resin" },
      unit: "kg",
      store: "IM-MAIN",
      division: "IM",
      lot_no: "OS26110201-LOT-7",
      quantity: "1250.500",
      unit_cost: "420.0000",
      value: "525210.00",
    },
  ],
  can_edit: true,
  can_approve: false,
  approval: null,
};

function chooseFile(form: HTMLElement) {
  const file = new File(["x"], "count.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  fireEvent.change(within(form).getByLabelText("Excel file (.xlsx)"), { target: { files: [file] } });
}

test("the Accountant checks the sheet and sees every row to correct", async () => {
  mockApi({
    "GET /api/v1/opening-stock/": { body: [] },
    "POST /api/v1/opening-stock/": {
      status: 400,
      body: { detail: "Nothing was loaded.", errors: ["Row 2: There is no item NOPE.", "Row 4: The quantity must be more than 0."] },
    },
  });
  renderAt("/opening-stock", <OpeningStocksPage me={accountant} />);
  const form = await screen.findByRole("form", { name: "Load the counted stock" });
  expect(within(form).getByRole("link", { name: "Download the Excel sheet to fill in" })).toHaveAttribute(
    "href",
    "/api/v1/opening-stock/template/",
  );
  chooseFile(form);
  fireEvent.click(within(form).getByRole("button", { name: "Check the file" }));
  const errors = await within(form).findByRole("list", { name: "Rows to correct" });
  expect(
    within(errors)
      .getAllByRole("listitem")
      .map((li) => li.textContent),
  ).toEqual(["Row 2: There is no item NOPE.", "Row 4: The quantity must be more than 0."]);
});

test("a good sheet is checked, then loaded as a draft", async () => {
  let calls = 0;
  mockApi({
    "GET /api/v1/opening-stock/": { body: [] },
    "POST /api/v1/opening-stock/": () => {
      calls += 1;
      return calls === 1 ? { body: { dry_run: true, rows: 1, value: "525210.00" } } : { status: 201, body: loaded };
    },
    "GET /api/v1/opening-stock/3/": { body: loaded },
  });
  renderAt("/opening-stock", <OpeningStocksPage me={accountant} />);
  const form = await screen.findByRole("form", { name: "Load the counted stock" });
  chooseFile(form);
  fireEvent.click(within(form).getByRole("button", { name: "Check the file" }));
  expect(await within(form).findByRole("status")).toHaveTextContent("The file is fine: 1 rows, LKR 525,210.00.");
  fireEvent.click(within(form).getByRole("button", { name: "Load as a draft" }));
  await waitFor(() => expect(calls).toBe(2));
});

test("the Director approves and the stock goes in", async () => {
  const waiting: OSDetail = { ...loaded, status: "awaiting_approval", can_edit: false, can_approve: true };
  const calls = mockApi({
    "GET /api/v1/opening-stock/3/": { body: waiting },
    "POST /api/v1/opening-stock/3/approve/": {
      body: { ...waiting, status: "posted", can_approve: false, journal_entry: { id: 9, number: "JV26110014" } },
    },
  });
  renderAt("/opening-stock/3", <OpeningStockPage />, "/opening-stock/:id");
  const table = await screen.findByRole("table", { name: "Counted stock" });
  expect(within(table).getByText("OS26110201-LOT-7")).toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "Load the counted stock" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Approve: put it into stock" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/opening-stock/3/approve/",
      expect.objectContaining({ body: JSON.stringify({ comment: "" }) }),
    ),
  );
  expect(await screen.findByRole("link", { name: "JV26110014" })).toBeInTheDocument();
});
