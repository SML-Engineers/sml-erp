import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

/** Taking over from the old payroll (P2B-14). */

export interface OpeningBatch {
  id: number;
  file_name: string;
  tax_year: string;
  employees: number;
  gross: string;
  apit: string;
  gratuity: string;
  status: "awaiting" | "approved" | "rejected";
  status_label: string;
  created_by: string;
  created_at: string;
  can_decide: boolean;
}

export interface ComparedPerson {
  number: string;
  name: string;
  missing: "" | "here" | "old";
  differs: boolean;
  figures: { field: string; here: string; old: string; difference: string }[];
}

export interface Comparison {
  run: number;
  title: string;
  employees: number;
  differences: number;
  people: ComparedPerson[];
}

export interface ParallelCheck {
  id: number;
  run: number;
  title: string;
  file_name: string;
  employees: number;
  differences: number;
  people: ComparedPerson[];
  created_by: string;
  created_at: string;
  signed_off_by: string;
  signed_off_at: string | null;
  note: string;
  can_sign_off: boolean;
}

export interface Takeover {
  can_edit: boolean;
  is_director: boolean;
  batches: OpeningBatch[];
  checks: ParallelCheck[];
  runs: { id: number; title: string; status_label: string }[];
}

export interface UploadResult {
  errors: string[];
  saved: boolean;
  rows?: number;
  employees?: number;
  tax_year?: string;
  totals?: Record<string, string>;
}

export type CompareResult = { errors: string[]; saved: boolean } & Partial<Comparison>;

export const takeoverKey = ["payroll-takeover"] as const;
export const getTakeover = () => apiGet<Takeover>("/payroll-takeover/");
export const payTemplateUrl = `${API_BASE}/payroll-takeover/pay-template/`;
export const openingTemplateUrl = `${API_BASE}/payroll-takeover/opening-template/`;
export const compareTemplateUrl = (run: number) => `${API_BASE}/payroll-takeover/compare-template/${run}/`;

function upload<T>(path: string, file: File, flag: string, value: boolean) {
  const form = new FormData();
  form.append("file", file);
  form.append(flag, value ? "true" : "false");
  return apiUpload<T>(path, form, "POST");
}

export const importPay = (file: File, dryRun: boolean) => upload<UploadResult>("/payroll-takeover/pay/", file, "dry_run", dryRun);
export const importOpening = (file: File, dryRun: boolean) =>
  upload<UploadResult>("/payroll-takeover/opening/", file, "dry_run", dryRun);
export const decideOpening = (id: number, action: "approve" | "reject", reason: string) =>
  apiSend<Takeover>("POST", `/payroll-takeover/opening/${id}/${action}/`, { reason });
export const compareRun = (run: number, file: File, save: boolean) =>
  upload<CompareResult>(`/payroll-takeover/compare/${run}/`, file, "save", save);
export const signOff = (id: number, note: string) => apiSend<Takeover>("POST", `/payroll-takeover/checks/${id}/sign-off/`, { note });
