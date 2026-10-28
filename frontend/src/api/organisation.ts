import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

export interface Company {
  name: string;
  registration_no: string;
  tin: string;
  vat_no: string;
  address: string;
  phone: string;
  email: string;
  website: string;
  base_currency: string;
  financial_year_start_month: number;
  has_logo: boolean;
  updated_at: string;
}

export type CompanyChange = Partial<Omit<Company, "base_currency" | "has_logo" | "updated_at">> & {
  reason?: string;
};

export type DivisionType = "production" | "shared";

export interface DivisionAdmin {
  id: number;
  code: string;
  name: string;
  division_type: DivisionType;
  /** Code in tax invoice numbers, e.g. W1 in 26SEP_W1_35; empty until the Admin sets it. */
  tax_invoice_code: string;
  /** Used on an invoice number: the tax invoice code can no longer change. */
  tax_invoice_code_in_use: boolean;
  is_active: boolean;
  /** Used on a document: the code can no longer change and it cannot be deleted. */
  in_use: boolean;
  first_used_at: string | null;
  /** How many users may work in it. */
  users: number;
  created_at: string;
}

export interface DivisionChange {
  code?: string;
  name?: string;
  division_type?: DivisionType;
  tax_invoice_code?: string;
  is_active?: boolean;
  reason?: string;
}

export const companyQueryKey = ["company"];
export const getCompany = () => apiGet<Company>("/company/");
export const updateCompany = (change: CompanyChange) => apiSend<Company>("PUT", "/company/", change);
export const logoUrl = (company: Company) =>
  `${API_BASE}/company/logo/?v=${encodeURIComponent(company.updated_at)}`;

export function uploadLogo(file: File) {
  const form = new FormData();
  form.append("logo", file);
  return apiUpload<Company>("/company/logo/", form);
}

export const removeLogo = () => apiSend<Company>("DELETE", "/company/logo/");

export const divisionsAdminKey = ["settings", "divisions"];
export const listDivisionsAdmin = () => apiGet<DivisionAdmin[]>("/settings/divisions/");
export const createDivision = (change: DivisionChange) =>
  apiSend<DivisionAdmin>("POST", "/settings/divisions/", change);
export const updateDivision = (id: number, change: DivisionChange) =>
  apiSend<DivisionAdmin>("PATCH", `/settings/divisions/${id}/`, change);
export const deleteDivision = (id: number, reason: string) =>
  apiSend<null>("DELETE", `/settings/divisions/${id}/`, { reason });

export type ResetPeriod = "daily" | "monthly" | "yearly" | "never";
export type WhenFull = "stop" | "grow";

export interface NextNumber {
  /** Null when the format has no {PP}: all divisions share one running number. */
  division: string | null;
  next: string;
}

export interface NumberSeries {
  id: number;
  document_type: string;
  name: string;
  format: string;
  reset_period: ResetPeriod;
  when_full: WhenFull;
  next_numbers: NextNumber[];
}

export interface SeriesChange {
  format: string;
  reset_period: ResetPeriod;
  when_full?: WhenFull;
  reason?: string;
}

export const numberSeriesKey = ["settings", "number-series"];
export const listNumberSeries = () => apiGet<NumberSeries[]>("/settings/number-series/");
export const updateNumberSeries = (id: number, change: SeriesChange) =>
  apiSend<NumberSeries>("PATCH", `/settings/number-series/${id}/`, change);
export const previewNumberSeries = (id: number, change: SeriesChange) =>
  apiSend<{ next_numbers: NextNumber[] }>("POST", `/settings/number-series/${id}/preview/`, change);
