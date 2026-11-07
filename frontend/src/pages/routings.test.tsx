import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { Routing, RoutingList } from "../api/routings";
import { mockApi, renderAt } from "../test-utils";
import RoutingsPage from "./RoutingsPage";

const routing: Routing = {
  id: 5, item: "SH-100", item_name: "Drive shaft", revision: 1, drawing_revision: "B", status: "awaiting",
  status_label: "Waiting for approval", notes: "", created_by: "Planner", approved_at: null, setup_min: "35", run_min: "14.75",
  subcontract_cost: "450.00", returned_reason: null, can_edit: false, can_decide: true,
  operations: [
    { seq: 10, name: "Turn", section: "M-LAT", section_name: "Manual Lathe", machine: "M-LAT-01", setup_min: "30", run_min: "12.25", subcontract: false, supplier: "", subcontract_cost: "", notes: "" },
    { seq: 20, name: "Hard chrome", section: "", machine: "", setup_min: "0", run_min: "0", subcontract: true, supplier: "S0100", supplier_name: "Ceylon Platers", subcontract_cost: "450.00", notes: "" },
  ],
};
const list: RoutingList = { results: [routing], can_prepare: true, statuses: [{ value: "approved", label: "Approved" }] };

test("the Production Manager opens a routing and approves it", async () => {
  const calls = mockApi({
    "GET /api/v1/routings/?q=&status=": { body: list },
    "POST /api/v1/routings/5/approve/": { body: { ...routing, status: "approved", status_label: "Approved", can_decide: false } },
  });
  renderAt("/routings", <RoutingsPage />);
  fireEvent.click(await screen.findByRole("button", { name: "SH-100" }));
  const panel = screen.getByRole("region", { name: "Routing SH-100 rev 1" });
  expect(within(panel).getByText("Manual Lathe · M-LAT-01")).toBeInTheDocument();
  expect(within(panel).getByText("Subcontracted to Ceylon Platers, LKR 450.00 a piece")).toBeInTheDocument();
  fireEvent.click(within(panel).getByRole("button", { name: "Approve" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith("/api/v1/routings/5/approve/", expect.objectContaining({ method: "POST" })),
  );
});

test("the planner drafts a routing with a subcontracted operation", async () => {
  const calls = mockApi({
    "GET /api/v1/routings/?q=&status=": { body: { ...list, results: [] } },
    "POST /api/v1/routings/": { body: { ...routing, status: "draft", can_edit: true, can_decide: false }, status: 201 },
  });
  renderAt("/routings", <RoutingsPage />);
  fireEvent.click(await screen.findByRole("button", { name: "New routing" }));
  const form = screen.getByRole("region", { name: "New routing" });
  fireEvent.change(within(form).getByLabelText("Part"), { target: { value: "SH-100" } });
  fireEvent.change(within(form).getByLabelText("Operation 1"), { target: { value: "Turn" } });
  fireEvent.change(within(form).getByLabelText("Section of operation 1"), { target: { value: "M-LAT" } });
  fireEvent.change(within(form).getByLabelText("Run minutes of operation 1"), { target: { value: "12.25" } });
  fireEvent.click(within(form).getByRole("button", { name: "Add operation" }));
  fireEvent.change(within(form).getByLabelText("Operation 2"), { target: { value: "Hard chrome" } });
  fireEvent.click(within(form).getByRole("checkbox", { name: "Operation 2 sent out" }));
  fireEvent.change(within(form).getByLabelText("Supplier of operation 2"), { target: { value: "S0100" } });
  fireEvent.click(within(form).getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/routings/", expect.objectContaining({ method: "POST" })));
  const sent = JSON.parse((calls.mock.calls.find((c) => c[0] === "/api/v1/routings/")![1] as RequestInit).body as string);
  expect(sent.item).toBe("SH-100");
  expect(sent.operations.map((o: { seq: string; subcontract: boolean }) => [o.seq, o.subcontract])).toEqual([
    ["10", false],
    ["20", true],
  ]);
});
