import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { ApprovalMatrix } from "../../api/approvals";
import type { CurrentUser } from "../../api/auth";
import { mockApi, renderAt, sampleUser } from "../../test-utils";
import ApprovalMatrixPage from "./ApprovalMatrixPage";

const admin: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["enter", "manage", "view"] }, actions: [], divisions: "all" },
};

const accountant: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["view"] }, actions: [], divisions: "all" },
};

const rule = (id: number, level: number, code: string, name: string) => ({
  id,
  document_type: "voucher",
  level,
  role: { code, name },
  min_amount: null,
  max_amount: null,
  division: null,
  subtype: "",
  is_active: true,
  created_at: "2026-10-29T00:00:00Z",
});

const matrix: ApprovalMatrix = {
  document_types: [
    { code: "voucher", name: "Payment voucher", min_approvals: 2, final_role: "director", subtype_label: "Voucher type" },
  ],
  rules: [rule(1, 2, "accountant", "Accountant"), rule(2, 3, "director", "Director")],
  roles: [
    { code: "accountant", name: "Accountant" },
    { code: "director", name: "Director" },
  ],
};

test("the Admin sees the voucher route and adds a rule for large amounts", async () => {
  const calls = mockApi({
    "GET /api/v1/settings/approval-matrix/": { body: matrix },
    "GET /api/v1/settings/approval-reminders/": { body: [] },
    "POST /api/v1/settings/approval-matrix/": { status: 201, body: matrix },
  });
  renderAt("/settings/approval-matrix", <ApprovalMatrixPage me={admin} />);

  const table = await screen.findByRole("table", { name: "Approval rules: Payment voucher" });
  expect(within(table).getAllByText("Every document")).toHaveLength(2);
  const form = screen.getByRole("form", { name: "Add rule" });
  await within(form).findByRole("option", { name: "Director" });
  fireEvent.change(within(form).getByLabelText("Approved by"), { target: { value: "director" } });
  fireEvent.change(within(form).getByLabelText("From amount (optional)"), { target: { value: "1000000" } });
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "big payments" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add rule" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/settings/approval-matrix/", expect.objectContaining({ method: "POST" })),
  );
  const [, init] = calls.mock.calls.find(([, i]) => i?.method === "POST")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    document_type: "voucher",
    level: 2,
    role: "director",
    min_amount: "1000000",
    max_amount: null,
    reason: "big payments",
  });
});

test("others see the matrix read-only and can check a document's route", async () => {
  mockApi({
    "GET /api/v1/settings/approval-matrix/": { body: matrix },
    "GET /api/v1/settings/approval-reminders/": { body: [] },
    "GET /api/v1/settings/approval-matrix/route/?document_type=voucher&amount=5000": {
      body: [
        { level: 2, role: "accountant", role_name: "Accountant" },
        { level: 3, role: "director", role_name: "Director" },
      ],
    },
  });
  renderAt("/settings/approval-matrix", <ApprovalMatrixPage me={accountant} />);

  await screen.findByRole("table", { name: "Approval rules: Payment voucher" });
  expect(screen.queryByRole("form", { name: "Add rule" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Switch off" })).not.toBeInTheDocument();
  const check = screen.getByRole("form", { name: "Check route" });
  fireEvent.change(within(check).getByLabelText("Amount"), { target: { value: "5000" } });
  fireEvent.click(within(check).getByRole("button", { name: "Check route" }));
  expect(await within(check).findByRole("status")).toHaveTextContent(
    "L1 Submitter → L2 Accountant → L3 Director",
  );
});
