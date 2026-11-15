import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { AccessToConfirm } from "../../api/admin";
import { mockApi, renderAt } from "../../test-utils";
import AccessToConfirmPage from "./AccessToConfirmPage";

const waiting: AccessToConfirm = {
  can_confirm: true,
  roles: [
    {
      id: 4,
      user_id: 7,
      user: "Rashani Perera",
      email: "rashani@sml.lk",
      code: "production_team_leader",
      name: "Production Team Leader",
      reason: "New job",
      conflict_warning: "",
      requested_by: "Peduru Somarathna",
      requested_by_id: 2,
      requested_at: "2026-11-15T10:00:00Z",
      mine: false,
    },
  ],
  grants: [],
  resets: [],
};

test("the Director confirms a new role (owner, 15 Nov 2026)", async () => {
  const calls = mockApi({
    "GET /api/v1/access-to-confirm/": { body: waiting },
    "POST /api/v1/role-requests/4/confirm/": { body: { ...waiting.roles[0] } },
  });
  renderAt("/admin/access-to-confirm", <AccessToConfirmPage />);
  const roles = await screen.findByRole("region", { name: "New roles" });
  const row = within(roles).getAllByRole("row")[1];
  expect(row).toHaveTextContent("Rashani Perera");
  expect(row).toHaveTextContent("Production Team Leader");
  expect(row).toHaveTextContent("Peduru Somarathna");
  fireEvent.click(within(row).getByRole("button", { name: "Confirm" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Production Team Leader confirmed for Rashani Perera");
  expect(calls).toHaveBeenCalledWith("/api/v1/role-requests/4/confirm/", expect.objectContaining({ method: "POST" }));
});

test("refusing needs a reason; nobody decides what they asked for", async () => {
  const calls = mockApi({
    "GET /api/v1/access-to-confirm/": {
      body: { ...waiting, roles: [...waiting.roles, { ...waiting.roles[0], id: 5, user: "Me Myself", mine: true }] },
    },
    "POST /api/v1/role-requests/4/refuse/": { body: waiting.roles[0] },
  });
  renderAt("/admin/access-to-confirm", <AccessToConfirmPage />);
  const roles = await screen.findByRole("region", { name: "New roles" });
  const [, first, second] = within(roles).getAllByRole("row");
  expect(within(second).queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
  expect(second).toHaveTextContent("Someone else decides this");
  fireEvent.click(within(first).getByRole("button", { name: "Refuse" }));
  const refuse = within(first).getByRole("button", { name: "Refuse" });
  expect(refuse).toBeDisabled();
  fireEvent.change(within(first).getByLabelText("Reason for refusing"), { target: { value: "Not her job" } });
  fireEvent.click(refuse);
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/role-requests/4/refuse/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ reason: "Not her job" }) }),
    ),
  );
});
