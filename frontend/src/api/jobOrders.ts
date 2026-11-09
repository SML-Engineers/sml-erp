import { API_BASE, apiGet, apiSend } from "./client";
import type { OrderCosts } from "./orderCosts";
import type { CloseReport, OrderProfit } from "./orderProfits";
import type { OpenSalesLine, SalesLine } from "./productionOrders";

/** Machining job orders and their material (P3-11). */

export type JobStatus = "draft" | "released" | "completed" | "closed" | "cancelled";
export type JobPurpose = "sales" | "new_mould" | "mould_repair" | "tools" | "internal";

export interface JobRow {
  id: number;
  number: string;
  purpose: JobPurpose;
  purpose_label: string;
  item: string;
  description: string;
  quantity: string;
  unit: string;
  division: string;
  sales_order: string;
  customer: string;
  mould: string;
  due_date: string;
  status: JobStatus;
  status_label: string;
}

export interface JobOperation {
  seq: number;
  name: string;
  section: string;
  machine: string;
  setup_min: string;
  run_min: string;
  subcontract: boolean;
  supplier: string;
  subcontract_cost: string;
  notes: string;
}

export interface JobMaterial {
  seq: number | null;
  line_type: string;
  component: string;
  name: string;
  supplier?: string;
  description?: string;
  per_piece?: string;
  unit: string;
  operation_seq?: number | null;
  customer_supplied?: boolean;
  extra?: boolean;
  allowed?: string;
  issued?: string;
  left?: string;
  on_hand?: string;
}

/** P3-12: what each operation received, completed, rejected and passed on. */
export interface JobStep {
  seq: number;
  name: string;
  subcontract: boolean;
  received: string;
  completed: string;
  rejected: string;
  rework: string;
  in_hand: string;
  at_supplier: string;
  available: string;
  finished: string;
  card: string;
}

/** P3-13: parts sent out to a supplier and what came back. */
export interface Dispatch {
  id: number;
  number: string;
  operation: number;
  operation_name: string;
  supplier: string;
  supplier_name: string;
  quantity: string;
  sent_on: string;
  expected_on: string | null;
  notes: string;
  out: string;
  returns: { received_on: string; good: string; rejected: string; reason: string; by: string }[];
}

/** P3-14: an inspection of the job, its checks per piece, and the decision. */
export interface JobInspectionRow {
  id: number;
  stage: "first_article" | "in_process" | "final";
  stage_label: string;
  operation: number;
  operation_name: string;
  pieces: number;
  status: "draft" | "passed" | "on_hold" | "deviation_requested" | "decided";
  status_label: string;
  inspector: string;
  inspected_at: string | null;
  notes: string;
  checks: {
    position: number;
    name: string;
    kind: "number" | "pass_fail";
    minimum: string;
    maximum: string;
    unit: string;
    critical: boolean;
    pieces: { piece: number; value: string; passed: boolean | null; within_limits: boolean | null; notes: string }[];
  }[];
  failed: string[];
  decision: "" | "rework" | "scrap" | "deviation";
  decision_label: string;
  decision_quantity: string;
  decision_reason: string;
  decided_by: string;
  can_enter: boolean;
  can_decide: boolean;
  can_approve: boolean;
}

/** P3-15: a mould job transferred at cost to the mould's division. */
export interface Transfer {
  done: boolean;
  kind?: "new_mould" | "repair";
  kind_label: string;
  date?: string;
  from: string;
  to: string;
  material: string;
  bills: string;
  labour: string;
  overhead: string;
  hours?: string;
  amount: string;
  journal?: string;
  asset?: string;
  bill_lines?: string[];
  why_not?: string;
  can_post?: boolean;
}

export interface Bill {
  kind: "voucher" | "invoice";
  number: string;
  line_no: number;
  supplier: string;
  description: string;
  amount: string;
  status: string;
}

export interface JobIssueDoc {
  id: number;
  number: string;
  kind: "issue" | "return";
  date: string;
  store: string;
  value: string;
  lines: { id: number; item: string; lot_no: string; quantity: string; unit: string; value: string; returnable: string }[];
}

