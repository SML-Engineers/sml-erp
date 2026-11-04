import { API_BASE, apiGet, apiSend } from "./client";

/** Custom report builder (P2-26). */

export type FieldKind = "text" | "date" | "money" | "number";

export interface BuilderField {
  key: string;
  label: string;
  kind: FieldKind;
}

export interface Definition {
  source: string;
  columns: string[];
  filters?: { field: string; op: string; value: string }[];
  group_by?: string | null;
  sort?: { field: string; desc: boolean }[];
  period?: "" | "month" | "division";
  measure?: string | null;
}

export interface SavedReport {
  id: number;
  name: string;
  definition: Definition;
  owner: string;
  mine: boolean;
  shared_role: string | null;
  shared_role_name: string | null;
  updated_at: string;
}

export interface Builder {
  sources: { key: string; label: string; fields: BuilderField[] }[];
  ops: Record<FieldKind, Record<string, string>>;
  presets: { name: string; definition: Definition }[];
  saved: SavedReport[];
  roles: { code: string; name: string }[];
  max_rows: number;
}

export interface ReportResult {
  columns: { key: string; label: string; kind: FieldKind }[];
  rows: { kind: "line" | "subtotal" | "total"; cells: Record<string, string> }[];
  count: number;
  truncated: boolean;
}

export const builderKey = ["report-builder"] as const;

const encode = (d: Definition) => encodeURIComponent(JSON.stringify(d));

export const getBuilder = () => apiGet<Builder>("/report-builder/");
export const runReport = (d: Definition) => apiGet<ReportResult>(`/report-builder/run/?d=${encode(d)}`);
export const reportExportUrl = (d: Definition, fmt: "xlsx" | "pdf", name: string) =>
  `${API_BASE}/report-builder/run/?d=${encode(d)}&export=${fmt}&name=${encodeURIComponent(name)}`;
export const saveReport = (input: { name: string; definition: Definition; shared_role: string }, id?: number) =>
  id ? apiSend<SavedReport>("PUT", `/report-builder/saved/${id}/`, input) : apiSend<SavedReport>("POST", "/report-builder/saved/", input);
export const deleteReport = (id: number) => apiSend<null>("DELETE", `/report-builder/saved/${id}/`);
export const reportEmailDraft = (name: string) =>
  apiGet<{ from: string; ready: boolean; subject: string; body: string }>(`/report-builder/email/?name=${encodeURIComponent(name)}`);
export const emailReport = (input: { definition: Definition; name: string; to: string[]; cc: string[]; subject: string; body: string }) =>
  apiSend<{ status: string }>("POST", "/report-builder/email/", input);
