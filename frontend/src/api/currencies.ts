import { apiGet, apiSend, apiUpload } from "./client";

export interface Currency {
  id: number;
  code: string;
  name: string;
  symbol: string;
  decimal_places: number;
  is_base: boolean;
  is_active: boolean;
  latest_rate: { date: string; rate: string } | null;
}

export interface ExchangeRate {
  id: number;
  currency: string;
  date: string;
  /** Exact amounts as text (rule 1). */
  rate: string;
  buying: string | null;
  selling: string | null;
  source: "manual" | "import";
  created_by: string | null;
  created_at: string;
  used: boolean;
}

export interface RateImportResult {
  dry_run: boolean;
  added: number;
  corrected: number;
  unchanged: number;
}

export const currencyKeys = {
  list: ["settings", "currencies"],
  rates: ["settings", "exchange-rates"],
};

export const listCurrencies = () => apiGet<Currency[]>("/settings/currencies/");
export const createCurrency = (change: {
  code: string;
  name: string;
  symbol: string;
  decimal_places: number;
}) => apiSend<Currency>("POST", "/settings/currencies/", change);
export const updateCurrency = (
  code: string,
  change: { is_active?: boolean; name?: string; symbol?: string; reason?: string },
) => apiSend<Currency>("PATCH", `/settings/currencies/${code}/`, change);

export function listRates(currency: string) {
  const query = currency ? `?currency=${encodeURIComponent(currency)}` : "";
  return apiGet<ExchangeRate[]>(`/settings/exchange-rates/${query}`);
}
export const enterRate = (entry: {
  currency: string;
  date: string;
  rate: string;
  buying: string;
  selling: string;
  reason: string;
}) => apiSend<ExchangeRate>("POST", "/settings/exchange-rates/", entry);
export const removeRate = (id: number, reason: string) =>
  apiSend<null>("DELETE", `/settings/exchange-rates/${id}/`, { reason });

export function importRates(file: File, reason: string, dryRun: boolean) {
  const form = new FormData();
  form.append("file", file);
  form.append("reason", reason);
  form.append("dry_run", dryRun ? "1" : "");
  return apiUpload<RateImportResult>("/settings/exchange-rates/import/", form, "POST");
}
