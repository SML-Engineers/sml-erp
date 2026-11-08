import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

/** Bills of materials (P3-04). */

export interface BomLine {
  seq: number | string;
  line_type: string;
  line_type_label?: string;
  component: string;
  component_name?: string;
  description: string;
  supplier: string;
  quantity: string;
  unit?: string;
  scrap_pct: string;
  pct_of_resin: string;
  operation_seq: number | string | null;
  issue_method: string;
  customer_supplied: boolean;
  unit_cost: string;
  stock_size: string;
  bar_length_mm: string;
  cut_length_mm: string;
  facing_mm: string;
  saw_mm: string;
  notes: string;
  standard_value?: string;
}

export interface BomOutput {
  item: string;
  name?: string;
  cavities: number | string;
  part_weight_g: string;
}

export interface Bom {
  id: number;
  item: string;
  item_name: string;
  item_unit: string;
  revision: number;
  kind: "general" | "machining" | "moulding";
  kind_label: string;
  division: string;
  drawing_revision: string;
  effective_from: string;
  base_quantity: string;
  mould: string;
  reject_pct: string;
  max_regrind_pct: string;
  status: "draft" | "awaiting" | "approved" | "obsolete";
  status_label: string;
  notes: string;
  created_by: string;
  outputs: BomOutput[];
  resin: { shot_g: string; per_piece_g: string; pieces_per_shot: number; family: boolean } | null;
  lines: BomLine[];
  cost: { material: string; machine: string; labour: string; overhead: string; mould: string; per_unit: string; missing: string[] };
  returned_reason: string | null;
  can_edit: boolean;
  can_decide: boolean;
}

export interface BomList {
  results: Bom[];
  can_prepare: boolean;
  statuses: { value: string; label: string }[];
  line_types: { value: string; label: string }[];
}

export interface BomValues {
  item?: string;
  kind: string;
  drawing_revision: string;
  base_quantity: string;
  mould: string;
  reject_pct: string;
  max_regrind_pct: string;
  notes: string;
  outputs?: BomOutput[];
  lines: BomLine[];
}

export interface WhereUsed {
  item: string;
  name: string;
  boms: { id: number; item: string; item_name: string; revision: number; status: string; quantity: string; unit: string }[];
}

export interface Comparison {
  a: string;
  b: string;
  lines: { component: string; a: string; b: string; changed: boolean }[];
}

export const bomsKey = ["boms"] as const;
export const getBoms = (q: string, status: string) =>
  apiGet<BomList>(`/boms/?q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}`);
export const addBom = (values: BomValues) => apiSend<Bom>("POST", "/boms/", values);
export const changeBom = (id: number, values: BomValues) => apiSend<Bom>("PATCH", `/boms/${id}/`, values);
export const deleteBom = (id: number) => apiSend<void>("DELETE", `/boms/${id}/`);
export const bomAction = (id: number, action: "submit" | "approve" | "send_back" | "copy", body: Record<string, string> = {}) =>
  apiSend<Bom>("POST", `/boms/${id}/${action}/`, body);
export const whereUsed = (item: string) => apiGet<WhereUsed>(`/boms/where-used/?item=${encodeURIComponent(item)}`);
export const compareBoms = (a: number, b: number) => apiGet<Comparison>(`/boms/compare/?a=${a}&b=${b}`);
export const bomExportUrl = `${API_BASE}/boms/export/`;

export function importBoms(file: File, dryRun: boolean) {
  const form = new FormData();
  form.append("file", file);
  form.append("dry_run", dryRun ? "true" : "false");
  return apiUpload<{ drafts: number; saved: boolean }>("/boms/import/", form, "POST");
}
