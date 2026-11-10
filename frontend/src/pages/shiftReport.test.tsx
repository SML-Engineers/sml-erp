import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import type { ShiftReport } from "../api/shiftReports";
import ScanButton from "../components/ScanButton";
import { mockApi, renderAt } from "../test-utils";
import ShiftReportPage from "./ShiftReportPage";

const report: ShiftReport = {
  id: 9,
  section: "IM-MLD",
  section_type: "moulding",
  section_name: "Moulding",
  day: "2026-11-08",
  shift: "G",
  shift_name: "General",
  status: "draft",
  status_label: "Draft",
  created_by: "Sup",
  submitted_at: null,
  shift_start: "2026-11-08T02:30:00Z",
  shift_end: "2026-11-08T11:30:00Z",
  closes_at: "2026-11-08T15:30:00Z",
  notes: "",
  runs: [
    {
      machine: "IMM-250",
      order: 7,
      order_number: "MO26110001",
      item: "CAP-28",
      mould: "MD-001",
      plan_entry: 3,
      material_lot: "L1",
      material: "PP-H",
      operator: "E010",
      start_time: "08:00",
      end_time: "10:00",
      start_counter: 1000,
      end_counter: 1500,
      shots: 500,
      cavities: 8,
      good_quantity: "3960",
      actual_cycle_s: "12",
      standard_cycle_s: "12",
      planned_quantity: "19200",
      rejects: [{ reason: "FLASH", quantity: 40 }],
    },
  ],
  operations: [],
  downtime: [],
  materials: [],
  manpower: [],
  summary: {
    shots: 500,
    made: 4000,
    good: "3960",
    rejects: 40,
    reject_pct: "1",
    rejects_by_reason: [{ reason: "FLASH Flash", quantity: 40 }],
    downtime_minutes: 0,
    downtime_by_reason: [],
    material: [],
    regrind: "0",
    people: 0,
    overtime_hours: "0",
    machining: { completed: "0", rejected: "0", rework: "0", minutes: 0 },
  },
  editable: true,
  version: "2026-11-08T08:00:00+05:30",
  return_reason: "",
  approved_by: "",
  approved_at: null,
  stock_issue: "",
  receipts: [],
  corrections: [],
  can_decide: false,
  can_ask: false,
  reopened_until: null,
  options: {
    machines: [{ code: "IMM-250", name: "Haitian 250 t" }],
    orders: [{ id: 7, number: "MO26110001", item: "CAP-28", mould: "MD-001" }],
    plan: [
      { id: 3, machine: "IMM-250", order: 7, order_number: "MO26110001", item: "CAP-28", mould: "MD-001", quantity: "19200", minutes: 480 },
    ],
    jobs: [],
    reject_reasons: [{ code: "FLASH", name: "Flash" }],
    downtime_reasons: [{ code: "POWER", name: "Power failure" }],
    operators: [{ number: "E010", name: "Kamal Perera" }],
  },
};

afterEach(() => {
  delete (window as unknown as { BarcodeDetector?: unknown }).BarcodeDetector;
});

test("the supervisor starts an open shift", async () => {
  const calls = mockApi({
    "GET /api/v1/shift-reports/": {
      body: {
        open: [
          {
            section: "IM-MLD",
            section_name: "Moulding",
            section_type: "moulding",
            day: "2026-11-08",
            shift: "G",
            shift_name: "General",
            closes_at: "",
            report: null,
            status: "",
          },
        ],
        recent: [],
        can_enter: true,
      },
    },
    "POST /api/v1/shift-reports/": { body: report, status: 201 },
    "GET /api/v1/shift-reports/9/": { body: report },
  });
  renderAt("/shift-report", <ShiftReportPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Start IM-MLD · General · 2026-11-08" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/shift-reports/",
      expect.objectContaining({ body: JSON.stringify({ section: "IM-MLD", shift: "G", day: "2026-11-08" }) }),
    ),
  );
  expect(await screen.findByText(/500 shots × 8 cavities: 3,960 good. Cycle 12 s \(standard 12 s\)/)).toBeInTheDocument();
});

