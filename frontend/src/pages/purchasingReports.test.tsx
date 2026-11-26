import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";

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
          {
            grn_id: 4,
            grn: "GRN26110101",
            receipt_date: "2026-11-01",
            division: "IM",
            supplier: "Inserts Lanka",
            po: "PO26110101",
            item: "M8-INSERT Insert",
            quantity: "80",
            unit: "pcs",
            unit_cost: "100.00",
            value: "8000.00",
          },
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

// Testing T24 (21 Nov 2026): the Open POs page had no total row; the Excel and PDF files do.
test("open POs are added up in a total row, like the Excel and PDF files", async () => {
  const po = {
    id: 1,
    label: "PO26112101",
    supplier: "Precision Tools",
    delivery_date: "2026-11-28",
    days_late: 0,
    status: "Approved",
    received_pct: "0",
  };
  mockApi({
    "GET /api/v1/purchasing-reports/open-orders/": {
      body: [
        { ...po, outstanding_lkr: "12500.00" },
        { ...po, id: 2, label: "PO26110801", supplier: "Lanka Steel", outstanding_lkr: "227500.00" },
      ],
    },
  });
  renderAt("/purchasing/reports", <PurchasingReportsPage />);
  const table = await screen.findByRole("table", { name: "Open purchase orders" });
  const total = table.querySelector("tfoot tr") as HTMLElement;
  expect(within(total).getByText("Total")).toBeInTheDocument();
  expect(within(total).getByText("240,000.00")).toBeInTheDocument();
});

test("the overdue deliveries tab lists the late POs with their total", async () => {
  const calls = mockApi({
    "GET /api/v1/purchasing-reports/open-orders/?overdue=1": {
      body: [
        {
          id: 3,
          label: "PO26110803",
          supplier: "Lanka Steel",
          delivery_date: "2026-11-18",
          days_late: 7,
          status: "Approved",
          received_pct: "0",
          outstanding_lkr: "227500.00",
        },
      ],
    },
  });
  renderAt("/purchasing/reports?tab=overdue", <PurchasingReportsPage />, "/purchasing/reports");
  const table = await screen.findByRole("table", { name: "Overdue deliveries" });
  expect(within(table).getByRole("link", { name: "PO26110803" })).toHaveAttribute("href", "/purchase-orders/3");
  expect(within(table).getByText("7")).toBeInTheDocument();
  expect(within(table.querySelector("tfoot tr") as HTMLElement).getByText("227,500.00")).toBeInTheDocument();
  expect(calls).toHaveBeenCalledWith("/api/v1/purchasing-reports/open-orders/?overdue=1", expect.anything());
});

// Owner, 22 Nov 2026: rejected goods go back within 14 days; a list shows those waiting.
test("rejected stock lists the lots waiting, those over 14 days in red, and filters them", async () => {
  const lot = { store: "IM-REJ", item: "M8-INSERT Insert", unit: "pcs", grn_id: 4, grn: "GRN26112101", supplier: "Inserts Lanka" };
  mockApi({
    "GET /api/v1/purchasing-reports/rejected-stock/": {
      body: [
        { ...lot, since: "2026-11-05", days: 20, over: true, lot_no: "GRN26112101-1", quantity: "20" },
        { ...lot, since: "2026-11-20", days: 5, over: false, lot_no: "GRN26112102-1", quantity: "3" },
      ],
    },
    "GET /api/v1/purchasing-reports/rejected-stock/?over=1": {
      body: [{ ...lot, since: "2026-11-05", days: 20, over: true, lot_no: "GRN26112101-1", quantity: "20" }],
    },
  });
  renderAt("/purchasing/reports?tab=rejected", <PurchasingReportsPage />, "/purchasing/reports");
  const table = await screen.findByRole("table", { name: "Rejected stock" });
  expect(within(table).getByText("20")).toHaveClass("form-error");
  expect(within(table).getByText("5")).not.toHaveClass("form-error");
  expect(within(table).getByText("20 pcs")).toBeInTheDocument();
  expect(within(table).getAllByRole("link", { name: "GRN26112101" })[0]).toHaveAttribute("href", "/goods-receipts/4");
  expect(screen.getByRole("link", { name: "Excel" })).toHaveAttribute("href", "/api/v1/purchasing-reports/rejected-stock/?export=xlsx");

  fireEvent.click(screen.getByLabelText("Only those over 14 days"));
  await waitFor(() =>
    expect(within(screen.getByRole("table", { name: "Rejected stock" })).queryByText("GRN26112102-1")).not.toBeInTheDocument(),
  );
  expect(screen.getByRole("link", { name: "Excel" })).toHaveAttribute(
    "href",
    "/api/v1/purchasing-reports/rejected-stock/?over=1&export=xlsx",
  );
});

