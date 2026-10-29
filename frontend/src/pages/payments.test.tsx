import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";

import type { CurrentUser } from "../api/auth";
import type { PayAccount, Payment, ToPayRow } from "../api/payments";
import { mockApi, renderAt, sampleUser } from "../test-utils";
import PaymentsPage from "./PaymentsPage";
import PayPage from "./PayPage";

const cashier: CurrentUser = {
  ...sampleUser,
  access: { areas: { vouchers: ["view"], payments: ["enter", "view"] }, actions: ["record_payment"], divisions: "all" },
};

const row = (over: Partial<ToPayRow> = {}): ToPayRow => ({
  id: 1,
  number: "WS261029001",
  status: "partly_paid",
  voucher_type: { code: "ADV", name: "Supplier Advance" },
  division: "WS",
  payee: { id: 3, name: "Lanka Steel" },
  transfer_to: null,
  voucher_date: "2026-10-29",
  total_amount: "1000.00",
  paid: "400.00",
  remaining: "600.00",
  methods: ["cheque", "transfer", "card", "qr"],
  suggested_account: 2,
  ...over,
});

const accounts: PayAccount[] = [
  { id: 1, code: "SAMP-SAV", name: "Sampath savings", kind: "savings", currency: "LKR", has_ledger: true, next_cheque: null },
  { id: 2, code: "COM-CUR", name: "Commercial current", kind: "current", currency: "LKR", has_ledger: true, next_cheque: "000123" },
  { id: 3, code: "CASH", name: "Cash on hand", kind: "cash", currency: "LKR", has_ledger: true, next_cheque: null },
];

const payment: Payment = {
  id: 9,
  number: "PY26100001",
  voucher: { id: 1, number: "WS261029001" },
  payee: "Lanka Steel",
  account: { id: 2, code: "COM-CUR", name: "Commercial current" },
  method: "cheque",
  reference: "000123",
  cheque_date: null,
  payment_date: "2026-10-29",
  amount: "600.00",
  journal_entry: "JV26100007",
  notes: "",
  created_by: "Sunil",
  created_at: "2026-10-29T10:00:00Z",
};

test("the Cashier sees what is left to pay and the payments made", async () => {
  mockApi({
    "GET /api/v1/payments/to-pay/": { body: [row()] },
    "GET /api/v1/payments/": { body: [payment] },
  });
  renderAt("/payments", <PaymentsPage me={cashier} />);

  const toPay = await screen.findByRole("table", { name: "To pay" });
  expect(within(toPay).getAllByText("600.00").length).toBeGreaterThan(0);
  expect(within(toPay).getByRole("link", { name: "Pay" })).toHaveAttribute("href", "/payments/new?voucher=1");
  const made = await screen.findByRole("table", { name: "Payments made" });
  expect(within(made).getByText("JV26100007")).toBeInTheDocument();
});

test("a cheque payment: next cheque and the division's account filled in, then printed", async () => {
  const calls = mockApi({
    "GET /api/v1/payments/to-pay/": { body: [row()] },
    "GET /api/v1/payments/accounts/": { body: accounts },
    "POST /api/v1/payments/": { status: 201, body: payment },
  });
  const open = vi.spyOn(window, "open").mockImplementation(() => null);
  renderAt("/payments/new?voucher=1", <PayPage />, "/payments/new");

  const form = await screen.findByRole("form", { name: "Record a payment" });
  expect(form).toHaveTextContent("left to pay 600.00");
  expect(within(form).getByLabelText("Paid from")).toHaveValue("2");
  expect(within(form).getByLabelText("Cheque number")).toHaveValue("000123");
  expect(within(form).getByLabelText("Amount (LKR)")).toHaveValue("600.00");
  // Cheques are written on current accounts only.
  expect(within(within(form).getByLabelText("Paid from")).queryByText(/Sampath savings/)).not.toBeInTheDocument();
  fireEvent.click(within(form).getByRole("button", { name: "Save payment" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/payments/", expect.objectContaining({ method: "POST" })),
  );
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    voucher: 1,
    account: 2,
    method: "cheque",
    amount: "600.00",
    cheque_number: "000123",
    reference: "",
  });
  const done = await screen.findByRole("status", { name: "Payment saved" });
  expect(done).toHaveTextContent("PY26100001");
  expect(done).toHaveTextContent("JV26100007");
  fireEvent.click(within(done).getByRole("button", { name: "Print payment voucher" }));
  expect(open).toHaveBeenCalledWith("/api/v1/vouchers/1/print/?paper=A4", "_blank", "noopener");
  open.mockRestore();
});

test("a QR payment needs its reference and can come from a savings account", async () => {
  const calls = mockApi({
    "GET /api/v1/payments/to-pay/": { body: [row()] },
    "GET /api/v1/payments/accounts/": { body: accounts },
    "POST /api/v1/payments/": { status: 201, body: { ...payment, method: "qr", reference: "LQR-55" } },
  });
  renderAt("/payments/new?voucher=1", <PayPage />, "/payments/new");

  const form = await screen.findByRole("form", { name: "Record a payment" });
  fireEvent.change(within(form).getByLabelText("Method"), { target: { value: "qr" } });
  expect(within(form).queryByLabelText("Cheque number")).not.toBeInTheDocument();
  const reference = within(form).getByLabelText("Reference");
  expect(reference).toBeRequired();
  fireEvent.change(within(form).getByLabelText("Paid from"), { target: { value: "1" } });
  fireEvent.change(reference, { target: { value: "LQR-55" } });
  fireEvent.change(within(form).getByLabelText("Amount (LKR)"), { target: { value: "250.00" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save payment" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/payments/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    account: 1,
    method: "qr",
    amount: "250.00",
    reference: "LQR-55",
    cheque_number: null,
  });
});

test("a voucher that is not waiting to be paid cannot be paid here", async () => {
  mockApi({
    "GET /api/v1/payments/to-pay/": { body: [] },
    "GET /api/v1/payments/accounts/": { body: accounts },
  });
  renderAt("/payments/new?voucher=5", <PayPage />, "/payments/new");
  expect(await screen.findByRole("alert")).toHaveTextContent("not waiting to be paid");
  expect(screen.queryByRole("form")).not.toBeInTheDocument();
});
