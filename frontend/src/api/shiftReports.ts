import { apiGet, apiSend } from "./client";

/** Shift reports entered by supervisors: moulding runs (P3-08) or job card operations in a
 * machining section (P3-12). */

export type SectionType = "moulding" | "machining";

export interface OpenShift {
  section: string;
  section_name: string;
  section_type: SectionType;
  day: string;
  shift: string;
  shift_name: string;
  closes_at: string;
  report: number | null;
  status: string;
}

export interface ReportRow {
  id: number;
  section: string;
  section_type: SectionType;
  day: string;
  shift: string;
  shift_name: string;
  status: "draft" | "submitted" | "returned" | "approved";
  status_label: string;
  created_by: string;
  submitted_at: string | null;
}

export interface RunValues {
  machine: string;
  order: number | "";
  plan_entry?: number | null;
  material_lot: string;
  operator: string;
  start_time: string;
  end_time: string;
  start_counter: string;
  end_counter: string;
  rejects: { reason: string; quantity: string }[];
}

export interface Run extends Omit<RunValues, "start_counter" | "end_counter" | "rejects"> {
  order_number: string;
  item: string;
  mould: string;
  material: string;
  start_counter: number;
  end_counter: number;
  shots: number;
  cavities: number;
  good_quantity: string;
  actual_cycle_s: string;
  standard_cycle_s: string;
  planned_quantity: string;
  rejects: { reason: string; quantity: number }[];
}

/** P3-12: work on one job card operation. */
export interface JobWorkValues {
  job: string;
  operation: string;
  machine: string;
  operator: string;
  start_time: string;
  end_time: string;
  completed: string;
  rework: string;
  setup: boolean;
  notes: string;
  rejects: { reason: string; quantity: string }[];
}

export interface JobWork extends Omit<JobWorkValues, "operation"> {
  job_id: number;
  description: string;
  operation: number;
  operation_name: string;
  rejected: string;
  minutes_per_piece: string;
  standard_minutes: string;
  standard_setup: string;
}

export interface DowntimeValues {
  machine: string;
  reason: string;
  start_time: string;
  end_time: string;
  remarks: string;
}

export interface MaterialValues {
  kind: "issue" | "return" | "regrind";
  item: string;
  lot_no: string;
  quantity: string;
}

export interface ManpowerValues {
  machine: string;
  people: string;
  overtime_hours: string;
}

export interface Summary {
  shots: number;
  made: number;
  good: string;
  rejects: number;
  reject_pct: string;
  rejects_by_reason: { reason: string; quantity: number }[];
  downtime_minutes: number;
  downtime_by_reason: { reason: string; minutes: number }[];
  material: { item: string; used: string; unit: string; grams_per_good: string }[];
  regrind: string;
  people: number;
  overtime_hours: string;
  machining: { completed: string; rejected: string; rework: string; minutes: number };
}

export interface ShiftReport extends ReportRow {
  section_name: string;
  shift_start: string;
  shift_end: string;
  closes_at: string;
  notes: string;
  runs: Run[];
  operations: JobWork[];
  downtime: DowntimeValues[];
  materials: MaterialValues[];
  manpower: { machine: string; people: number; overtime_hours: string }[];
  summary: Summary;
  editable: boolean;
  /** P3-21: when the report was last saved; an offline save names it. */
  version: string;
  // P3-09: approval and corrections.
  return_reason: string;
  approved_by: string;
  approved_at: string | null;
  stock_issue: string;
  receipts: {
    order: string;
    item: string;
    is_regrind: boolean;
    quantity: string;
    material_value: string;
    regrind_credit: string;
    value: string;
    undone: boolean;
  }[];
  corrections: {
    id: number;
    reason: string;
    status: "awaiting" | "approved" | "rejected";
    status_label: string;
    requested_by: string;
    requested_at: string;
    can_decide: boolean;
  }[];
  can_decide: boolean;
  can_ask: boolean;
  reopened_until: string | null;
  options: {
    machines: { code: string; name: string }[];
    orders: { id: number; number: string; item: string; mould: string }[];
    plan: {
      id: number;
      machine: string;
      order: number;
      order_number: string;
      item: string;
      mould: string;
      quantity: string;
      minutes: number;
    }[];
    jobs: {
      id: number;
      number: string;
      item: string;
      description: string;
      operations: { seq: number; name: string; section: string; machine: string; in_hand: string; run_min: string }[];
    }[];
    reject_reasons: { code: string; name: string }[];
    downtime_reasons: { code: string; name: string }[];
    operators: { number: string; name: string }[];
  };
}

export interface ReportValues {
  runs: RunValues[];
  operations: JobWorkValues[];
  downtime: DowntimeValues[];
  materials: MaterialValues[];
  manpower: ManpowerValues[];
  notes: string;
}

export const reportsKey = ["shift-reports"] as const;
export const getReports = () => apiGet<{ open: OpenShift[]; recent: ReportRow[]; can_enter: boolean }>("/shift-reports/");
export const openReport = (values: { section: string; shift: string; day: string }) =>
  apiSend<ShiftReport>("POST", "/shift-reports/", values);
export const getReport = (id: number) => apiGet<ShiftReport>(`/shift-reports/${id}/`);
export const saveReport = (id: number, values: ReportValues, baseVersion?: string) =>
  apiSend<ShiftReport>("PUT", `/shift-reports/${id}/`, baseVersion ? { ...values, base_version: baseVersion } : values);
export const submitReport = (id: number) => apiSend<ShiftReport>("POST", `/shift-reports/${id}/submit/`);
export const decideReport = (id: number, action: "approve" | "send_back", reason = "") =>
  apiSend<ShiftReport>("POST", `/shift-reports/${id}/decide/`, { action, reason });
export const askCorrection = (id: number, reason: string) => apiSend<ShiftReport>("POST", `/shift-reports/${id}/corrections/`, { reason });
export const decideCorrection = (id: number, action: "approve" | "reject", reason = "") =>
  apiSend<ShiftReport>("POST", `/shift-reports/corrections/${id}/decide/`, { action, reason });