test("a run from the plan, downtime and material are saved, then the report submitted", async () => {
  const calls = mockApi({
    "GET /api/v1/shift-reports/9/": { body: { ...report, runs: [] } },
    "PUT /api/v1/shift-reports/9/": { body: report },
    "POST /api/v1/shift-reports/9/submit/": { body: { ...report, status: "submitted", status_label: "Submitted", editable: false } },
  });
  renderAt("/shift-report?report=9", <ShiftReportPage />, "/shift-report");
  const planned = await screen.findByRole("region", { name: "Planned for this shift" });
  fireEvent.click(within(planned).getByRole("button", { name: "Enter this run" }));
  const run = screen.getByRole("group", { name: "Run 1" });
  expect(within(run).getByLabelText("Machine")).toHaveValue("IMM-250");
  fireEvent.change(within(run).getByLabelText("Start time"), { target: { value: "08:00" } });
  fireEvent.change(within(run).getByLabelText("End time"), { target: { value: "10:00" } });
  fireEvent.change(within(run).getByLabelText("Shot counter at start"), { target: { value: "1000" } });
  fireEvent.change(within(run).getByLabelText("Shot counter at end"), { target: { value: "1500" } });
  fireEvent.click(within(run).getByRole("button", { name: "Add rejects" }));
  fireEvent.change(within(run).getByLabelText("Reason"), { target: { value: "FLASH" } });
  fireEvent.change(within(run).getByLabelText("Pieces"), { target: { value: "40" } });
  fireEvent.click(screen.getByRole("button", { name: "Add downtime" }));
  const stop = screen.getByRole("group", { name: "Downtime 1" });
  fireEvent.change(within(stop).getByLabelText("Machine"), { target: { value: "IMM-250" } });
  fireEvent.change(within(stop).getByLabelText("Reason"), { target: { value: "POWER" } });
  fireEvent.change(within(stop).getByLabelText("From"), { target: { value: "09:00" } });
  fireEvent.change(within(stop).getByLabelText("To"), { target: { value: "09:10" } });
  fireEvent.click(screen.getByRole("button", { name: "Add material" }));
  const material = screen.getByRole("group", { name: "Material 1" });
  fireEvent.change(within(material).getByLabelText("Material batch"), { target: { value: "L1" } });
  fireEvent.change(within(material).getByLabelText("Quantity (kg)"), { target: { value: "25" } });
  expect(screen.getByText("Changes not saved yet.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Submit the report" }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith("/api/v1/shift-reports/9/submit/", expect.objectContaining({ method: "POST" })));
  const put = calls.mock.calls.find((c) => c[0] === "/api/v1/shift-reports/9/" && c[1]?.method === "PUT");
  const sent = JSON.parse(String(put?.[1]?.body));
  expect(sent.runs).toEqual([
    {
      machine: "IMM-250",
      order: 7,
      material_lot: "",
      operator: "",
      start_time: "08:00",
      end_time: "10:00",
      start_counter: "1000",
      end_counter: "1500",
      rejects: [{ reason: "FLASH", quantity: "40" }],
      plan_entry: 3,
    },
  ]);
  expect(sent.downtime).toEqual([{ machine: "IMM-250", reason: "POWER", start_time: "09:00", end_time: "09:10", remarks: "" }]);
  expect(sent.materials).toEqual([{ kind: "issue", item: "", lot_no: "L1", quantity: "25" }]);
  expect(await screen.findByText(/Submitted/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
});

test("the summary and a saving error are shown", async () => {
  mockApi({
    "GET /api/v1/shift-reports/9/": { body: report },
    "PUT /api/v1/shift-reports/9/": { status: 400, body: { detail: "The shot counter of run 1 (IMM-250) goes down (1000 to 900)." } },
  });
  renderAt("/shift-report?report=9", <ShiftReportPage />, "/shift-report");
  const summary = await screen.findByRole("region", { name: "Shift summary" });
  expect(within(summary).getByText("Good: 3,960 of 4,000 made (500 shots)")).toBeInTheDocument();
  expect(within(summary).getByText("Rejects: 40 (1%)")).toBeInTheDocument();
  fireEvent.click(within(summary).getByRole("button", { name: "Save" }));
  expect(await within(summary).findByRole("alert")).toHaveTextContent("goes down (1000 to 900)");
});

test("scanning fills the field where the browser can read codes", async () => {
  const stop = vi.fn();
  (window as unknown as { BarcodeDetector: unknown }).BarcodeDetector = class {
    detect() {
      return Promise.resolve([{ rawValue: " imm-250 " }]);
    }
  };
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] }) },
  });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  const onScan = vi.fn();
  renderAt("/", <ScanButton label="Scan the machine" onScan={onScan} />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Scan the machine" }));
  });
  await waitFor(() => expect(onScan).toHaveBeenCalledWith("imm-250"));
  expect(stop).toHaveBeenCalled();
});

