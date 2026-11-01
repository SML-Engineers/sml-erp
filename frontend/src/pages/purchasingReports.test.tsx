import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import Trail from "../components/Trail";
import { mockApi, renderAt } from "../test-utils";
import PurchasingReportsPage from "./PurchasingReportsPage";

test("the GRNI report shows the ledger balance and exports", async () => {
  mockApi({
    "GET /api/v1/purchasing-reports/open-orders/": { body: [] },
    "GET /api/v1/purchasing-reports/grni/": {
      body: {
        ledger_balance: "8000.00",
        rows: [
          { grn_id: 4, grn: "GRN26110101", receipt_date: "2026-11-01", division: "IM", supplier: "Inserts Lanka", po: "PO26110101",
            item: "M8-INSERT Insert", quantity: "80", unit: "pcs", unit_cost: "100.00", value: "8000.00" },
        ],
      },
    },
  });
  renderAt("/purchasing/reports", <PurchasingReportsPage />);
  fireEvent.click(await screen.findByRole("tab", { name: "Goods received not invoiced" }));
  expect(await screen.findByText("Balance of the Goods received not invoiced account: LKR 8,000.00")).toBeInTheDocument();
  const table = screen.getByRole("table", { name: "Goods received not invoiced" });
  expect(within(table).getByRole("link", { name: "GRN26110101" })).toHaveAttribute("href", "/goods-receipts/4");
  expect(screen.getByRole("link", { name: "Excel" })).toHaveAttribute("href", "/api/v1/purchasing-reports/grni/?export=xlsx");
});

test("the trail links every document of a PO", async () => {
  mockApi({
    "GET /api/v1/purchasing-reports/trail/?grn=4": {
      body: {
        po: { id: 9, label: "PO26110101", status: "Received", total_lkr: "10000.00", parent: null, revisions: [] },
        grns: [{ id: 4, number: "GRN26110101", date: "2026-11-01", status: "Confirmed" }],
        inspections: [{ id: 7, grn: "GRN26110101", item: "M8-INSERT", status: "Decided", decision: "Accepted", accepted: "90", rejected: "10" }],
        invoices: [{ id: 3, number: "SI26110101", invoice_no: "INV-1", status: "Matched and posted", total_lkr: "9000.00", unpaid: "0.00", set_off: "0.00", debited: "0.00" }],
        returns: [],
        vouchers: [{ id: 12, number: "IM261101001", status: "Paid", amount: "9000.00", advance: false, payments: [{ number: "PY2611001", date: "2026-11-02", amount: "9000.00" }] }],
      },
    },
  });
  renderAt("/", <Trail by="grn" id={4} />);
  const trail = await screen.findByRole("region", { name: "Trail" });
  await waitFor(() => expect(within(trail).getByRole("link", { name: "PO26110101" })).toHaveAttribute("href", "/purchase-orders/9"));
  expect(within(trail).getByRole("link", { name: "INV-1" })).toHaveAttribute("href", "/supplier-invoices/3");
  expect(within(trail).getByRole("link", { name: "IM261101001" })).toHaveAttribute("href", "/vouchers/12");
  expect(within(trail).getByText(/paid by PY2611001 2026-11-02/)).toBeInTheDocument();
});
