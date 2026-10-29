import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { CurrentUser } from "../../api/auth";
import { mockApi, renderAt, sampleUser } from "../../test-utils";
import ApprovalMatrixPage from "./ApprovalMatrixPage";

const admin: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["manage", "enter", "view"] }, actions: [], divisions: "all" },
};
const director: CurrentUser = {
  ...sampleUser,
  access: { areas: { settings: ["view"] }, actions: [], divisions: "all" },
};

const reminders = [
  { document_type: "voucher", name: "Payment voucher", enabled: true, after_days: 3 },
  { document_type: "voucher_cancellation", name: "Voucher cancellation", enabled: true, after_days: 3 },
];

const api = (extra = {}) => ({
  "GET /api/v1/settings/approval-matrix/": { body: { document_types: [], rules: [], roles: [] } },
  "GET /api/v1/settings/approval-reminders/": { body: reminders },
  ...extra,
});

test("the Admin changes after how many days approvers are reminded", async () => {
  const calls = mockApi(
    api({ "PUT /api/v1/settings/approval-reminders/": { body: [{ ...reminders[0], after_days: 5 }, reminders[1]] } }),
  );
  renderAt("/settings/approval-matrix", <ApprovalMatrixPage me={admin} />);

  const row = await screen.findByRole("group", { name: "Payment voucher" });
  const save = within(row).getByRole("button", { name: "Save" });
  expect(save).toBeDisabled(); // nothing changed yet
  fireEvent.change(within(row).getByLabelText("after days"), { target: { value: "5" } });
  fireEvent.click(save);
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/settings/approval-reminders/",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ document_type: "voucher", enabled: true, after_days: 5, reason: "" }),
      }),
    ),
  );
});

test("others see the reminders but cannot change them", async () => {
  mockApi(api());
  renderAt("/settings/approval-matrix", <ApprovalMatrixPage me={director} />);

  const row = await screen.findByRole("group", { name: "Voucher cancellation" });
  expect(within(row).getByLabelText("Remind")).toBeDisabled();
  expect(within(row).getByLabelText("after days")).toBeDisabled();
  expect(within(row).queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
});
