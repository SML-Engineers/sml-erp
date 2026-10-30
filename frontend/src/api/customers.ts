import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

export const INCOTERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"] as const;

export interface Contact {
  id: number;
  name: string;
  position: string;
  phone: string;
  email: string;
  is_main: boolean;
  is_active: boolean;
}

export interface Customer {
  id: number;
  code: string;
  name: string;
  billing_address: string;
  delivery_address: string;
  phone: string;
  email: string;
  vat_no: string;
  tin: string;
  currency: string;
  payment_terms_days: number;
  /** Decimal as text, e.g. "500000.00"; null = no limit set. */
  credit_limit: string | null;
  is_export: boolean;
  country: string;
  incoterm: string;
  port_of_destination: string;
  notes: string;
  is_active: boolean;
  main_contact: Contact | null;
  in_use: boolean;
}

export type CustomerChange = Partial<Omit<Customer, "id" | "code" | "main_contact" | "in_use">> & {
  reason?: string;
  confirm_duplicates?: boolean;
};

export type ContactChange = Partial<Omit<Contact, "id">>;

export interface PickerCurrency {
  code: string;
  name: string;
  symbol: string;
  decimal_places: number;
}

export interface CustomerImportResult {
  dry_run: boolean;
  created: number;
  updated: number;
}

export const customersKey = ["customers"];

export function listCustomers(q: string, includeInactive: boolean) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (includeInactive) params.set("include_inactive", "1");
  const query = params.toString();
  return apiGet<Customer[]>(`/customers/${query ? `?${query}` : ""}`);
}
export const createCustomer = (change: CustomerChange) => apiSend<Customer>("POST", "/customers/", change);
export const updateCustomer = (id: number, change: CustomerChange) =>
  apiSend<Customer>("PATCH", `/customers/${id}/`, change);
export const setCustomerActive = (id: number, is_active: boolean, reason: string) =>
  apiSend<Customer>("POST", `/customers/${id}/active/`, { is_active, reason });
export const listContacts = (id: number) => apiGet<Contact[]>(`/customers/${id}/contacts/`);
export const addContact = (id: number, change: ContactChange) =>
  apiSend<Contact>("POST", `/customers/${id}/contacts/`, change);
export const updateContact = (id: number, contactId: number, change: ContactChange) =>
  apiSend<Contact>("PATCH", `/customers/${id}/contacts/${contactId}/`, change);
export const listPickerCurrencies = () => apiGet<PickerCurrency[]>("/currencies/");

export const customersExportUrl = (includeInactive: boolean) =>
  `${API_BASE}/customers/export/${includeInactive ? "?include_inactive=1" : ""}`;
export function importCustomers(file: File, reason: string, dryRun: boolean) {
  const form = new FormData();
  form.append("file", file);
  form.append("reason", reason);
  form.append("dry_run", dryRun ? "1" : "");
  return apiUpload<CustomerImportResult>("/customers/import/", form, "POST");
}
