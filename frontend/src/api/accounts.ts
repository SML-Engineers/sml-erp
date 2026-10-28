import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

export type Section = "assets" | "liabilities" | "equity" | "profit_and_loss";

export interface DetailTypeRef {
  id: number;
  name: string;
  is_active: boolean;
}

export interface AccountType {
  code: string;
  label: string;
  section: Section;
  section_label: string;
  normal_balance: "debit" | "credit";
  detail_types: DetailTypeRef[];
}

export interface LedgerAccount {
  id: number;
  number: string;
  name: string;
  full_name: string;
  depth: number;
  parent: number | null;
  account_type: string;
  account_type_label: string;
  section: Section;
  detail_type: { id: number; name: string };
  description: string;
  default_division: string | null;
  default_tax_code: string | null;
  system_role: string | null;
  is_active: boolean;
  merged_into: { id: number; name: string } | null;
  in_use: boolean;
  /** Code of the company bank or cash account this is the ledger of. */
  company_account: string | null;
}

export interface LedgerChange {
  number?: string;
  name?: string;
  account_type?: string;
  detail_type?: number | null;
  parent?: number | null;
  description?: string;
  default_division?: string | null;
  default_tax_code?: string | null;
  is_active?: boolean;
  reason?: string;
}

export interface DetailType {
  id: number;
  account_type: string;
  name: string;
  is_active: boolean;
  accounts: number;
}

export interface ChartImportResult {
  dry_run: boolean;
  created: number;
  updated: number;
  unchanged: number;
  detail_types_created: number;
}

export const chartKey = ["chart-of-accounts"];

const BASE = "/chart-of-accounts/";

export const listLedgerAccounts = (includeInactive: boolean) =>
  apiGet<LedgerAccount[]>(`${BASE}${includeInactive ? "?include_inactive=1" : ""}`);
export const listAccountTypes = () => apiGet<AccountType[]>(`${BASE}types/`);
export const createLedgerAccount = (change: LedgerChange) =>
  apiSend<LedgerAccount>("POST", BASE, change);
export const updateLedgerAccount = (id: number, change: LedgerChange) =>
  apiSend<LedgerAccount>("PATCH", `${BASE}${id}/`, change);
export const deleteLedgerAccount = (id: number, reason: string) =>
  apiSend<null>("DELETE", `${BASE}${id}/`, { reason });
export const mergeLedgerAccount = (id: number, into: number, reason: string) =>
  apiSend<LedgerAccount>("POST", `${BASE}${id}/merge/`, { into, reason });

export const listDetailTypes = () => apiGet<DetailType[]>(`${BASE}detail-types/`);
export const createDetailType = (account_type: string, name: string) =>
  apiSend<DetailType>("POST", `${BASE}detail-types/`, { account_type, name });
export const updateDetailType = (id: number, change: { name?: string; is_active?: boolean }) =>
  apiSend<DetailType>("PATCH", `${BASE}detail-types/${id}/`, change);
export const deleteDetailType = (id: number) => apiSend<null>("DELETE", `${BASE}detail-types/${id}/`);

export const chartExportUrl = `${API_BASE}${BASE}export/`;
export function importChart(file: File, reason: string, dryRun: boolean) {
  const form = new FormData();
  form.append("file", file);
  form.append("reason", reason);
  form.append("dry_run", dryRun ? "1" : "");
  return apiUpload<ChartImportResult>(`${BASE}import/`, form, "POST");
}
