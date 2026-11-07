import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

/** Moulds (P3-01). */

export interface Mould {
  id: number;
  code: string;
  name: string;
  division: string;
  owner: "company" | "customer";
  owner_label: string;
  customer: string;
  customer_name: string;
  asset: string;
  cycle_time_s: string;
  shot_weight_g: string;
  runner_weight_g: string;
  tonnage_t: string;
  width_mm: string;
  height_mm: string;
  thickness_mm: string;
  pm_interval_shots: number | null;
  shot_count: number;
  pm_due_at: number | null;
  status: "active" | "maintenance" | "retired";
  status_label: string;
  notes: string;
  in_use: boolean;
  parts: { item: string; name: string; cavities: number }[];
  machines: string[];
  warnings: string[];
}

export interface MouldList {
  results: Mould[];
  can_edit: boolean;
  statuses: { value: string; label: string }[];
  machines: { code: string; name: string }[];
}

export interface MouldValues {
  code: string;
  name: string;
  division: string;
  parts: string;
  owner: string;
  customer: string;
  asset: string;
  cycle_time_s: string;
  shot_weight_g: string;
  runner_weight_g: string;
  tonnage_t: string;
  width_mm: string;
  height_mm: string;
  thickness_mm: string;
  machines: string[];
  pm_interval_shots: string;
  status: string;
  notes: string;
}

export interface ImportResult {
  created: number;
  changed: number;
  saved: boolean;
}

export const mouldsKey = ["moulds"] as const;
export const getMoulds = (q: string, status: string) =>
  apiGet<MouldList>(`/moulds/?q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}`);
export const addMould = (values: MouldValues) => apiSend<Mould>("POST", "/moulds/", values);
export const changeMould = (id: number, values: Partial<MouldValues>) => apiSend<Mould>("PATCH", `/moulds/${id}/`, values);
export const mouldExportUrl = `${API_BASE}/moulds/export/`;
export const mouldLabelsUrl = (ids: number[] = []) => `${API_BASE}/moulds/labels/${ids.length ? `?ids=${ids.join(",")}` : ""}`;

export function importMoulds(file: File, dryRun: boolean) {
  const form = new FormData();
  form.append("file", file);
  form.append("dry_run", dryRun ? "true" : "false");
  return apiUpload<ImportResult>("/moulds/import/", form, "POST");
}
