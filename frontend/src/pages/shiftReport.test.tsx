import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import type { ShiftReport } from "../api/shiftReports";
import ScanButton from "../components/ScanButton";
import { mockApi, renderAt } from "../test-utils";
import ShiftReportPage from "./ShiftReportPage";

const report: ShiftReport = {
  id: 9,
  section: "IM-MLD",
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
  },
  editable: true,
  options: {
    machines: [{ code: "IMM-250", name: "Haitian 250 t" }],
    orders: [{ id: 7, number: "MO26110001", item: "CAP-28", mould: "MD-001" }],
    plan: [
      { id: 3, machine: "IMM-250", order: 7, order_number: "MO26110001", item: "CAP-28", mould: "MD-001", quantity: "19200", minutes: 480 },
    ],
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
