import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

/** Budgets by account, division and month, approved by the Director (P2-22). */

export type BudgetStatus = "draft" | "awaiting_approval" | "approved" | "rejected" | "replaced";

export interface BudgetSummary {
  id: number;
  year_start: string;
  label: string;
  version: number;
  status: BudgetStatus;
  notes: string;
  created_by: string;
  created_at: string;
  approved_at: string | null;
  income: string;
  costs: string;
}

export interface BudgetAccount {
  id: number;
  number: string;
  name: string;
  account_type: string;
}

export interface BudgetGridRow {
  account: BudgetAccount;
  division: string;
  amounts: Record<string, string>; // "YYYY-MM" -> amount
  total: string;
}

export interface BudgetDetail extends BudgetSummary {
  months: string[];
  rows: BudgetGridRow[];
  can_edit: boolean;
  can_approve: boolean;
  approval: {
    status: string;
    history: { action: string; action_label: string; by: string; at: string; reason: string }[];
  } | null;
  accounts?: BudgetAccount[];
  divisions?: string[];
}

export interface BudgetList {
  current_year: number;
  current_label: string;
  can_manage: boolean;
  budgets: BudgetSummary[];
}

export interface BudgetRowInput {
  account: number;
  division: string;
  amounts: Record<string, string>;
}

export const budgetsKey = ["budgets"] as const;

export const listBudgets = () => apiGet<BudgetList>("/budgets/");
export const startBudget = (year: number, notes: string) => apiSend<BudgetDetail>("POST", "/budgets/", { year, notes });
export const getBudget = (id: number) => apiGet<BudgetDetail>(`/budgets/${id}/`);
export const saveBudget = (id: number, notes: string, rows: BudgetRowInput[]) =>
  apiSend<BudgetDetail>("PUT", `/budgets/${id}/`, { notes, rows });
export const discardBudget = (id: number) => apiSend<null>("DELETE", `/budgets/${id}/`);
export const budgetAction = (id: number, action: "submit" | "approve" | "return" | "reject", text = "") =>
  apiSend<BudgetDetail>("POST", `/budgets/${id}/${action}/`, { comment: text, reason: text });
export const budgetExportUrl = (id: number) => `${API_BASE}/budgets/${id}/export/`;
export const importBudget = (id: number, file: File) => {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<BudgetDetail>(`/budgets/${id}/import/`, form, "POST");
};
