import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

/** Routings for machined parts (P3-03). */

export interface Operation {
  seq: number | string;
  name: string;
  section: string;
  section_name?: string;
  machine: string;
  setup_min: string;
  run_min: string;
  subcontract: boolean;
  supplier: string;
  supplier_name?: string;
  subcontract_cost: string;
  notes: string;
}

export interface Routing {
  id: number;
  item: string;
  item_name: string;
  revision: number;
  drawing_revision: string;
  status: "draft" | "awaiting" | "approved" | "obsolete";
  status_label: string;
  notes: string;
  created_by: string;
  approved_at: string | null;
  setup_min: string;
  run_min: string;
  subcontract_cost: string;
  operations: Operation[];
  returned_reason: string | null;
  can_edit: boolean;
  can_decide: boolean;
}

export interface RoutingList {
  results: Routing[];
  can_prepare: boolean;
  statuses: { value: string; label: string }[];
}

export interface RoutingValues {
  item?: string;
  drawing_revision: string;
  notes: string;
  operations: Operation[];
}

export const routingsKey = ["routings"] as const;
export const getRoutings = (q: string, status: string) =>
  apiGet<RoutingList>(`/routings/?q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}`);
export const addRouting = (values: RoutingValues) => apiSend<Routing>("POST", "/routings/", values);
export const changeRouting = (id: number, values: RoutingValues) => apiSend<Routing>("PATCH", `/routings/${id}/`, values);
export const deleteRouting = (id: number) => apiSend<void>("DELETE", `/routings/${id}/`);
export const routingAction = (id: number, action: "submit" | "approve" | "send_back" | "copy", body: Record<string, string> = {}) =>
  apiSend<Routing>("POST", `/routings/${id}/${action}/`, body);
export const routingExportUrl = `${API_BASE}/routings/export/`;

export function importRoutings(file: File, dryRun: boolean) {
  const form = new FormData();
  form.append("file", file);
  form.append("dry_run", dryRun ? "true" : "false");
  return apiUpload<{ drafts: number; saved: boolean }>("/routings/import/", form, "POST");
}
