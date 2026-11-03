import { API_BASE, apiGet, apiSend } from "./client";
import type { ReceiptMethod } from "./advances";

/** Customer receipts for tax invoices (P2-07). */
export type ReceiptStatus = "awaiting_approval" | "post_dated" | "posted" | "rejected";
export const RECEIPT_STATUSES: ReceiptStatus[] = ["awaiting_approval", "post_dated", "posted", "rejected"];

export interface ReceiptRow {
  id: number;
  number: string;
  receipt_date: string;
  customer: { id: number; code: string; name: string };
  method: ReceiptMethod;
  reference: string;
  cheque_date: string | null;
  /** Decimals as text, e.g. "75000.00"; always LKR for now. */
  amount: string;
  status: ReceiptStatus;
  created_by: string;
}

export interface ReceiptDetail extends ReceiptRow {
  account: { id: number; code: string; name: string } | null;
  cheque_bank: string;
  notes: string;
  allocations: {
    invoice: { id: number; number: string; invoice_date: string; division: string; total_amount: string };
    amount: string;
  }[];
  journal_entry: { id: number; number: string } | null;
  approved_by: string | null;
  approved_at: string | null;
  posted_at: string | null;
  can_approve: boolean;
  history: { action: string; action_label: string; by: string; at: string; reason: string }[];
}

export interface OpenInvoice {
  id: number;
  number: string;
  invoice_date: string;
  due_date: string;
  division: string;
  customer_po: string;
  total_amount: string;
  open_amount: string;
}

export interface ReceiptOptions {
  can_record: boolean;
  customers: { id: number; code: string; name: string; invoices: OpenInvoice[] }[];
  accounts: { id: number; code: string; name: string; kind: string; currency: string }[];
}

export interface ReceiptInput {
  customer: number;
  method: ReceiptMethod;
  account: number | null;
  amount: string;
  receipt_date: string;
  reference: string;
  cheque_date: string | null;
  cheque_bank: string;
  notes: string;
  allocations: { invoice: number; amount: string }[];
}

export const receiptsKey = ["receipts"];

export function listReceipts(filters: { status?: string; waiting?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<ReceiptRow[]>(`/receipts/${query ? `?${query}` : ""}`);
}
export const getReceiptOptions = () => apiGet<ReceiptOptions>("/receipts/options/");
export const getReceipt = (id: number) => apiGet<ReceiptDetail>(`/receipts/${id}/`);
export const recordReceipt = (input: ReceiptInput) => apiSend<ReceiptDetail>("POST", "/receipts/", input);
export const approveReceipt = (id: number, comment: string) =>
  apiSend<ReceiptDetail>("POST", `/receipts/${id}/approve/`, { comment });
export const rejectReceipt = (id: number, reason: string) =>
  apiSend<ReceiptDetail>("POST", `/receipts/${id}/reject/`, { reason });
export const receiptPdfUrl = (id: number) => `${API_BASE}/receipts/${id}/pdf/`;
