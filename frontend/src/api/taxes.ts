import { apiGet, apiSend } from "./client";

export type TaxKind = "charged" | "withheld";
export type TaxBase = "net" | "net_and_tax";
export type TaxUse = "both" | "sales" | "purchases";

interface AccountRef {
  id: number;
  number: string;
  name: string;
}

export interface TaxComponent {
  id: number;
  code: string;
  name: string;
  kind: TaxKind;
  sales_account: AccountRef | null;
  purchase_account: AccountRef | null;
  is_active: boolean;
  in_use: boolean;
  current_rate: string | null;
  rates: { id: number; effective_from: string; rate: string; in_force: boolean }[];
}

export interface TaxCode {
  id: number;
  code: string;
  name: string;
  description: string;
  use: TaxUse;
  is_active: boolean;
  in_use: boolean;
  /** portion_pct: the share of the amount the tax is charged on, e.g. "85.00" for SSCL on
   * manufactured goods. */
  components: { component: number; code: string; base: TaxBase; portion_pct: string }[];
}

export interface TaxOverview {
  components: TaxComponent[];
  codes: TaxCode[];
}

export interface TaxCalculation {
  code: string;
  net: string;
  lines: { code: string; name: string; rate: string; base: string; amount: string }[];
  tax: string;
  gross: string;
}

export interface ComponentChange {
  code?: string;
  name?: string;
  kind?: TaxKind;
  sales_account?: number | null;
  purchase_account?: number | null;
  is_active?: boolean;
  reason?: string;
}

export interface CodeChange {
  code?: string;
  name?: string;
  description?: string;
  use?: TaxUse;
  is_active?: boolean;
  components?: { component: number; base: TaxBase; portion_pct: string }[];
  reason?: string;
}

export const taxesKey = ["taxes"];

export const getTaxes = () => apiGet<TaxOverview>("/taxes/");
export const createComponent = (change: ComponentChange) =>
  apiSend<TaxOverview>("POST", "/taxes/components/", change);
export const updateComponent = (id: number, change: ComponentChange) =>
  apiSend<TaxOverview>("PATCH", `/taxes/components/${id}/`, change);
export const addTaxRate = (id: number, effective_from: string, rate: string, reason = "") =>
  apiSend<TaxOverview>("POST", `/taxes/components/${id}/rates/`, { effective_from, rate, reason });
export const removeTaxRate = (id: number, rateId: number, reason: string) =>
  apiSend<TaxOverview>("DELETE", `/taxes/components/${id}/rates/${rateId}/`, { reason });
export const createCode = (change: CodeChange) => apiSend<TaxOverview>("POST", "/taxes/codes/", change);
export const updateCode = (id: number, change: CodeChange) =>
  apiSend<TaxOverview>("PATCH", `/taxes/codes/${id}/`, change);
export const deleteCode = (id: number, reason: string) =>
  apiSend<TaxOverview>("DELETE", `/taxes/codes/${id}/`, { reason });
export const calculateTax = (code: string, amount: string, date?: string) => {
  const query = new URLSearchParams({ code, amount });
  if (date) query.set("date", date);
  return apiGet<TaxCalculation>(`/taxes/calculate/?${query.toString()}`);
};
