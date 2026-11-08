import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../api/auth";
import type { ReturnDetail } from "../api/supplierReturns";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import SupplierReturnPage from "./SupplierReturnPage";
import SupplierReturnsPage from "./SupplierReturnsPage";

const stores: CurrentUser = { ...sampleUser, access: { areas: { stores: ["enter", "view"] }, actions: [], divisions: "all" } };

const made: ReturnDetail = {
  id: 2,
  number: "RTN26110201",
  kind: "accepted",
  status: "awaiting_approval",
  return_date: "2026-11-02",
  division: "IM",
  supplier: { id: 1, code: "S0001", name: "Inserts Lanka" },
  grn: { id: 4, number: "GRN26110101" },
  reason: "Threads stripped",
  created_by: "Stores",
  vehicle_no: "",
  confirmed_at: null,
  journal: null,
  lines: [
    {
      line_no: 1,
      grn_line: 40,
      lot_no: "GRN26110101-1",
      item: { code: "M8-INSERT", name: "Insert", unit: "pcs" },
      quantity: "10.000",
      uninvoiced_quantity: "0.000",
      invoiced_quantity: "0.000",
      value: "0.00",
    },
  ],
  debit_notes: [],
  available: [],
  can_edit: false,
  can_approve: true,
  history: [],
};

test("the stores person returns a rejected lot", async () => {
  const calls = mockApi({
    "GET /api/v1/supplier-returns/": { body: [] },
    "GET /api/v1/goods-receipts/?status=confirmed": {
      body: [
        {
          id: 4,
          number: "GRN26110101",
          receipt_date: "2026-11-01",
          status: "confirmed",
          division: "IM",
          store: "IM-QUAR",
          purchase_order: { id: 9, label: "PO26110101" },
          supplier: { id: 1, code: "S0001", name: "Inserts Lanka" },
          delivery_note_no: "",
          created_by: "Stores",
        },
      ],
    },
    "GET /api/v1/supplier-returns/lots/?grn=4&kind=rejected": {
      body: [
        {
          grn_line: 40,
          lot_no: "GRN26110101-1",
          item: { code: "M8-INSERT", name: "Insert", unit: "pcs" },
          quantity: "20.000",
          value: "0.00",
        },
      ],
    },
    "POST /api/v1/supplier-returns/": { status: 201, body: { ...made, kind: "rejected", status: "draft" } },
  });
  renderAt("/supplier-returns", <SupplierReturnsPage me={stores} />);
  fireEvent.click(await screen.findByRole("button", { name: "Return goods to a supplier" }));
  const form = screen.getByRole("form", { name: "Return goods" });
  const grn = within(form).getByLabelText("GRN number");
  await within(grn).findByRole("option", { name: "GRN26110101 · Inserts Lanka" });
  fireEvent.change(grn, { target: { value: "4" } });
  fireEvent.change(await within(form).findByLabelText("To return, lot GRN26110101-1"), { target: { value: "20" } });
  fireEvent.change(within(form).getByLabelText("Why the goods are returned"), { target: { value: "Rejected by QC" } });
  fireEvent.click(within(form).getByRole("button", { name: "Make the return" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/supplier-returns/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/supplier-returns/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    grn: 4,
    kind: "rejected",
    reason: "Rejected by QC",
    lines: [{ grn_line: 40, lot_no: "GRN26110101-1", quantity: "20" }],
  });
});

test("the Director approves a return of accepted goods and sees the debit note", async () => {
  const calls = mockApi({
    "GET /api/v1/supplier-returns/2/": { body: made },
    "POST /api/v1/supplier-returns/2/approve/": {
      body: {
        ...made,
        status: "confirmed",
        can_approve: false,
        journal: "JE26110009",
        debit_notes: [{ number: "DN26110201", invoice: { id: 3, invoice_no: "INV-1" }, quantity: "10.000", total_lkr: "1000.00" }],
      },
    },
  });
  renderAt("/supplier-returns/2", <SupplierReturnPage />, "/supplier-returns/:id");
  fireEvent.click(await screen.findByRole("button", { name: "Approve the return" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/supplier-returns/2/approve/", expect.objectContaining({ method: "POST" })),
  );
  expect(await screen.findByText(/DN26110201: LKR 1,000.00 for 10 returned/)).toBeInTheDocument();
});