test("no scan button where the browser cannot read codes", () => {
  renderAt("/", <ScanButton label="Scan the machine" onScan={vi.fn()} />);
  expect(screen.queryByRole("button", { name: "Scan the machine" })).not.toBeInTheDocument();
});

test("the Production Manager approves, and the stock it made is shown", async () => {
  const submitted = { ...report, status: "submitted" as const, status_label: "Submitted", editable: false, can_decide: true };
  const approved = {
    ...submitted,
    status: "approved" as const,
    status_label: "Approved",
    can_decide: false,
    approved_by: "Pm",
    stock_issue: "SI26110001",
    receipts: [
      {
        order: "MO26110001",
        item: "CAP-28",
        is_regrind: false,
        quantity: "3960",
        material_value: "9619.20",
        regrind_credit: "600.00",
        value: "9019.20",
        undone: false,
      },
      {
        order: "",
        item: "PP-H",
        is_regrind: true,
        quantity: "1.2",
        material_value: "600.00",
        regrind_credit: "0.00",
        value: "600.00",
        undone: false,
      },
    ],
  };
  const calls = mockApi({
    "GET /api/v1/shift-reports/9/": { body: submitted },
    "POST /api/v1/shift-reports/9/decide/": { body: approved },
  });
  renderAt("/shift-report?report=9", <ShiftReportPage />, "/shift-report");
  const panel = await screen.findByRole("region", { name: "Approve or return" });
  fireEvent.click(within(panel).getByRole("button", { name: "Approve the report" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/shift-reports/9/decide/",
      expect.objectContaining({ body: JSON.stringify({ action: "approve", reason: "" }) }),
    ),
  );
  const stock = await screen.findByRole("table", { name: "Put into stock" });
  expect(within(stock).getByText("9,019.20")).toBeInTheDocument();
  expect(screen.getByText(/stock issue SI26110001/)).toBeInTheDocument();
  expect(screen.getByText(/Approved by Pm/)).toBeInTheDocument();
});

test("a supervisor asks for a correction and the approver decides it", async () => {
  const approved = { ...report, status: "approved" as const, status_label: "Approved", editable: false, can_ask: true };
  const asked = {
    ...approved,
    can_ask: false,
    corrections: [
      {
        id: 4,
        reason: "Counter misread",
        status: "awaiting" as const,
        status_label: "Waiting for approval",
        requested_by: "Sup",
        requested_at: "",
        can_decide: false,
      },
    ],
  };
  const calls = mockApi({
    "GET /api/v1/shift-reports/9/": { body: approved },
    "POST /api/v1/shift-reports/9/corrections/": { body: asked, status: 201 },
  });
  const { unmount } = renderAt("/shift-report?report=9", <ShiftReportPage />, "/shift-report");
  const panel = await screen.findByRole("region", { name: "Corrections" });
  fireEvent.change(within(panel).getByLabelText("What needs correcting"), { target: { value: "Counter misread" } });
  fireEvent.click(within(panel).getByRole("button", { name: "Ask for a correction" }));
  expect(await within(panel).findByText(/“Counter misread” asked by Sup: Waiting for approval/)).toBeInTheDocument();
  expect(calls).toHaveBeenCalledWith(
    "/api/v1/shift-reports/9/corrections/",
    expect.objectContaining({ body: JSON.stringify({ reason: "Counter misread" }) }),
  );
  unmount();
  const toDecide = { ...asked, corrections: [{ ...asked.corrections[0], can_decide: true }] };
  const decide = mockApi({
    "GET /api/v1/shift-reports/9/": { body: toDecide },
    "POST /api/v1/shift-reports/corrections/4/decide/": {
      body: { ...approved, status: "returned", status_label: "Returned", return_reason: "Correction: Counter misread", can_ask: false },
    },
  });
  renderAt("/shift-report?report=9", <ShiftReportPage />, "/shift-report");
  const again = await screen.findByRole("region", { name: "Corrections" });
  fireEvent.click(within(again).getByRole("button", { name: "Approve the correction" }));
  await waitFor(() =>
    expect(decide).toHaveBeenCalledWith(
      "/api/v1/shift-reports/corrections/4/decide/",
      expect.objectContaining({ body: JSON.stringify({ action: "approve", reason: "" }) }),
    ),
  );
  expect(await screen.findByText("Returned by the Production Manager: Correction: Counter misread")).toBeInTheDocument();
});

test("in a machining section the supervisor scans a job card and enters the work", async () => {
  (window as unknown as { BarcodeDetector: unknown }).BarcodeDetector = class {
    detect() {
      return Promise.resolve([{ rawValue: "jo26110001/20" }]);
    }
  };
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] }) },
  });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  const lathe: ShiftReport = {
    ...report,
    section: "M-LAT",
    section_type: "machining",
    section_name: "Manual lathes",
    runs: [],
    options: {
      ...report.options,
      machines: [{ code: "M-LAT-01", name: "Lathe 1" }],
      plan: [],
      orders: [],
      reject_reasons: [{ code: "SURFACE", name: "Surface finish" }],
      jobs: [
        {
          id: 7,
          number: "JO26110001",
          item: "SH-100",
          description: "Drive shaft",
          operations: [{ seq: 20, name: "Turn", section: "M-LAT", machine: "M-LAT-01", in_hand: "18", run_min: "12.25" }],
        },
      ],
    },
  };
  const calls = mockApi({
    "GET /api/v1/shift-reports/9/": { body: lathe },
    "PUT /api/v1/shift-reports/9/": { body: lathe },
  });
  renderAt("/shift-report?report=9", <ShiftReportPage />, "/shift-report");
  const cards = await screen.findByRole("region", { name: "Job cards worked on" });
  expect(screen.queryByRole("region", { name: "Machine runs" })).not.toBeInTheDocument();
  fireEvent.click(within(cards).getByRole("button", { name: "Add a job card" }));
  await act(async () => {
    fireEvent.click(within(cards).getByRole("button", { name: "Scan job card 1" }));
  });
  const card = within(cards).getByRole("group", { name: "Job card 1" });
  await waitFor(() => expect(within(card).getByLabelText("Operation")).toHaveValue("20"));
  expect(within(card).getByLabelText("Machine")).toHaveValue("M-LAT-01");
  expect(within(card).getByText("Standard: 12.25 min a piece")).toBeInTheDocument();
  fireEvent.change(within(card).getByLabelText("Start time"), { target: { value: "08:00" } });
  fireEvent.change(within(card).getByLabelText("End time"), { target: { value: "10:00" } });
  fireEvent.change(within(card).getByLabelText("Pieces completed"), { target: { value: "9" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(calls).toHaveBeenCalledWith(
      "/api/v1/shift-reports/9/",
      expect.objectContaining({ body: expect.stringContaining('"job":"JO26110001","operation":"20","machine":"M-LAT-01"') }),
    ),
  );
});

