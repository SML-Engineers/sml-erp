import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { ReceivedCheque } from "../api/cheques";
import { mockApi, renderAt } from "../test-utils";
import ChequesPage from "./ChequesPage";

const cheque: ReceivedCheque = {
  id: 4,
  number: "RC26110004",
  customer: { id: 5, name: "Lanka Tiles PLC" },
  reference: "004512",
  cheque_bank: "Sampath Bank",
  cheque_date: "2026-11-03",
  receipt_date: "2026-11-03",
  currency: "LKR",
  amount: "20000.00",
  amount_lkr: "20000.00",
  status: "in_hand",
  deposit: null,
  cleared_on: null,
  returned_on: null,
  return_reason: "",
};

test("the cashier puts customers' cheques on a deposit slip", async () => {
  const calls = mockApi({
    "GET /api/v1/cheques/received/?status=in_hand": { body: [cheque] },
    "GET /api/v1/cheques/received/": { body: [cheque] },
    "GET /api/v1/deposits/": { body: [] },
    "GET /api/v1/payments/accounts/": {
      body: [
        { id: 2, code: "COM-CUR", name: "Commercial Bank current", kind: "current", currency: "LKR", has_ledger: true, next_cheque: null },
      ],
    },
    "POST /api/v1/deposits/": (sent) => ({
      status: 201,
      body: {
        id: 1,
        number: "DP26110001",
        account: { id: 2, code: "COM-CUR", name: "x" },
        deposit_date: (sent as { deposit_date: string }).deposit_date,
        slip_no: "",
        total: "20000.00",
        journal_entry: "JE1",
        created_by: "Kamal",
        cheques: [],
      },
    }),
  });
  renderAt("/cheques", <ChequesPage />);
  const slip = await screen.findByRole("region", { name: "Make a deposit slip" });
  fireEvent.click(await within(slip).findByLabelText(/RC26110004/));
  fireEvent.change(within(slip).getByLabelText("Bank account"), { target: { value: "2" } });
  expect(within(slip).getByText("Total 20,000.00")).toBeInTheDocument();
  fireEvent.click(within(slip).getByRole("button", { name: "Record the deposit" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/deposits/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/deposits/" && i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({ account: 2, receipts: [4] });
});
