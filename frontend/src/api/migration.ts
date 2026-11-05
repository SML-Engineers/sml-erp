import { apiGet, apiSend, apiUpload } from "./client";

/** Opening balances from QuickBooks (P2-28). */

export type MigrationFile = "trial_balance" | "receivables" | "payables" | "items";

export interface MigrationReport {
  as_at: string | null;
  accounts: number;
  debits: string;
  credits: string;
  receivables: string;
  payables: string;
  stock_in_trial_balance: string;
  stock_in_item_list: string | null;
  customers: number;
  suppliers: number;
  errors: string[];
  warnings: string[];
}

export interface OpeningDoc {
  id: number;
  as_at: string;
  status: "draft" | "awaiting_approval" | "posted" | "rejected";
  report: MigrationReport;
  created_by: string;
  journal_entry: string | null;
  total_debit: string;
  total_credit: string;
  lines: { account: string; party: string; description: string; debit: string; credit: string }[];
  can_send: boolean;
  can_approve: boolean;
  history: { action: string; by: string; at: string; reason: string }[];
}

export const migrationKey = ["migration"] as const;

export interface ItemsReport {
  documents: number;
  total: string;
  errors: string[];
  warnings: string[];
  loaded?: boolean;
}

export interface MigrationState {
  can_enter: boolean;
  documents: OpeningDoc[];
  posted: boolean;
  open_invoices: { count: number; total: string };
  open_bills: { count: number; total: string };
}

export const getMigration = () => apiGet<MigrationState>("/migration/");
export function openItems(files: { receivables?: File; payables?: File }, division: string, load: boolean) {
  const form = new FormData();
  if (files.receivables) form.append("receivables", files.receivables);
  if (files.payables) form.append("payables", files.payables);
  form.append("division", division);
  if (load) form.append("load", "yes");
  return apiUpload<{ receivables?: ItemsReport; payables?: ItemsReport }>("/migration/open-items/", form, "POST");
}
export function checkFiles(files: Partial<Record<MigrationFile, File>>, make: boolean) {
  const form = new FormData();
  for (const [key, file] of Object.entries(files)) if (file) form.append(key, file);
  if (make) form.append("make", "yes");
  return apiUpload<{ report: MigrationReport; document: OpeningDoc | null }>("/migration/", form, "POST");
}
export const migrationAction = (id: number, action: "submit" | "approve" | "return" | "reject", text = "") =>
  apiSend<OpeningDoc>("POST", `/migration/${id}/${action}/`, { comment: text, reason: text });
export const deleteMigration = (id: number) => apiSend<null>("DELETE", `/migration/${id}/`);
