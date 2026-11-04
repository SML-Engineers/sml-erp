import { apiGet, apiSend } from "./client";

/** Month-end revaluation of foreign-currency balances (P2-21). */

export type RevaluationKind = "receivable" | "payable" | "balance";

export interface RevaluationLineRow {
  id: number;
  kind: RevaluationKind;
  document: string;
  link: string;
  party: string;
  division: string;
  currency: string;
  open_amount: string;
  carried_lkr: string;
  rate: string;
  rate_date: string;
  revalued_lkr: string;
  difference: string;
  balance_from: string;
}

export interface RevaluationRow {
  id: number;
  month_end: string;
  status: "draft" | "posted";
  open_items_total: string;
  balances_total: string;
  journal_entry: string | null;
  reversal_entry: string | null;
  balances_entry: string | null;
  prepared_by: string;
  posted_by: string | null;
  lines: RevaluationLineRow[];
}

export interface ForeignAccount {
  id: number;
  code: string;
  name: string;
  currency: string;
  statement_balance: string | null;
  statement_date: string | null;
}

export interface RevaluationList {
  suggested_month: string;
  accounts: ForeignAccount[];
  runs: RevaluationRow[];
}

export const revaluationKey = ["revaluations"] as const;

export const listRevaluations = (monthEnd?: string) =>
  apiGet<RevaluationList>(`/revaluations/${monthEnd ? `?month_end=${monthEnd}` : ""}`);
export const prepareRevaluation = (month_end: string, balances: Record<string, string>) =>
  apiSend<RevaluationRow>("POST", "/revaluations/", { month_end, balances });
export const postRevaluation = (id: number) => apiSend<RevaluationRow>("POST", `/revaluations/${id}/post/`, {});
export const discardRevaluation = (id: number) => apiSend<null>("POST", `/revaluations/${id}/discard/`, {});
