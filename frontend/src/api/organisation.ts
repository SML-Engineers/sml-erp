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
