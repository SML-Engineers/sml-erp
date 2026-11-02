import { apiGet, apiPost, apiSend } from "./client";

export type RateStatus = "pending" | "confirmed" | "rejected" | "withdrawn";

export interface RateRow {
  id: number;
  effective_from: string;
  /** Percent as text, e.g. "2.125" (rule 1). */
  rate: string;
  status: RateStatus;
  reason: string;
  created_by: string;
  created_by_me: boolean;
  decided_by: string;
  decided_at: string | null;
  decision_note: string;
}

export interface TaxRates {
  id: number;
  code: string;
  name: string;
  printed_as: string;
  is_active: boolean;
  current: RateRow | null;
  coming: RateRow[];
  pending: RateRow[];
  history: RateRow[];
}

export interface TaxRatesPage {
  taxes: TaxRates[];
  can_propose: boolean;
  can_confirm: boolean;
}

export const taxRatesKey = ["settings", "tax-rates"];
export const getTaxRates = () => apiGet<TaxRatesPage>("/settings/tax-rates/");
export const proposeTaxRate = (change: { component: number; effective_from: string; rate: string; reason: string }) =>
  apiSend<TaxRatesPage>("POST", "/settings/tax-rates/", change);
export const confirmTaxRate = (id: number) => apiPost<TaxRatesPage>(`/settings/tax-rates/${id}/confirm/`);
export const rejectTaxRate = (id: number, note: string) => apiPost<TaxRatesPage>(`/settings/tax-rates/${id}/reject/`, { note });
export const withdrawTaxRate = (id: number) => apiPost<TaxRatesPage>(`/settings/tax-rates/${id}/withdraw/`);
