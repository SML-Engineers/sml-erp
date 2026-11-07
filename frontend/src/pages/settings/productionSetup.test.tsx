import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { ProductionSetup } from "../../api/productionSetup";
import { mockApi, renderAt } from "../../test-utils";
import ProductionSetupPage from "./ProductionSetupPage";

const setup: ProductionSetup = {
  reasons: [
    { id: 1, division: "IM", kind: "downtime", code: "MOULD-CHANGE", name: "Mould change", planned: false, is_active: true, sort_order: 20, in_use: false },
    { id: 2, division: "IM", kind: "downtime", code: "PLANNED-PM", name: "Planned maintenance", planned: true, is_active: true, sort_order: 80, in_use: false },
    { id: 3, division: "IM", kind: "reject", code: "FLASH", name: "Flash", planned: false, is_active: true, sort_order: 20, in_use: true },
    { id: 4, division: "WS", kind: "downtime", code: "SETUP", name: "Setting up", planned: false, is_active: true, sort_order: 20, in_use: false },
  ],
  divisions: ["IM", "WS"],
  settings: [
    { id: 1, effective_from: "2026-01-01", grace_hours: "4.0", reject_alert_pct: "5.00", overrun_alert_pct: "10.00", min_margin_pct: "", reason: "Owner's answers", created_by: "", in_force: true },
  ],
  current: 1,
  can_manage: true,
};

test("the limits in force are shown and changed from a date", async () => {
  const calls = mockApi({
    "GET /api/v1/production-setup/": { body: setup },
    "POST /api/v1/production-setup/": { body: setup },
  });
  renderAt("/settings/production", <ProductionSetupPage />);
  expect(
    await screen.findByText(/4.0 hours to enter or change a shift after it ends; alert at 5.00% rejects and 10.00% cost overrun; minimum margin as on the order's quotation/),
  ).toBeInTheDocument();
  const form = screen.getByRole("form", { name: "Change from a date" });
  fireEvent.change(within(form).getByLabelText("Grace period after a shift (hours)"), { target: { value: "3" } });
  fireEvent.change(within(form).getByLabelText("Reason for the change"), { target: { value: "Review" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/production-setup/",
      expect.objectContaining({
        body: JSON.stringify({
          effective_from: "", grace_hours: "3", reject_alert_pct: "5.00", overrun_alert_pct: "10.00", min_margin_pct: "", reason: "Review",
        }),
      }),
    ),
  );
});

test("reasons are listed per division and kind, and switched off", async () => {
  const calls = mockApi({
    "GET /api/v1/production-setup/": { body: setup },
    "PATCH /api/v1/production-reasons/1/": { body: setup },
    "POST /api/v1/production-reasons/": { body: setup },
  });
  renderAt("/settings/production", <ProductionSetupPage />);
  const table = await screen.findByRole("table", { name: "Reject and downtime reasons" });
  expect(within(table).getByText("MOULD-CHANGE")).toBeInTheDocument();
  expect(within(table).getByRole("checkbox", { name: "PLANNED-PM is a planned stop" })).toBeChecked();
  expect(within(table).queryByText("FLASH")).not.toBeInTheDocument();
  fireEvent.click(within(table).getByRole("checkbox", { name: "MOULD-CHANGE is active" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/production-reasons/1/", expect.objectContaining({ body: JSON.stringify({ is_active: false }) })),
  );
  fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "reject" } });
  expect(within(table).getByText("FLASH")).toBeInTheDocument();
  const add = screen.getByRole("form", { name: "Add reason" });
  fireEvent.change(within(add).getByLabelText("Code"), { target: { value: "GATE" } });
  fireEvent.change(within(add).getByLabelText("Name"), { target: { value: "Gate mark" } });
  fireEvent.click(within(add).getByRole("button", { name: "Add reason" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/production-reasons/",
      expect.objectContaining({ body: JSON.stringify({ division: "IM", kind: "reject", code: "GATE", name: "Gate mark", planned: false }) }),
    ),
  );
});
