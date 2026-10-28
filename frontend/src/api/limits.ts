import { apiGet, apiPost, apiSend } from "./client";

export type LimitStatus = "pending" | "confirmed" | "rejected" | "withdrawn";

export interface QuotationLimit {
  id: number;
  division: string;
  effective_from: string;
  /** Exact figures as text (rule 1). */
  min_margin_pct: string;
  director_above_lkr: string;
  status: LimitStatus;
  reason: string;
  created_by: string;
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string;
  in_force: boolean;
}

export const limitsKey = ["settings", "quotation-limits"];
export const listLimits = () => apiGet<QuotationLimit[]>("/settings/quotation-limits/");
export const proposeLimit = (change: {
  division: string;
  effective_from: string;
  min_margin_pct: string;
  director_above_lkr: string;
  reason: string;
}) => apiSend<QuotationLimit>("POST", "/settings/quotation-limits/", change);
export const confirmLimit = (id: number) =>
  apiPost<QuotationLimit>(`/settings/quotation-limits/${id}/confirm/`);
export const rejectLimit = (id: number, note: string) =>
  apiPost<QuotationLimit>(`/settings/quotation-limits/${id}/reject/`, { note });
export const withdrawLimit = (id: number) =>
  apiPost<QuotationLimit>(`/settings/quotation-limits/${id}/withdraw/`);
