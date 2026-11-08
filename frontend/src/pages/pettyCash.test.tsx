import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { PettyFloat } from "../api/pettyCash";
import { mockApi, renderAt } from "../test-utils";
import PettyCashPage from "./PettyCashPage";

const box: PettyFloat = {
  id: 4,
  code: "PC-WS",
  name: "Workshop petty cash",
  custodian: "Sunil",
  division: "WS",
  can_record: true,
  float: "10000.00",
  spent: "0.00",
  not_on_voucher: "0.00",
  cash_in_hand: "10000.00",
};

test("the custodian records an expense with its slip", async () => {
  const calls = mockApi({
    "GET /api/v1/petty-cash/": { body: [box] },
    "GET /api/v1/petty-cash/4/expenses/": { body: { float: box, expenses: [] } },
    "GET /api/v1/payees/": { body: [] },
    "POST /api/v1/petty-cash/4/expenses/": { status: 201, body: {} },
  });
  renderAt("/petty-cash", <PettyCashPage />);
  const form = await screen.findByRole("form", { name: "Record an expense" });
  expect(screen.getByText("10,000.00", { selector: "strong" })).toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Paid to"), { target: { value: "Hardware shop" } });
  fireEvent.change(within(form).getByLabelText("What for"), { target: { value: "Bolts" } });
  fireEvent.change(within(form).getByLabelText("Amount (LKR)"), { target: { value: "250.00" } });
  const file = new File(["%PDF-1.4"], "slip.pdf", { type: "application/pdf" });
  fireEvent.change(within(form).getByLabelText("Slip (photo or PDF)"), { target: { files: [file] } });
  fireEvent.click(within(form).getByRole("button", { name: "Save the expense" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/petty-cash/4/expenses/", expect.objectContaining({ method: "POST" })));
});
