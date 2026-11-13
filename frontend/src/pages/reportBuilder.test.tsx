import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { Builder, ReportResult } from "../api/reportBuilder";
import { mockApi, renderAt } from "../test-utils";
import ReportBuilderPage from "./ReportBuilderPage";

const builder: Builder = {
  sources: [
    {
      key: "journal_lines",
      label: "Journal lines (the ledger)",
      fields: [
        { key: "account", label: "Account", kind: "text" },
        { key: "division", label: "Division", kind: "text" },
        { key: "debit", label: "Debit", kind: "money" },
      ],
    },
  ],
  ops: { text: { equals: "iexact", contains: "icontains" }, date: { from: "gte" }, money: { from: "gte" }, number: { from: "gte" } },
  presets: [],
  saved: [],
  roles: [{ code: "director", name: "Director" }],
  max_rows: 5000,
};
const result: ReportResult = {
  columns: [
    { key: "account", label: "Account", kind: "text" },
    { key: "debit", label: "Debit", kind: "money" },
  ],
  rows: [
    { kind: "line", cells: { account: "Repairs", debit: "400.00" } },
    { kind: "total", cells: { account: "Total", debit: "400.00" } },
  ],
  count: 1,
  truncated: false,
};

test("choose a source and columns, put them in order and run", async () => {
  const wanted = {
    source: "journal_lines",
    columns: ["debit", "account"],
    filters: [],
    group_by: null,
    sort: [],
    period: "",
    measure: null,
  };
  const calls = mockApi({
    "GET /api/v1/report-builder/": { body: builder },
    [`GET /api/v1/report-builder/run/?d=${encodeURIComponent(JSON.stringify(wanted))}`]: { body: result },
  });
  renderAt("/report-builder", <ReportBuilderPage />);
  fireEvent.change(await screen.findByLabelText("Data source"), { target: { value: "journal_lines" } });
  fireEvent.click(screen.getByRole("checkbox", { name: "Account" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "Debit" }));
  fireEvent.click(screen.getByRole("button", { name: "Move Debit up" }));
  fireEvent.click(screen.getByRole("button", { name: "Run" }));
  const table = await screen.findByRole("table", { name: "Result" });
  expect(within(table).getByText("Repairs")).toBeInTheDocument();
  expect(within(table).getAllByText("400.00")).toHaveLength(2);
  await waitFor(() => expect(calls).toHaveBeenCalledTimes(2));
});

test("counts show with thousands separators, and each tick box sits with its column's name", async () => {
  // Owner's testing (12 Nov 2026): "3960" for 3,960 good pieces; tick boxes a line above their names.
  const counting: Builder = {
    ...builder,
    sources: [
      {
        key: "moulding_runs",
        label: "Moulding runs",
        fields: [
          { key: "machine", label: "Machine", kind: "text" },
          { key: "good", label: "Good pieces", kind: "number" },
        ],
      },
    ],
  };
  const wanted = {
    source: "moulding_runs",
    columns: ["machine", "good"],
    filters: [],
    group_by: null,
    sort: [],
    period: "",
    measure: null,
  };
  mockApi({
    "GET /api/v1/report-builder/": { body: counting },
    [`GET /api/v1/report-builder/run/?d=${encodeURIComponent(JSON.stringify(wanted))}`]: {
      body: {
        columns: [
          { key: "machine", label: "Machine", kind: "text" },
          { key: "good", label: "Good pieces", kind: "number" },
        ],
        rows: [{ kind: "line", cells: { machine: "IMM-250", good: "3960" } }],
        count: 1,
        truncated: false,
      },
    },
  });
  renderAt("/report-builder", <ReportBuilderPage />);
  fireEvent.change(await screen.findByLabelText("Data source"), { target: { value: "moulding_runs" } });
  const machine = screen.getByRole("checkbox", { name: "Machine" });
  expect(machine.closest("label")).toHaveClass("check");
  fireEvent.click(machine);
  fireEvent.click(screen.getByRole("checkbox", { name: "Good pieces" }));
  fireEvent.click(screen.getByRole("button", { name: "Run" }));
  const table = await screen.findByRole("table", { name: "Result" });
  expect(within(table).getByText("3,960")).toBeInTheDocument();
  expect(within(table).queryByText("3960")).not.toBeInTheDocument();
});
