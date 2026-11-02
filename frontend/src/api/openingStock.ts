import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

export type OSStatus = "draft" | "awaiting_approval" | "posted" | "rejected";

export interface OSSummary {
  id: number;
  number: string;
  count_date: string;
  status: OSStatus;
  notes: string;
  lines: number;
  /** Decimals as text, e.g. "599210.00". */
  value: string;
  created_by: string;
  journal_entry: { id: number; number: string } | null;
}

export interface OSRow {
  line_no: number;
  item: { id: number; code: string; name: string };
  unit: string;
  store: string;
  division: string;
  lot_no: string;
  quantity: string;
  unit_cost: string;
  value: string;
}

export interface OSDetail extends OSSummary {
  rows: OSRow[];
  can_edit: boolean;
  can_approve: boolean;
  approval: { status: string; history: { action: string; action_label: string; by: string; at: string; reason: string }[] } | null;
}

export interface OSCheck {
  dry_run: true;
  rows: number;
  value: string;
}

export const osKey = ["opening-stock"];
export const openingTemplateUrl = `${API_BASE}/opening-stock/template/`;

export function listOpeningStock(waiting = "") {
  return apiGet<OSSummary[]>(`/opening-stock/${waiting ? `?waiting=${waiting}` : ""}`);
}
export const getOpeningStock = (id: number) => apiGet<OSDetail>(`/opening-stock/${id}/`);

function form(file: File, countDate: string, notes: string, dryRun: boolean) {
  const body = new FormData();
  body.append("file", file);
  body.append("count_date", countDate);
  body.append("notes", notes);
  if (dryRun) body.append("dry_run", "1");
  return body;
}
export const loadOpeningStock = (file: File, countDate: string, notes: string, dryRun: boolean) =>
  apiUpload<OSDetail | OSCheck>("/opening-stock/", form(file, countDate, notes, dryRun), "POST");
export const reloadOpeningStock = (id: number, file: File, countDate: string, notes: string, dryRun: boolean) =>
  apiUpload<OSDetail | OSCheck>(`/opening-stock/${id}/`, form(file, countDate, notes, dryRun), "PUT");
export const deleteOpeningStock = (id: number) => apiSend<null>("DELETE", `/opening-stock/${id}/`);
const act = (id: number, what: string, body: object = {}) => apiSend<OSDetail>("POST", `/opening-stock/${id}/${what}/`, body);
export const submitOpeningStock = (id: number) => act(id, "submit");
export const approveOpeningStock = (id: number, comment = "") => act(id, "approve", { comment });
export const returnOpeningStock = (id: number, reason: string) => act(id, "return", { reason });
export const rejectOpeningStock = (id: number, reason: string) => act(id, "reject", { reason });