test("debit notes show the supplier's credit note, or how long we have waited for it", async () => {
  const row = {
    number: "DN26112501",
    date: "2026-11-10",
    supplier: "Inserts Lanka",
    invoice_id: 3,
    invoice: "INV-77",
    total_lkr: "1000.00",
  };
  mockApi({
    "GET /api/v1/purchasing-reports/debit-notes/": {
      body: [
        { ...row, credit_note: "", credit_note_date: null, days_waiting: 16 },
        { ...row, number: "DN26112502", credit_note: "SCN-0055", credit_note_date: "2026-11-26", days_waiting: null },
      ],
    },
  });
  renderAt("/purchasing/reports?tab=debitNotes", <PurchasingReportsPage />, "/purchasing/reports");
  const table = await screen.findByRole("table", { name: "Debit notes" });
  expect(within(table).getByText("Waiting, 16 days")).toBeInTheDocument();
  expect(within(table).getByText("SCN-0055 · 2026-11-26")).toBeInTheDocument();
  expect(within(table).getAllByRole("link", { name: "INV-77" })[0]).toHaveAttribute("href", "/supplier-invoices/3");
  expect(within(table.querySelector("tfoot tr") as HTMLElement).getByText("2,000.00")).toBeInTheDocument();
  expect(screen.getByLabelText("Only those still waiting")).not.toBeChecked();
});

test("the trail links every document of a PO", async () => {
  mockApi({
    "GET /api/v1/purchasing-reports/trail/?grn=4": {
      body: {
        po: { id: 9, label: "PO26110101", status: "Received", total_lkr: "10000.00", parent: null, revisions: [] },
        grns: [{ id: 4, number: "GRN26110101", date: "2026-11-01", status: "Confirmed" }],
        inspections: [
          { id: 7, grn: "GRN26110101", item: "M8-INSERT", status: "Decided", decision: "Accepted", accepted: "90", rejected: "10" },
        ],
        invoices: [
          {
            id: 3,
            number: "SI26110101",
            invoice_no: "INV-1",
            status: "Matched and posted",
            total_lkr: "9000.00",
            unpaid: "0.00",
            set_off: "0.00",
            debited: "0.00",
          },
        ],
        returns: [],
        vouchers: [
          {
            id: 12,
            number: "IM261101001",
            status: "Paid",
            amount: "9000.00",
            advance: false,
            payments: [{ number: "PY2611001", date: "2026-11-02", amount: "9000.00" }],
          },
        ],
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

// Testing T36 (21 Nov 2026): the Trail kept old statuses, and a held invoice read "LKR 0.00 unpaid".
test("the trail is read again when the document's status changes, and a held invoice is not payable yet", async () => {
  const body = {
    po: { id: 9, label: "PO26110805", status: "Received", total_lkr: "62400.00", parent: null, revisions: [] },
    grns: [],
    inspections: [],
    invoices: [
      {
        id: 3,
        number: "SI26112101",
        invoice_no: "PTL-7702",
        status: "Held: discrepancy",
        total_lkr: "62400.00",
        unpaid: "0.00",
        payable: false,
        set_off: "0.00",
        debited: "0.00",
      },
    ],
    returns: [],
    vouchers: [],
  };
  const calls = mockApi({ "GET /api/v1/purchasing-reports/trail/?invoice=3": { body } });
  function Page() {
    const [status, setStatus] = useState("held");
    return (
      <>
        <button type="button" onClick={() => setStatus("exception_requested")}>
          Ask for the exception
        </button>
        <Trail by="invoice" id={3} stamp={status} />
      </>
    );
  }
  renderAt("/", <Page />);
  const trail = await screen.findByRole("region", { name: "Trail" });
  expect(within(trail).getByText(/Held: discrepancy, LKR 62,400.00, not payable yet/)).toBeInTheDocument();
  expect(within(trail).queryByText(/unpaid/)).not.toBeInTheDocument();
  const reads = () => calls.mock.calls.filter(([url]) => String(url).includes("/trail/")).length;
  expect(reads()).toBe(1);
  fireEvent.click(screen.getByRole("button", { name: "Ask for the exception" }));
  await waitFor(() => expect(reads()).toBe(2));
});
