import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { PasswordResetRow } from "../api/admin";
import { mockApi, renderAt } from "../test-utils";
import PasswordResetPanel from "./PasswordResetPanel";

const waiting: PasswordResetRow = {
  id: 3, status: "waiting", with_authenticator: true, reason: "Lost phone", requested_by: "Peduru Somarathna",
  requested_at: "2026-10-31T21:20:00", decided_by: null, decided_at: null, decision_reason: "", issued_at: null,
  can_decide: false, can_issue: false,
};

test("the Admin asks for a reset, then makes the temporary password once approved", async () => {
  let listed = { can_request: true, resets: [] as PasswordResetRow[] };
  const calls = mockApi({
    "GET /api/v1/users/7/password-resets/": () => ({ body: listed }),
    "POST /api/v1/users/7/password-resets/": () => {
      listed = { can_request: true, resets: [{ ...waiting, status: "approved", can_issue: true }] };
      return { status: 201, body: waiting };
    },
    "POST /api/v1/password-resets/3/issue/": { body: { ...waiting, status: "done", temporary_password: "Tmp-77abc" } },
  });
  renderAt("/admin/users/7", <PasswordResetPanel userId={7} name="Nimal Perera" />, "/admin/users/:id");
  const panel = await screen.findByRole("region", { name: "Password reset" });
  fireEvent.change(within(panel).getByLabelText("Reason"), { target: { value: "Lost phone" } });
  fireEvent.click(within(panel).getByLabelText("Also reset the authenticator (lost phone)"));
  fireEvent.click(within(panel).getByRole("button", { name: "Request a password reset" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/users/7/password-resets/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "Lost phone", with_authenticator: true }) }),
    ),
  );
  fireEvent.click(await within(panel).findByRole("button", { name: "Make the new temporary password" }));
  expect(await within(panel).findByText("Tmp-77abc")).toBeInTheDocument();
});

test("the Director approves or refuses a waiting reset", async () => {
  const calls = mockApi({
    "GET /api/v1/users/7/password-resets/": { body: { can_request: false, resets: [{ ...waiting, can_decide: true }] } },
    "POST /api/v1/password-resets/3/refuse/": { body: { ...waiting, status: "refused" } },
  });
  renderAt("/admin/users/7", <PasswordResetPanel userId={7} name="Nimal Perera" />, "/admin/users/:id");
  const panel = await screen.findByRole("region", { name: "Password reset" });
  expect(within(panel).getByRole("button", { name: "Approve the reset" })).toBeInTheDocument();
  expect(within(panel).queryByRole("button", { name: "Request a password reset" })).not.toBeInTheDocument();
  fireEvent.change(within(panel).getByLabelText("Reason (needed to refuse)"), { target: { value: "Call me first" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Refuse" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/password-resets/3/refuse/",
      expect.objectContaining({ body: JSON.stringify({ reason: "Call me first" }) }),
    ),
  );
});