export interface JobExcessRow {
  id: number;
  item: string;
  quantity: string;
  unit: string;
  reason: string;
  status: "awaiting" | "approved" | "rejected";
  by: string;
  at: string;
  can_decide: boolean;
}

export interface JobOrder extends JobRow {
  sales_line: SalesLine | null;
  item_name: string;
  drawing_no: string;
  drawing_revision: string;
  notes: string;
  end_reason: string;
  routing: { id: number; revision: number } | null;
  bom: { id: number; revision: number } | null;
  operations: JobOperation[];
  materials: JobMaterial[];
  progress: JobStep[];
  can_print_cards: boolean;
  subcontract: Dispatch[];
  bills: Bill[];
  can_subcontract: boolean;
  inspections: JobInspectionRow[];
  on_hold: boolean;
  transfer: Transfer | null;
  costs: OrderCosts | null;
  /** P3-17: null for a draft or for people who do not see costs. */
  profit?: OrderProfit | null;
  /** P3-18: the final report once closed. */
  close_report?: CloseReport | null;
  can_inspect: boolean;
  suppliers: { seq: number; supplier: string }[];
  dispatch?: { id: number; number: string };
  issues: JobIssueDoc[];
  excess: JobExcessRow[];
  stores: { id: number; code: string; name: string }[];
  created_by: string;
  released_by: string;
  can_edit: boolean;
  can_release: boolean;
  can_complete: boolean;
  can_close: boolean;
  can_cancel: boolean;
  can_issue: boolean;
  can_return: boolean;
  can_ask_more: boolean;
  stock_issue?: string;
}

export interface JobList {
  results: JobRow[];
  can_plan: boolean;
  divisions: string[];
  statuses: { value: string; label: string }[];
  purposes: { value: JobPurpose; label: string }[];
}

export interface WaitingExcess {
  id: number;
  job: string;
  job_id: number;
  item: string;
  quantity: string;
  unit: string;
  reason: string;
  by: string;
}

export type JobValues = Record<string, unknown>;
export type JobAction =
  | "release"
  | "complete"
  | "close"
  | "cancel"
  | "issue"
  | "return"
  | "ask-more"
  | "send-out"
  | "receive-back"
  | "inspect"
  | "transfer"
  | "refresh-costs";

export const jobsKey = ["job-orders"] as const;
export const getJobs = (q: string, status: string, purpose: string) =>
  apiGet<JobList>(`/job-orders/?q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}&purpose=${encodeURIComponent(purpose)}`);
export const getJob = (id: number) => apiGet<JobOrder>(`/job-orders/${id}/`);
export const addJob = (values: JobValues) => apiSend<JobOrder>("POST", "/job-orders/", values);
export const changeJob = (id: number, values: JobValues) => apiSend<JobOrder>("PATCH", `/job-orders/${id}/`, values);
export const jobAction = (id: number, action: JobAction, body: JobValues = {}) =>
  apiSend<JobOrder>("POST", `/job-orders/${id}/${action}/`, body);
export const getJobLots = (id: number, store: number, item: string) =>
  apiGet<{ results: { lot_no: string; quantity: string }[] }>(`/job-orders/${id}/lots/?store=${store}&item=${encodeURIComponent(item)}`);
export const getJobSalesLines = (q: string) => apiGet<{ results: OpenSalesLine[] }>(`/job-orders/sales-lines/?q=${encodeURIComponent(q)}`);
export const getWaitingExcess = () => apiGet<{ results: WaitingExcess[] }>("/job-orders/waiting/");
export const decideExcess = (id: number, action: "approve" | "reject", reason: string) =>
  apiSend<{ status: string }>("POST", `/job-orders/excess/${id}/decide/`, { action, reason });
export const jobCardsUrl = (id: number) => `${API_BASE}/job-orders/${id}/cards/`;
export const dispatchNoteUrl = (id: number) => `${API_BASE}/job-orders/sent/${id}/note/`;
export const inspectionAction = (id: number, action: "save" | "finish" | "decide" | "director", body: JobValues) =>
  apiSend<JobOrder>("POST", `/job-orders/inspections/${id}/${action}/`, body);
