import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

export type InspectionStatus = "draft" | "deviation_requested" | "decided";
export type Decision = "" | "accepted" | "rejected" | "deviation";
export type CheckKind = "number" | "pass_fail";

export interface Parameter {
  name: string;
  kind: CheckKind;
  minimum: string | null;
  maximum: string | null;
  unit: string;
  critical: boolean;
}

export interface Plan {
  id: number;
  name: string;
  item: { id: number; code: string; name: string } | null;
  category: string;
  sampling: "all" | "fixed" | "percent";
  sample_value: string | null;
  notes: string;
  is_active: boolean;
  parameters: Parameter[];
}

export interface PlanList {
  can_edit: boolean;
  categories: { value: string; label: string }[];
  plans: Plan[];
}

export interface PlanInput {
  name: string;
  item: number | null;
  category: string;
  sampling: string;
  sample_value: string | null;
  notes: string;
  is_active: boolean;
  parameters: Parameter[];
}

export interface QueueLine {
  line: number;
  grn: { id: number; number: string; receipt_date: string };
  division: string;
  supplier: string;
  item: { code: string; name: string; unit: string };
  good_quantity: string;
  packages: number;
  inspection: { id: number; status: InspectionStatus } | null;
}

export interface InspectionSummary {
  id: number;
  status: InspectionStatus;
  decision: Decision;
  automatic: boolean;
  grn: { id: number; number: string; receipt_date: string };
  division: string;
  supplier: { code: string; name: string };
  item: { code: string; name: string; unit: string };
  good_quantity: string;
  accepted_quantity: string;
  rejected_quantity: string;
  inspector: string | null;
  started_at: string;
  decided_at: string | null;
}

export interface Result extends Parameter {
  position: number;
  value: string | null;
  passed: boolean | null;
  within_limits: boolean | null;
  notes: string;
}

export interface InspectionDetail extends InspectionSummary {
  line_no: number;
  received_quantity: string;
  damaged_quantity: string;
  plan: { id: number; name: string } | null;
  sample_size: number;
  notes: string;
  reason: string;
  results: Result[];
  packages: { package_no: number; lot_no: string; supplier_lot: string; quantity: string | null; damaged: boolean; rejected: boolean }[];
  attachments: { id: number; file_name: string; uploaded_by: string; uploaded_at: string }[];
  can_edit: boolean;
  can_attach: boolean;
  can_approve: boolean;
  history: { action: string; action_label: string; by: string; at: string; reason: string }[];
}

export interface InspectionInput {
  results: { position: number; value: string | null; passed: boolean | null; notes: string }[];
  accepted_quantity?: string;
  rejected_packages?: number[];
  notes: string;
}

export const qcKey = ["inspections"];
export const plansKey = ["inspection-plans"];

export const listPlans = (includeInactive = false) => apiGet<PlanList>(`/inspection-plans/${includeInactive ? "?include_inactive=1" : ""}`);
export const createPlan = (input: PlanInput) => apiSend<Plan>("POST", "/inspection-plans/", input);
export const updatePlan = (id: number, input: PlanInput) => apiSend<Plan>("PUT", `/inspection-plans/${id}/`, input);

export const getQueue = () => apiGet<{ can_inspect: boolean; lines: QueueLine[] }>("/inspections/queue/");
export function listInspections(filters: { status?: string; waiting?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<InspectionSummary[]>(`/inspections/${query ? `?${query}` : ""}`);
}
export const startInspection = (line: number) => apiSend<InspectionDetail>("POST", "/inspections/", { line });
export const getInspection = (id: number) => apiGet<InspectionDetail>(`/inspections/${id}/`);
export const saveInspection = (id: number, input: InspectionInput) => apiSend<InspectionDetail>("PUT", `/inspections/${id}/`, input);
export const decideInspection = (id: number, decision: Decision, reason = "") =>
  apiSend<InspectionDetail>("POST", `/inspections/${id}/decide/`, { decision, reason });
export const approveDeviation = (id: number, comment = "") => apiSend<InspectionDetail>("POST", `/inspections/${id}/approve/`, { comment });
export const returnDeviation = (id: number, reason: string) => apiSend<InspectionDetail>("POST", `/inspections/${id}/return/`, { reason });
export function addInspectionFile(id: number, file: File) {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<InspectionDetail>(`/inspections/${id}/attachments/`, form, "POST");
}
export const removeInspectionFile = (id: number, attachment: number) =>
  apiSend<InspectionDetail>("DELETE", `/inspections/${id}/attachments/${attachment}/`);
export const inspectionFileUrl = (id: number, attachment: number) => `${API_BASE}/inspections/${id}/attachments/${attachment}/`;
