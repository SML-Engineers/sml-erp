import { API_BASE, apiGet, apiSend } from "./client";

export type AdvanceStatus = "awaiting_approval" | "approved" | "rejected";
export type ReceiptMethod = "transfer" | "cheque" | "cash" | "card" | "qr";
export const RECEIPT_METHODS: ReceiptMethod[] = ["transfer", "cheque", "cash", "card", "qr"];

export interface AdvanceRow {
  id: number;
  number: string;
  receipt_date: string;
  customer: { id: number; code: string; name: string };
  quotation: { id: number; label: string } | null;
  proforma: { id: number; number: string } | null;
  sales_order: { id: number; number: string } | null;
  division: string;
  currency: string;
  /** Decimals as text, e.g. "75000.00". */
  amount: string;
  amount_lkr: string;
  /** Still to be set off against invoices (Phase 2). */
  balance_lkr: string;
  method: ReceiptMethod;
  status: AdvanceStatus;
  created_by: string;
}

export interface AdvanceDetail extends AdvanceRow {
  account: { id: number; code: string; name: string };
  reference: string;
  exchange_rate: string;
  rate_date: string | null;
  set_off_lkr: string;
  notes: string;
  journal_entry: { id: number; number: string } | null;
  approved_at: string | null;
  can_approve: boolean;
  history: { action: string; action_label: string; by: string; at: string; reason: string }[];
  /** Set off against tax invoices (P2-07). */
  set_offs?: { invoice: { id: number; number: string }; amount: string; set_off_date: string; journal_entry: string; by: string }[];
  /** The Accountant may set it off by hand against these open invoices of the customer. */
  can_set_off?: boolean;
  open_invoices?: { id: number; number: string; invoice_date: string; open_amount: string }[];
}

export interface AdvanceOptions {
  can_record: boolean;
  customers: {
    id: number;
    code: string;
    name: string;
    quotations: { id: number; label: string; division: number; currency: string; total_amount: string }[];
    proformas: { id: number; number: string; currency: string; total_amount: string; advance_amount: string }[];
    sales_orders: { id: number; number: string; customer_po: string; currency: string; total_amount: string }[];
  }[];
  divisions: { code: string; name: string }[];
  accounts: { id: number; code: string; name: string; kind: string; currency: string }[];
}

export interface AdvanceInput {
  customer: number;
  quotation: number | null;
  proforma: number | null;
  sales_order?: number | null;
  division: string;
  account: number;
  method: ReceiptMethod;
  amount: string;
  receipt_date: string;
  reference: string;
  notes: string;
}

export const advancesKey = ["advances"];

export function listAdvances(filters: { status?: string; waiting?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<AdvanceRow[]>(`/advances/${query ? `?${query}` : ""}`);
}
export const getAdvanceOptions = () => apiGet<AdvanceOptions>("/advances/options/");
export const getAdvance = (id: number) => apiGet<AdvanceDetail>(`/advances/${id}/`);
export const recordAdvance = (input: AdvanceInput) => apiSend<AdvanceDetail>("POST", "/advances/", input);
export const approveAdvance = (id: number, comment: string) =>
  apiSend<AdvanceDetail>("POST", `/advances/${id}/approve/`, { comment });
export const rejectAdvance = (id: number, reason: string) =>
  apiSend<AdvanceDetail>("POST", `/advances/${id}/reject/`, { reason });
export const receiptUrl = (id: number) => `${API_BASE}/advances/${id}/receipt/`;
export const setOffAdvance = (id: number, invoice: number, amount: string) =>
  apiSend<AdvanceDetail>("POST", `/advances/${id}/set-off/`, { invoice, amount });
