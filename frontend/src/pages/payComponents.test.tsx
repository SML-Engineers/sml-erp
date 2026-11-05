import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { PayComponentList } from "../api/pay";
import { mockApi, renderAt } from "../test-utils";
import PayComponentsPage from "./PayComponentsPage";

const list: PayComponentList = {
  can_manage: true,
  results: [
    { id: 1, code: "BASIC", name: "Basic salary", kind: "earning", basis: "fixed", epf_liable: true, apit_taxable: true, is_allowance: false, sort_order: 10, is_active: true },
    { id: 6, code: "WELFARE", name: "Welfare society", kind: "deduction", basis: "fixed", epf_liable: false, apit_taxable: false, is_allowance: false, sort_order: 10, is_active: true },
  ],
};

test("HR adds a component; a deduction cannot count for EPF", async () => {
  const calls = mockApi({
    "GET /api/v1/pay-components/": { body: list },
    "POST /api/v1/pay-components/": { body: list.results[0] },
  });
  renderAt("/pay-components", <PayComponentsPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Add a component" }));
  fireEvent.change(screen.getByLabelText("Code"), { target: { value: "meal" } });
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Meal allowance" } });
  fireEvent.click(screen.getByLabelText("APIT"));
  fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "deduction" } });
  expect(screen.getByLabelText("APIT")).toBeDisabled();
  expect(screen.getByLabelText("APIT")).not.toBeChecked();
  fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "earning" } });
  fireEvent.click(screen.getByLabelText("APIT"));
  fireEvent.click(screen.getByLabelText("Allowance"));
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/pay-components/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          code: "MEAL", name: "Meal allowance", kind: "earning", basis: "fixed", epf_liable: false,
          apit_taxable: true, is_allowance: true, sort_order: 100, is_active: true,
        }),
      }),
    ),
  );
});

test("changing a component asks for a reason and sends only what changed", async () => {
  const calls = mockApi({
    "GET /api/v1/pay-components/": { body: list },
    "PATCH /api/v1/pay-components/1/": { body: list.results[0] },
  });
  renderAt("/pay-components", <PayComponentsPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Change BASIC" }));
  fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Basic wage" } });
  fireEvent.change(screen.getByLabelText("Reason for the change"), { target: { value: "Wages Board wording" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/pay-components/1/",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ name: "Basic wage", reason: "Wages Board wording" }) }),
    ),
  );
});
