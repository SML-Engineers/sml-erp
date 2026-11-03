import { API_BASE, apiGet, apiSend } from "./client";

export type CNStatus = "draft" | "awaiting_approval" | "approved" | "rejected";
export const CN_STATUSES: CNStatus[] = ["draft", "awaiting_approval", "approved", "rejected"];
export type CNKind = "return" | "price" | "other";
export const CN_KINDS: CNKind[] = ["return", "price", "other"];

/** All decimals are text. */
export interface CNSummary {
  id: number;
  /** Empty until approved. */
  number: string;
  status: CNStatus;
  status_label: string;
  kind: CNKind;
  credit_date: string;
  invoice: { id: number; number: string };
  customer: { id: number; name: string };
  division: string;
  total_amount: string;
  created_by: string;
}

export interface CNInvoiceLine {
  id: number;
  line_no: number;
  product_code: string;
  description: string;
  unit: string;
  quantity: string;
  net: string;
  tax_code: string | null;
  left_amount: string;
  left_quantity: string;
  credit_amount: string | null;
  credit_quantity: string | null;
  credit_tax: string | null;
}

export interface CNDetail extends CNSummary {
  reason: string;
  invoice_date: string;
  subtotal: string;
  tax_total: string;
  amount_in_words: string;
  lines: CNInvoiceLine[];
  taxes: { label: string; rate: string; on_tax: boolean; amount: string }[];
  journal_entry: { id: number; number: string } | null;
  can_edit: boolean;
  can_approve: boolean;
  approval: { status: string; history: { action: string; action_label: string; by: string; at: string; reason: string }[] } | null;
}

export interface InvoiceForCredit {
  id: number;
  number: string;
  invoice_date: string;
  customer: string;
  total_amount: string;
  lines: CNInvoiceLine[];
}

export interface CNInput {
  invoice?: number;
  kind: CNKind;
  reason: string;
  credit_date: string;
  lines: { invoice_line: number; amount: string; quantity: string }[];
}

export const cnKey = ["credit-notes"];

export function listCreditNotes(filters: { status?: string; waiting?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<CNSummary[]>(`/credit-notes/${query ? `?${query}` : ""}`);
}
export const invoiceForCredit = (invoice: number) => apiGet<InvoiceForCredit>(`/credit-notes/invoice/${invoice}/`);
export const getCreditNote = (id: number) => apiGet<CNDetail>(`/credit-notes/${id}/`);
export const createCreditNote = (input: CNInput) => apiSend<CNDetail>("POST", "/credit-notes/", input);
export const updateCreditNote = (id: number, input: CNInput) => apiSend<CNDetail>("PUT", `/credit-notes/${id}/`, input);
export const deleteCreditNote = (id: number) => apiSend<null>("DELETE", `/credit-notes/${id}/`);
const act = (id: number, what: string, body: object = {}) => apiSend<CNDetail>("POST", `/credit-notes/${id}/${what}/`, body);
export const submitCreditNote = (id: number) => act(id, "submit");
export const approveCreditNote = (id: number, comment = "") => act(id, "approve", { comment });
export const returnCreditNote = (id: number, reason: string) => act(id, "return", { reason });
export const rejectCreditNote = (id: number, reason: string) => act(id, "reject", { reason });
export const creditNotePdfUrl = (id: number) => `${API_BASE}/credit-notes/${id}/pdf/`;
