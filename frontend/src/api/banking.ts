import { apiGet, apiPost, apiSend } from "./client";

export type AccountKind = "current" | "savings" | "cash" | "petty_cash";
export const ACCOUNT_KINDS: AccountKind[] = ["current", "savings", "cash", "petty_cash"];

export interface ChequeBook {
  id: number;
  first: string;
  last: string;
  first_number: number;
  last_number: number;
  digits: number;
  received_on: string;
  is_active: boolean;
  summary: { leaves: number; used: number; left: number; next: string | null };
}

export interface CompanyAccount {
  id: number;
  code: string;
  name: string;
  kind: AccountKind;
  bank_name: string;
  branch: string;
  account_number: string;
  currency: string;
  division: string | null;
  custodian: { id: number; name: string } | null;
  float_amount: string | null;
  /** Its Bank-type account in the chart of accounts. */
  ledger_account: { id: number; number: string; name: string } | null;
  is_active: boolean;
  default_for: string[];
  cheque_books: ChequeBook[];
  in_use: boolean;
}

export interface AccountChange {
  code?: string;
  name?: string;
  kind?: AccountKind;
  bank_name?: string;
  branch?: string;
  account_number?: string;
  currency?: string;
  division?: string;
  custodian?: number | null;
  float_amount?: string | null;
  ledger_account?: number | null;
  is_active?: boolean;
  reason?: string;
}

export interface LedgerChoice {
  id: number;
  number: string;
  name: string;
  /** Code of the company account already linked to it, if any. */
  linked_to: string | null;
}

export interface ChequeRegister {
  next: string | null;
  used: { id: number; number: string; status: "issued" | "spoiled"; reason: string; used_by: string | null; used_at: string }[];
}

export const accountsKey = ["company-accounts"];

export const listAccounts = (includeClosed: boolean) =>
  apiGet<CompanyAccount[]>(`/company-accounts/${includeClosed ? "?include_closed=1" : ""}`);
export const createAccount = (change: AccountChange) =>
  apiSend<CompanyAccount>("POST", "/company-accounts/", change);
export const updateAccount = (id: number, change: AccountChange) =>
  apiSend<CompanyAccount>("PATCH", `/company-accounts/${id}/`, change);
export const addChequeBook = (id: number, book: { first_number: number; last_number: number; digits: number }) =>
  apiPost<ChequeBook>(`/company-accounts/${id}/cheque-books/`, book);
export const closeChequeBook = (id: number, bookId: number, reason: string) =>
  apiPost<ChequeBook>(`/company-accounts/${id}/cheque-books/${bookId}/close/`, { reason });
export const getRegister = (id: number) => apiGet<ChequeRegister>(`/company-accounts/${id}/cheques/`);
export const spoilCheque = (id: number, number: number, reason: string) =>
  apiPost<unknown>(`/company-accounts/${id}/cheques/`, { number, reason });
export const listLedgers = () => apiGet<LedgerChoice[]>("/company-accounts/ledgers/");
export const listCustodians = () => apiGet<{ id: number; name: string }[]>("/company-accounts/custodians/");
export const listDefaults = () =>
  apiGet<{ division: string; account: { id: number; code: string } | null }[]>(
    "/company-accounts/division-defaults/",
  );
export const setDefault = (division: string, account: number | null) =>
  apiSend<unknown>("PUT", "/company-accounts/division-defaults/", { division, account });