describe("without a connection (P3-21)", () => {
  afterEach(() => window.localStorage.clear());

  test("a save is kept on the phone, the page opens from the kept copy, and it is sent when the connection returns", async () => {
    let down = false;
    const sent: unknown[] = [];
    const calls = mockApi({
      "GET /api/v1/shift-reports/9/": () => {
        if (down) throw new TypeError("Failed to fetch");
        return { body: report };
      },
      "PUT /api/v1/shift-reports/9/": (body) => {
        if (down) throw new TypeError("Failed to fetch");
        sent.push(body);
        return { body: { ...report, notes: "Mould changed at 10", version: "2026-11-08T10:30:00+05:30" } };
      },
    });
    const first = renderAt("/shift-report?report=9", <ShiftReportPage />, "/shift-report");
    const notes = await screen.findByLabelText("Notes for the shift");
    down = true;
    fireEvent.change(notes, { target: { value: "Mould changed at 10" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Saved on this phone at .*, not sent yet\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit the report" })).toBeDisabled();
    // The phone is reloaded with no connection: the kept copy and the kept save are shown.
    first.unmount();
    renderAt("/shift-report?report=9", <ShiftReportPage />, "/shift-report");
    expect(await screen.findByText(/No connection: showing the copy kept on this phone at/)).toBeInTheDocument();
    expect(screen.getByLabelText("Notes for the shift")).toHaveValue("Mould changed at 10");
    // The connection returns: the save goes, on the version the copy came from.
    down = false;
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ notes: "Mould changed at 10", base_version: report.version });
    await waitFor(() => expect(screen.queryByText(/not sent yet/)).not.toBeInTheDocument());
    expect(window.localStorage.getItem("sml-offline-report-9")).toBeNull();
    expect(calls).toHaveBeenCalled();
  });

  test("a save made on an older copy is never sent over the report saved elsewhere without a choice", async () => {
    const office = { ...report, notes: "Saved from the office", version: "2026-11-08T10:00:00+05:30" };
    const sent: Record<string, unknown>[] = [];
    window.localStorage.setItem(
      "sml-offline-report-9",
      JSON.stringify({
        values: { runs: [], operations: [], downtime: [], materials: [], manpower: [], notes: "Typed offline" },
        base: report.version,
        savedAt: "2026-11-08T09:40:00+05:30",
      }),
    );
    mockApi({
      "GET /api/v1/shift-reports/9/": { body: office },
      "PUT /api/v1/shift-reports/9/": (raw) => {
        const body = raw as Record<string, unknown>;
        sent.push(body);
        if (body.base_version) return { status: 409, body: { detail: "Changed elsewhere", current: office } };
        return { body: { ...office, notes: "Typed offline", version: "2026-11-08T10:40:00+05:30" } };
      },
    });
    renderAt("/shift-report?report=9", <ShiftReportPage />, "/shift-report");
    const choice = await screen.findByRole("alert", { name: "This report was changed elsewhere" });
    expect(within(choice).getByRole("row", { name: /Your version/ })).toHaveTextContent("Typed offline");
    expect(within(choice).getByRole("row", { name: /The saved version/ })).toHaveTextContent("Saved from the office");
    expect(sent).toHaveLength(1); // refused, nothing overwritten
    fireEvent.click(within(choice).getByRole("button", { name: "Keep my version" }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1].base_version).toBeUndefined();
    await waitFor(() => expect(screen.queryByRole("alert", { name: "This report was changed elsewhere" })).not.toBeInTheDocument());
    expect(window.localStorage.getItem("sml-offline-report-9")).toBeNull();
  });
});
