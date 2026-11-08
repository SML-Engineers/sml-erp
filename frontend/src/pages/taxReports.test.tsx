import { screen, within } from "@testing-library/react";

import type { VatReport } from "../api/taxReports";
import { mockApi, renderAt } from "../test-utils";
import TaxReportsPage from "./TaxReportsPage";

function lastMonth(): [number, number] {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return [d.getFullYear(), d.getMonth() + 1];
}

const [year, month] = lastMonth();
const vat: VatReport = {
  year,
  month,
  supplies: { standard: "115750.00", zero: "750000.00", exempt: "0.00", outside: "0.00" },
  output_vat: "21277.75",
  ledger_output_vat: "21277.75",
  input_vat: "1800.00",
  payable: "19477.75",
  sales: [
    {
      date: "2026-10-05",
      document: "26OCT_W1_01",
      kind: "Tax invoice",
      link: "/tax-invoices/1",
      customer: "Lanka Tiles PLC",
      tin: "114455667",
      standard: "115750.00",
      zero: "0.00",
      exempt: "0.00",
      outside: "0.00",
      vat: "21277.75",
    },
    {
      date: "2026-10-09",
      document: "26OCT_W1_02",
      kind: "Tax invoice",
      link: "/tax-invoices/2",
      customer: "Mahindra Gears",
      tin: "",
      standard: "0.00",
      zero: "750000.00",
      exempt: "0.00",
      outside: "0.00",
      vat: "0.00",
    },
  ],
  purchases: [
    {
      date: "2026-10-12",
      entry: "JE-4",
      source_type: "supplier_invoice",
      document: "SI26100001",
      supplier: "SDD Polymer",
      tin: "",
      narration: "",
      vat: "1800.00",
    },
  ],
};

test("the month's VAT return shows exports apart", async () => {
  mockApi({
    [`GET /api/v1/tax-reports/vat/?year=${year}&month=${month}`]: { body: vat },
    [`GET /api/v1/tax-reports/sscl/?year=${year}&month=${month}`]: { body: { year, month, total: "0.00", rows: [] } },
    [`GET /api/v1/tax-reports/wht/?year=${year}&month=${month}`]: { body: { year, month, total: "0.00", rows: [] } },
  });
  renderAt("/tax-reports", <TaxReportsPage />);
  const panel = await screen.findByRole("region", { name: "VAT return" });
  expect(within(panel).getByText("Zero-rated supplies (exports)")).toBeInTheDocument();
  expect(within(panel).getByText("19,477.75")).toBeInTheDocument();
  expect(within(panel).getByRole("link", { name: "26OCT_W1_02" })).toHaveAttribute("href", "/tax-invoices/2");
});
