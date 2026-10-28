import { fireEvent, screen } from "@testing-library/react";

import { mockApi, renderAt } from "../../test-utils";
import AuditLogPage from "./AuditLogPage";

const row = {
  id: 1,
  occurred_at: "2026-10-28T09:15:00Z",
  actor_email: "admin@sml.lk",
  ip_address: "10.0.0.5",
  action: "update",
  object_type: "core.accessoverride",
  object_id: "4",
  object_repr: "grant record_payment for 7",
  related_user: 7,
  related_user_email: "clerk@sml.lk",
  event: "access_confirmed",
  reason: "",
  changes: { confirmed_by: [null, "Director <director@sml.lk>"] },
};

test("shows who changed what, with old and new values", async () => {
  mockApi({ "GET /api/v1/audit/": { body: [row] } });
  renderAt("/admin/audit", <AuditLogPage />);

  expect(await screen.findByText("Access confirmed by the Director")).toBeInTheDocument();
  expect(screen.getByText("admin@sml.lk")).toBeInTheDocument();
  expect(screen.getByText("10.0.0.5")).toBeInTheDocument();
  expect(screen.getByText(/— → Director <director@sml.lk>/)).toBeInTheDocument();
});

test("filters by person and dates", async () => {
  const api = mockApi({
    "GET /api/v1/audit/": { body: [row] },
    "GET /api/v1/audit/?actor=admin%40sml.lk&from=2026-10-01": { body: [] },
  });
  renderAt("/admin/audit", <AuditLogPage />);
  await screen.findByText("admin@sml.lk");

  fireEvent.change(screen.getByLabelText("Who"), { target: { value: "admin@sml.lk" } });
  fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-10-01" } });
  fireEvent.click(screen.getByRole("button", { name: "Show" }));

  expect(await screen.findByText("Nothing recorded yet.")).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith(
    "/api/v1/audit/?actor=admin%40sml.lk&from=2026-10-01",
    expect.anything(),
  );
});
