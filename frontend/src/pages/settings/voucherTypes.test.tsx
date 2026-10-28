import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../../api/auth";
import type { VoucherType } from "../../api/vouchers";
import { mockApi, renderAt, sampleUser } from "../../test-utils";
import VoucherTypesPage from "./VoucherTypesPage";

const admin: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["enter", "manage", "view"] }, actions: [], divisions: "all" },
};

const accountant: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["view"] }, actions: [], divisions: "all" },
};

const cheque: VoucherType = {
  id: 1,
  code: "CHQ",
  name: "Cheque Payment",
  payment_method: "cheque",
  needs_payee: true,
  payee_category: "",
  is_advance: false,
  notes: "",
  sort_order: 10,
  is_active: true,
  in_use: true,
};

const internal: VoucherType = {
  ...cheque,
  id: 4,
  code: "INT",
  name: "Internal Transfer",
  payment_method: "internal",
  needs_payee: false,
  in_use: false,
};

test("the Admin adds a type; an internal transfer has no payee", async () => {
  const calls = mockApi({
    "GET /api/v1/voucher-types/": { body: [cheque, internal] },
    "POST /api/v1/voucher-types/": { status: 201, body: { ...cheque, id: 9, code: "CCP" } },
  });
  renderAt("/settings/voucher-types", <VoucherTypesPage me={admin} />);

  const table = await screen.findByRole("table", { name: "Voucher types" });
  expect(within(table).getByText("No payee")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Add voucher type" }));
  const form = screen.getByRole("form", { name: "Voucher type details" });
  fireEvent.change(within(form).getByLabelText("Code"), { target: { value: "CCP" } });
  fireEvent.change(within(form).getByLabelText("Name"), { target: { value: "Credit Card Payment" } });
  fireEvent.change(within(form).getByLabelText("Paid by"), { target: { value: "internal" } });
  expect(within(form).queryByLabelText("Payee")).not.toBeInTheDocument();
  fireEvent.change(within(form).getByLabelText("Paid by"), { target: { value: "transfer" } });
  fireEvent.change(within(form).getByLabelText("Payee"), { target: { value: "bank_card" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add voucher type" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/voucher-types/", expect.objectContaining({ method: "POST" })),
  );
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    code: "CCP",
    name: "Credit Card Payment",
    payment_method: "transfer",
    needs_payee: true,
    payee_category: "bank_card",
  });
});

test("a used type keeps its code; others only view the types", async () => {
  mockApi({ "GET /api/v1/voucher-types/": { body: [cheque, internal] } });
  renderAt("/settings/voucher-types", <VoucherTypesPage me={accountant} />);

  fireEvent.click(await screen.findByRole("button", { name: "CHQ" }));
  const panel = screen.getByRole("region", { name: "CHQ Cheque Payment" });
  expect(within(panel).getByText(/has been used on vouchers/)).toBeInTheDocument();
  expect(within(panel).getByLabelText("Code")).toBeDisabled();
  expect(within(panel).getByLabelText("Name")).toBeDisabled();
  expect(within(panel).queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Add voucher type" })).not.toBeInTheDocument();
});
