import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { JobInspectionRow, JobList, JobOrder } from "../api/jobOrders";
import { mockApi, renderAt } from "../test-utils";
import JobOrdersPage from "./JobOrdersPage";

const row = {
  id: 7,
  number: "JO26110001",
  purpose: "tools" as const,
  purpose_label: "Tools and fixtures",
  item: "SH-100",
  description: "Drive shaft",
  quantity: "20",
  unit: "pcs",
  division: "WS",
  sales_order: "",
  customer: "",
  mould: "",
  due_date: "2026-11-30",
  status: "released" as const,
  status_label: "Released",
};
const list: JobList = {
  results: [row],
  can_plan: true,
  divisions: ["WS"],
  statuses: [{ value: "released", label: "Released" }],
  purposes: [
    { value: "sales", label: "For a sales order" },
    { value: "mould_repair", label: "Mould repair" },
  ],
};
const job: JobOrder = {
  ...row,
  sales_line: null,
  item_name: "Drive shaft",
  drawing_no: "D-100",
  drawing_revision: "B",
  notes: "",
  end_reason: "",
  routing: { id: 1, revision: 1 },
  bom: { id: 2, revision: 1 },
  operations: [
    {
      seq: 10,
      name: "Turn",
      section: "M-LAT",
      machine: "M-LAT-01",
      setup_min: "30",
      run_min: "12.25",
      subcontract: false,
      supplier: "",
      subcontract_cost: "",
      notes: "",
    },
  ],
  materials: [
    {
      seq: 10,
      line_type: "raw",
      component: "EN8-50",
      name: "EN8 bar 50 mm",
      per_piece: "2.1",
      unit: "kg",
      allowed: "42",
      issued: "35",
      left: "7",
      on_hand: "15",
    },
  ],
  issues: [
    {
      id: 30,
      number: "MI26110005",
      kind: "issue",
      date: "2026-11-09",
      store: "WS-MAIN",
      value: "3780.00",
      lines: [{ id: 31, item: "EN8-50", lot_no: "B", quantity: "5", unit: "kg", value: "540.00", returnable: "5" }],
    },
  ],
  excess: [
    {
      id: 9,
      item: "EN8-50",
      quantity: "4",
      unit: "kg",
      reason: "Two scrapped at setup",
      status: "awaiting",
      by: "Stores",
      at: "2026-11-09T08:00:00Z",
      can_decide: true,
    },
  ],
  stores: [{ id: 3, code: "WS-MAIN", name: "Workshop stores" }],
  created_by: "Planner",
  released_by: "Planner",
  can_edit: false,
  can_release: false,
  can_complete: true,
  can_close: false,
  can_cancel: true,
  can_issue: true,
  can_return: true,
  can_ask_more: true,
  progress: [
    {
      seq: 10,
      name: "Turn",
      subcontract: false,
      received: "20",
      completed: "18",
      rejected: "1",
      rework: "1",
      in_hand: "1",
      at_supplier: "0",
      available: "18",
      finished: "0",
      card: "JO26110001/10",
    },
  ],
  can_print_cards: true,
  subcontract: [],
  bills: [],
  can_subcontract: false,
  suppliers: [],
  inspections: [],
  on_hold: false,
  can_inspect: false,
  transfer: null,
};

