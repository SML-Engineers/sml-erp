import { fireEvent, screen, within } from "@testing-library/react";

import type { OeeFigures, OeeReport } from "../api/oee";
import { mockApi, renderAt } from "../test-utils";
import OeePage from "./OeePage";

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
const now = new Date();
const start = iso(new Date(now.getFullYear(), now.getMonth(), 1));
const end = iso(now);

const day: OeeFigures = {
  planned_h: "8.00",
  planned_stops_h: "6.00",
  run_h: "2.00",
  unplanned_stops_h: "0.00",
  good: "3960",
  made: 4000,
  availability: "100.0",
  performance: "83.3",
  quality: "99.0",
  oee: "82.5",
};
const idle: OeeFigures = {
  ...day,
  planned_stops_h: "0.00",
  run_h: "0.00",
  good: "0",
  made: 0,
  availability: "0.0",
  performance: null,
  quality: null,
  oee: "0.0",
};
const report: OeeReport = {
  start,
  end,
  sections: ["IM-MLD"],
  total: { ...day, planned_h: "24.00", availability: "20.0", oee: "16.5" },
  machines: [
    {
      machine: "IMM-250",
      name: "Haitian 250 t",
      section: "IM-MLD",
      ...day,
      planned_h: "16.00",
      availability: "20.0",
      oee: "16.5",
      months: [{ month: "2026-11", ...day }],
      days: [
        { day: "2026-11-08", ...idle },
        { day: "2026-11-09", ...day },
      ],
      shifts: [
        { day: "2026-11-08", shift: "G", ...idle },
        { day: "2026-11-09", shift: "G", ...day },
      ],
    },
    { machine: "IMM-120", name: "Haitian 120 t", section: "IM-MLD", ...idle, months: [], days: [], shifts: [] },
  ],
};

test("machines compared, then one machine day by day", async () => {
  mockApi({
    [`GET /api/v1/oee/?start=${start}&end=${end}`]: { body: report },
    [`GET /api/v1/oee/?start=${start}&end=${end}&section=IM-MLD`]: { body: report },
  });
  renderAt("/oee", <OeePage />);
  const table = await screen.findByRole("table", { name: "Machines compared" });
  expect(within(table).getByRole("row", { name: /IMM-250/ })).toHaveTextContent("16.002.000.003,96020.0%83.3%99.0%16.5%");
  expect(within(table).getByRole("row", { name: /IMM-120/ })).toHaveTextContent("0.0%––0.0%");
  expect(within(table).getByRole("row", { name: /Total/ })).toHaveTextContent("24.00");
  fireEvent.click(within(table).getByRole("button", { name: "IMM-250" }));
  const days = screen.getByRole("table", { name: "IMM-250 by day" });
  expect(within(days).getByRole("row", { name: /2026-11-09/ })).toHaveTextContent("2026-11-098.002.00100.0%83.3%99.0%82.5%");
  expect(screen.getByText("By shift (2)")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Section"), { target: { value: "IM-MLD" } });
  expect(await screen.findByRole("table", { name: "Machines compared" })).toBeInTheDocument();
});
