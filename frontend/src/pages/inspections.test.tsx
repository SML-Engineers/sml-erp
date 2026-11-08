import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { InspectionDetail } from "../api/inspections";
import { mockApi, renderAt } from "../test-utils";
import InspectionPage from "./InspectionPage";
import InspectionsPage from "./InspectionsPage";

const inspection: InspectionDetail = {
  id: 7,
  status: "draft",
  decision: "",
  automatic: false,
  grn: { id: 4, number: "GRN26110101", receipt_date: "2026-11-01" },
  division: "IM",
  supplier: { code: "S0003", name: "SDD Polymer" },
  item: { code: "PP-H-WHITE", name: "PP homopolymer", unit: "kg" },
  good_quantity: "100.000",
  accepted_quantity: "100.000",
  rejected_quantity: "0.000",
  inspector: "QC",
  started_at: "2026-11-01T10:00:00",
  decided_at: null,
  line_no: 1,
  received_quantity: "100.000",
  damaged_quantity: "0.000",
  plan: { id: 1, name: "PP resin" },
  sample_size: 2,
  notes: "",
  reason: "",
  results: [
    {
      position: 1,
      name: "Melt flow index",
      kind: "number",
      minimum: "10.0000",
      maximum: "14.0000",
      unit: "g/10 min",
      critical: true,
      value: null,
      passed: null,
      within_limits: null,
      notes: "",
    },
    {
      position: 2,
      name: "Bag condition",
      kind: "pass_fail",
      minimum: null,
      maximum: null,
      unit: "",
      critical: false,
      value: null,
      passed: null,
      within_limits: null,
      notes: "",
    },
  ],
  packages: [
    { package_no: 1, lot_no: "GRN26110101-1-001", supplier_lot: "L-1", quantity: "50.000", damaged: false, rejected: false },
    { package_no: 2, lot_no: "GRN26110101-1-002", supplier_lot: "L-1", quantity: "50.000", damaged: false, rejected: false },
  ],
  attachments: [],
  can_edit: true,
  can_attach: true,
  can_approve: false,
  history: [],
};

test("the queue lists goods waiting for QC and starts an inspection", async () => {
  const calls = mockApi({
    "GET /api/v1/inspections/queue/": {
      body: {
        can_inspect: true,
        lines: [
          {
            line: 11,
            grn: { id: 4, number: "GRN26110101", receipt_date: "2026-11-01" },
            division: "IM",
            supplier: "SDD Polymer",
            item: { code: "PP-H-WHITE", name: "PP homopolymer", unit: "kg" },
            good_quantity: "100.000",
            packages: 2,
            inspection: null,
          },
        ],
      },
    },
    "GET /api/v1/inspections/": { body: [] },
    "POST /api/v1/inspections/": { status: 201, body: inspection },
  });
  renderAt("/inspections", <InspectionsPage />);
  const queue = await screen.findByRole("table", { name: "Waiting for QC" });
  expect(within(queue).getByText(/100 kg · 2 packages/)).toBeInTheDocument();
  fireEvent.click(within(queue).getByRole("button", { name: "Inspect PP-H-WHITE" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/inspections/",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ line: 11 }) }),
    ),
  );
});

test("QC enters results, rejects one bag and accepts the rest", async () => {
  const calls = mockApi({
    "GET /api/v1/inspections/7/": { body: inspection },
    "PUT /api/v1/inspections/7/": { body: inspection },
    "POST /api/v1/inspections/7/decide/": {
      body: {
        ...inspection,
        status: "decided",
        decision: "accepted",
        can_edit: false,
        accepted_quantity: "50.000",
        rejected_quantity: "50.000",
      },
    },
  });
  renderAt("/inspections/7", <InspectionPage />, "/inspections/:id");
  fireEvent.change(await screen.findByLabelText("Result, Melt flow index"), { target: { value: "12.1" } });
  fireEvent.change(screen.getByLabelText("Result, Bag condition"), { target: { value: "pass" } });
  fireEvent.click(screen.getByRole("checkbox", { name: /GRN26110101-1-002/ }));
  fireEvent.click(screen.getByRole("button", { name: "Accept" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/inspections/7/decide/", expect.objectContaining({ method: "POST" })));
  const [, init] = calls.mock.calls.find(([url, i]) => url === "/api/v1/inspections/7/" && i?.method === "PUT")!;
  expect(JSON.parse(String(init!.body))).toMatchObject({
    results: [
      { position: 1, value: "12.1", passed: null },
      { position: 2, value: null, passed: true },
    ],
    rejected_packages: [2],
  });
  expect(await screen.findByText("Accepted 50 kg, rejected 50 kg.")).toBeInTheDocument();
});

test("the Director approves a deviation", async () => {
  const waiting: InspectionDetail = {
    ...inspection,
    status: "deviation_requested",
    can_edit: false,
    can_attach: false,
    can_approve: true,
    reason: "MFI slightly high",
    history: [{ action: "submit", action_label: "Submitted", by: "QC", at: "2026-11-01T11:00:00", reason: "MFI slightly high" }],
  };
  const calls = mockApi({
    "GET /api/v1/inspections/7/": { body: waiting },
    "POST /api/v1/inspections/7/approve/": { body: { ...waiting, status: "decided", decision: "deviation", can_approve: false } },
  });
  renderAt("/inspections/7", <InspectionPage />, "/inspections/:id");
  fireEvent.click(await screen.findByRole("button", { name: "Approve the deviation" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/inspections/7/approve/", expect.objectContaining({ method: "POST" })));
  expect(await screen.findByText(/^Accepted under deviation ·/)).toBeInTheDocument();
});
