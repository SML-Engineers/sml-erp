import { fireEvent, render, screen, within } from "@testing-library/react";

import "../i18n";
import DataTable, { type Column } from "./DataTable";

interface Voucher {
  no: string;
  name: string;
  total: string;
}

const vouchers: Voucher[] = Array.from({ length: 12 }, (_, i) => ({
  no: `IM2610${String(i + 1).padStart(5, "0")}`,
  name: i === 3 ? "Kleenpark Plus (PVT) Ltd" : `Supplier ${i + 1}`,
  total: i === 0 ? "0.10" : i === 1 ? "0.20" : "1000.00",
}));

const columns: Column<Voucher>[] = [
  { id: "no", header: "Voucher No.", value: (v) => v.no },
  { id: "name", header: "Name", value: (v) => v.name },
  { id: "total", header: "Total", value: (v) => v.total, money: true },
];

function renderTable(pageSize: number | "all" = 10) {
  render(<DataTable rows={vouchers} columns={columns} rowKey={(v) => v.no} pageSize={pageSize} />);
}

const bodyRows = () => within(screen.getAllByRole("rowgroup")[1]).getAllByRole("row");

test("pages through entries with Previous and Next", () => {
  renderTable(10);
  expect(bodyRows()).toHaveLength(10);
  expect(screen.getByText("Showing 1 to 10 of 12 entries")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(bodyRows()).toHaveLength(2);
  expect(screen.getByText("Showing 11 to 12 of 12 entries")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
});

test("Show All lists every entry, as in the current system", () => {
  renderTable(10);
  fireEvent.change(screen.getByLabelText(/Show/), { target: { value: "all" } });
  expect(bodyRows()).toHaveLength(12);
});

test("search narrows the list", () => {
  renderTable();
  fireEvent.change(screen.getByRole("searchbox", { name: "Search" }), {
    target: { value: "kleenpark" },
  });
  expect(bodyRows()).toHaveLength(1);
  expect(screen.getByText("Showing 1 to 1 of 1 entries")).toBeInTheDocument();
});

test("sorting by a money column compares amounts, not text", () => {
  renderTable("all");
  const header = screen.getByRole("button", { name: /Total/ });
  fireEvent.click(header); // ascending
  expect(within(bodyRows()[0]).getByText("0.10")).toBeInTheDocument();
  fireEvent.click(header); // descending
  expect(within(bodyRows()[0]).getByText("1,000.00")).toBeInTheDocument();
});

test("totals are exact and follow the search", () => {
  renderTable("all");
  const footer = screen.getAllByRole("rowgroup")[2];
  expect(within(footer).getByText("10,000.30")).toBeInTheDocument();

  fireEvent.change(screen.getByRole("searchbox", { name: "Search" }), {
    target: { value: "Supplier 2" },
  });
  expect(within(screen.getAllByRole("rowgroup")[2]).getByText("0.20")).toBeInTheDocument();
});
