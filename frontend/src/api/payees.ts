import { apiGet, apiPost, apiSend } from "./client";

export type PayeeCategory = "supplier" | "utility" | "bank_card" | "government" | "employee" | "other";
export const PAYEE_CATEGORIES: PayeeCategory[] = [
  "supplier",
  "utility",
  "bank_card",
  "government",
  "employee",
  "other",
];

export interface BankAccount {
  id: number;
  bank_name: string;
  branch: string;
  account_name: string;
  account_number: string;
  swift_code: string;
  is_default: boolean;
  is_active: boolean;
  created_by: string | null;
  created_at: string;
}

export interface Payee {
  id: number;
  code: string;
  name: string;
  category: PayeeCategory;
  address: string;
  phone: string;
  email: string;
  contact_person: string;
  contact_phone: string;
  vat_no: string;
  tin: string;
  payment_terms_days: number;
  currency: string;
  notes: string;
  is_active: boolean;
  bank_changed_at: string | null;
  bank_changed_by: string | null;
  bank_change_pending: boolean;
  default_account: BankAccount | null;
}

export type PayeeChange = Partial<
  Omit<Payee, "id" | "code" | "bank_changed_at" | "bank_changed_by" | "bank_change_pending" | "default_account">
> & { reason?: string; confirm_duplicates?: boolean };

export type BankAccountChange = Partial<
  Pick<BankAccount, "bank_name" | "branch" | "account_name" | "account_number" | "swift_code" | "is_default" | "is_active">
> & { reason?: string };

export const payeesKey = ["payees"];

export function listPayees(q: string, includeInactive: boolean) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (includeInactive) params.set("include_inactive", "1");
  const query = params.toString();
  return apiGet<Payee[]>(`/payees/${query ? `?${query}` : ""}`);
}
export const createPayee = (change: PayeeChange) => apiSend<Payee>("POST", "/payees/", change);
export const updatePayee = (id: number, change: PayeeChange) =>
  apiSend<Payee>("PATCH", `/payees/${id}/`, change);
export const listBankAccounts = (id: number) => apiGet<BankAccount[]>(`/payees/${id}/bank-accounts/`);
export const addBankAccount = (id: number, change: BankAccountChange) =>
  apiSend<BankAccount>("POST", `/payees/${id}/bank-accounts/`, change);
export const updateBankAccount = (id: number, accountId: number, change: BankAccountChange) =>
  apiSend<BankAccount>("PATCH", `/payees/${id}/bank-accounts/${accountId}/`, change);
export const acknowledgeBankChange = (id: number) =>
  apiPost<Payee>(`/payees/${id}/acknowledge-bank-change/`);