test("Stores issues material by lot and takes back what was not used", async () => {
  const calls = mockApi({
    "GET /api/v1/job-orders/waiting/": { body: { results: [] } },
    "GET /api/v1/job-orders/?q=&status=open&purpose=": { body: list },
    "GET /api/v1/job-orders/7/": { body: job },
    "GET /api/v1/job-orders/7/lots/?store=3&item=EN8-50": { body: { results: [{ lot_no: "B", quantity: "15" }] } },
    "POST /api/v1/job-orders/7/issue/": { body: { ...job, stock_issue: "MI26110006" } },
    "POST /api/v1/job-orders/7/return/": { body: { ...job, stock_issue: "MI26110007" } },
  });
  renderAt("/job-orders?job=7", <JobOrdersPage />, "/job-orders");
  const panel = await screen.findByRole("region", { name: "Job JO26110001" });
  expect(within(panel).getByRole("table", { name: "Materials" })).toHaveTextContent("EN8-50");
  expect(within(panel).getByRole("table", { name: "Progress by operation" })).toHaveTextContent("10 Turn");
  expect(within(panel).getByRole("link", { name: "Print job cards" })).toHaveAttribute("href", "/api/v1/job-orders/7/cards/");
  const issue = within(panel).getByRole("region", { name: "Issue material" });
  fireEvent.change(within(issue).getByLabelText("Material 1"), { target: { value: "EN8-50" } });
  fireEvent.change(within(issue).getByLabelText("Quantity 1"), { target: { value: "5" } });
  await within(issue).findByRole("option", { name: "B (15)" });
  fireEvent.change(within(issue).getByLabelText("Lot 1"), { target: { value: "B" } });
  fireEvent.click(within(issue).getByRole("button", { name: "Issue and post" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/job-orders/7/issue/",
      expect.objectContaining({ body: expect.stringContaining('"lines":[{"item":"EN8-50","quantity":"5","lot_no":"B"}]') }),
    ),
  );
  expect(await within(panel).findByText("MI26110006 posted.")).toBeInTheDocument();
  fireEvent.change(within(panel).getByLabelText("Return of EN8-50 B from MI26110005"), { target: { value: "2" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Take back to stores" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/job-orders/7/return/",
      expect.objectContaining({ body: expect.stringContaining('"lines":[{"line":31,"quantity":"2"}]') }),
    ),
  );
});

test("the Production Manager approves a request to issue more", async () => {
  const calls = mockApi({
    "GET /api/v1/job-orders/waiting/": {
      body: {
        results: [
          { id: 9, job: "JO26110001", job_id: 7, item: "EN8-50", quantity: "4", unit: "kg", reason: "Two scrapped at setup", by: "Stores" },
        ],
      },
    },
    "GET /api/v1/job-orders/?q=&status=open&purpose=": { body: list },
    "GET /api/v1/job-orders/7/": { body: { ...job, can_issue: false, can_return: false, can_ask_more: false } },
    "POST /api/v1/job-orders/excess/9/decide/": { body: { status: "approved" } },
  });
  renderAt("/job-orders", <JobOrdersPage />, "/job-orders");
  const waiting = await screen.findByRole("region", { name: "Requests to issue more, waiting for you" });
  fireEvent.click(within(waiting).getByRole("button", { name: "JO26110001" }));
  const requests = await screen.findByRole("region", { name: "Requests to issue more" });
  fireEvent.click(within(requests).getByRole("button", { name: "Approve more EN8-50" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/job-orders/excess/9/decide/",
      expect.objectContaining({ body: JSON.stringify({ action: "approve", reason: "" }) }),
    ),
  );
});

test("the Planner makes a mould repair job and changes its operations while a draft", async () => {
  const draft: JobOrder = {
    ...job,
    purpose: "mould_repair",
    purpose_label: "Mould repair",
    item: "",
    mould: "MD-001",
    description: "Repair cavity 3",
    status: "draft",
    status_label: "Draft",
    routing: null,
    bom: null,
    operations: [],
    materials: [],
    issues: [],
    excess: [],
    can_edit: true,
    can_release: true,
    can_issue: false,
    can_return: false,
    can_ask_more: false,
    progress: [],
    can_print_cards: false,
  };
  const calls = mockApi({
    "GET /api/v1/job-orders/waiting/": { body: { results: [] } },
    "GET /api/v1/job-orders/?q=&status=open&purpose=": { body: list },
    "POST /api/v1/job-orders/": { body: draft },
    "GET /api/v1/job-orders/7/": { body: draft },
    "PATCH /api/v1/job-orders/7/": { body: draft },
  });
  renderAt("/job-orders", <JobOrdersPage />, "/job-orders");
  fireEvent.click(await screen.findByRole("button", { name: "New job" }));
  const form = screen.getByRole("form", { name: "New job" });
  fireEvent.change(within(form).getByLabelText("For"), { target: { value: "mould_repair" } });
  fireEvent.change(within(form).getByLabelText("Mould code"), { target: { value: "MD-001" } });
  fireEvent.change(within(form).getByLabelText("Description"), { target: { value: "Repair cavity 3" } });
  fireEvent.change(within(form).getByLabelText("Quantity"), { target: { value: "1" } });
  fireEvent.click(within(form).getByRole("button", { name: "Make the job" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/job-orders/",
      expect.objectContaining({ body: expect.stringContaining('"purpose":"mould_repair"') }),
    ),
  );
  const panel = await screen.findByRole("region", { name: "Job JO26110001" });
  fireEvent.click(within(panel).getAllByRole("button", { name: "Add a line" })[0]);
  fireEvent.change(within(panel).getByLabelText("Operation 1"), { target: { value: "Weld and polish" } });
  fireEvent.change(within(panel).getByLabelText("Section 1"), { target: { value: "M-LAT" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Save changes" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/job-orders/7/",
      expect.objectContaining({ method: "PATCH", body: expect.stringContaining('"name":"Weld and polish","section":"M-LAT"') }),
    ),
  );
});

test("parts go out to the plater and are counted back; the bills coded to the job show", async () => {
  const plating = {
    seq: 30,
    name: "Hard chrome plating",
    section: "",
    machine: "",
    setup_min: "0",
    run_min: "0",
    subcontract: true,
    supplier: "S0100",
    subcontract_cost: "450",
    notes: "",
  };
  const withSub: JobOrder = {
    ...job,
    operations: [...job.operations, plating],
    can_subcontract: true,
    subcontract: [
      {
        id: 4,
        number: "SC26110001",
        operation: 30,
        operation_name: "Hard chrome plating",
        supplier: "S0100",
        supplier_name: "Ceylon Platers",
        quantity: "10",
        sent_on: "2026-11-09",
        expected_on: null,
        notes: "",
        out: "10",
        returns: [],
      },
    ],
    bills: [
      {
        kind: "voucher",
        number: "WS261109001",
        line_no: 1,
        supplier: "Ceylon Platers",
        description: "Plating",
        amount: "4500.00",
        status: "Draft",
      },
    ],
  };
  const calls = mockApi({
    "GET /api/v1/job-orders/waiting/": { body: { results: [] } },
    "GET /api/v1/job-orders/?q=&status=open&purpose=": { body: list },
    "GET /api/v1/job-orders/7/": { body: withSub },
    "POST /api/v1/job-orders/7/send-out/": { status: 201, body: withSub },
    "POST /api/v1/job-orders/7/receive-back/": { body: withSub },
  });
  renderAt("/job-orders?job=7", <JobOrdersPage />, "/job-orders");
  const sub = await screen.findByRole("region", { name: "Sent out to suppliers" });
  expect(within(sub).getByRole("link", { name: "Print the note" })).toHaveAttribute("href", "/api/v1/job-orders/sent/4/note/");
  fireEvent.change(within(sub).getByLabelText("Pieces sent"), { target: { value: "5" } });
  fireEvent.click(within(sub).getByRole("button", { name: "Send out and make the note" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/job-orders/7/send-out/",
      expect.objectContaining({ body: expect.stringContaining('"operation":"30","quantity":"5"') }),
    ),
  );
  const back = within(sub).getByRole("group", { name: "Received back from SC26110001" });
  fireEvent.change(within(back).getByLabelText("Good pieces"), { target: { value: "8" } });
  fireEvent.change(within(back).getByLabelText("Rejected pieces"), { target: { value: "1" } });
  fireEvent.change(within(back).getByLabelText("Reason for the rejects"), { target: { value: "Pitting" } });
  fireEvent.click(within(back).getByRole("button", { name: "Record what came back" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/job-orders/7/receive-back/",
      expect.objectContaining({ body: expect.stringContaining('"good":"8","rejected":"1","reason":"Pitting","dispatch":4') }),
    ),
  );
  expect(screen.getByRole("region", { name: "Supplier bills coded to this job" })).toHaveTextContent("Voucher WS261109001 line 1");
});

test("QC enters the measurements; a failed inspection holds the job and the Production Manager decides", async () => {
  const check = (value: string, within: boolean | null) => ({ piece: 1, value, passed: null, within_limits: within, notes: "" });
  const draftInspection: JobInspectionRow = {
    id: 11,
    stage: "in_process",
    stage_label: "In process",
    operation: 10,
    operation_name: "Turn",
    pieces: 1,
    status: "draft",
    status_label: "Being inspected",
    inspector: "Qc",
    inspected_at: null,
    notes: "",
    checks: [
      {
        position: 1,
        name: "Diameter",
        kind: "number",
        minimum: "49.98",
        maximum: "50",
        unit: "mm",
        critical: true,
        pieces: [check("", null)],
      },
    ],
    failed: [],
    decision: "",
    decision_label: "",
    decision_quantity: "0",
    decision_reason: "",
    decided_by: "",
    can_enter: true,
    can_decide: false,
    can_approve: false,
  };
  const failed: JobInspectionRow = {
    ...draftInspection,
    status: "on_hold",
    status_label: "Failed: job on hold",
    checks: [{ ...draftInspection.checks[0], pieces: [check("50.02", false)] }],
    failed: ["Diameter"],
    can_enter: false,
    can_decide: true,
  };
  const calls = mockApi({
    "GET /api/v1/job-orders/waiting/": { body: { results: [] } },
    "GET /api/v1/job-orders/?q=&status=open&purpose=": { body: list },
    "GET /api/v1/job-orders/7/": {
      body: { ...job, can_issue: false, can_return: false, can_ask_more: false, inspections: [draftInspection] },
    },
    "POST /api/v1/job-orders/inspections/11/finish/": { body: { ...job, on_hold: true, inspections: [failed] } },
    "POST /api/v1/job-orders/inspections/11/decide/": { body: { ...job, inspections: [] } },
  });
  renderAt("/job-orders?job=7", <JobOrdersPage />, "/job-orders");
  const panel = await screen.findByRole("region", { name: "Inspections" });
  fireEvent.change(within(panel).getByLabelText("Diameter, piece 1"), { target: { value: "50.02" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Finish the inspection" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/job-orders/inspections/11/finish/",
      expect.objectContaining({ body: JSON.stringify({ results: [{ position: 1, piece: 1, value: "50.02" }] }) }),
    ),
  );
  expect(await screen.findByRole("status")).toHaveTextContent("On hold: an inspection failed.");
  const decide = await screen.findByRole("group", { name: "Production Manager's decision" });
  fireEvent.change(within(decide).getByLabelText("Pieces"), { target: { value: "3" } });
  fireEvent.change(within(decide).getByLabelText("Reason"), { target: { value: "Oversize: another pass" } });
  fireEvent.click(within(decide).getByRole("button", { name: "Decide" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/job-orders/inspections/11/decide/",
      expect.objectContaining({ body: JSON.stringify({ decision: "rework", quantity: "3", reason: "Oversize: another pass" }) }),
    ),
  );
});

test("the Accountant transfers a completed mould repair at cost", async () => {
  const repair: JobOrder = {
    ...job,
    purpose: "mould_repair",
    purpose_label: "Mould repair",
    mould: "MD-001",
    status: "completed",
    status_label: "Completed",
    can_issue: false,
    can_return: false,
    can_ask_more: false,
    transfer: {
      done: false,
      kind_label: "Mould repair charged",
      from: "WS",
      to: "IM",
      material: "324.00",
      bills: "25000.00",
      labour: "1200.00",
      overhead: "800.00",
      hours: "2.00",
      amount: "27324.00",
      bill_lines: ["WS261109001 line 1: 25,000.00"],
      why_not: "",
      can_post: true,
    },
  };
  const calls = mockApi({
    "GET /api/v1/job-orders/waiting/": { body: { results: [] } },
    "GET /api/v1/job-orders/?q=&status=open&purpose=": { body: list },
    "GET /api/v1/job-orders/7/": { body: repair },
    "POST /api/v1/job-orders/7/transfer/": {
      body: { ...repair, transfer: { ...repair.transfer!, done: true, date: "2026-11-09", journal: "JE26110042", can_post: false } },
    },
  });
  renderAt("/job-orders?job=7", <JobOrdersPage />, "/job-orders");
  const panel = await screen.findByRole("region", { name: "Transfer at cost to the mould's division" });
  expect(within(panel).getByRole("table", { name: "Total at cost" })).toHaveTextContent("27,324.00");
  fireEvent.change(within(panel).getByLabelText("Notes (optional)"), { target: { value: "Cavity 3 rewelded" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Post the transfer" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/job-orders/7/transfer/",
      expect.objectContaining({ body: JSON.stringify({ notes: "Cavity 3 rewelded" }) }),
    ),
  );
  expect(await within(panel).findByText("Transferred on 2026-11-09: journal JE26110042")).toBeInTheDocument();
});
