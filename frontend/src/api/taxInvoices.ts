import { API_BASE, apiGet, apiSend } from "./client";
import type { EmailDraft, EmailToSend } from "./documentEmail";

export type InvoiceStatus = "draft" | "issued";

/** All decimals are text, e.g. "139487.43". */
export interface InvoiceSummary {
  id: number;
  /** Empty for a draft: the number is given when the invoice is issued. */
  number: string;
  status: InvoiceStatus;
  invoice_date: string;
  due_date: string;
  division: string;
  customer: { id: number; name: string };
  order: { id: number; number: string };
  customer_po: string;
  total_amount: string;
  created_by: string;
}

export interface InvoiceDetail extends InvoiceSummary {
  supply_date: string;
  place_of_supply: string;
  terms: string;
  notes: string;
  customer_tin: string;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  amount_in_words: string;
  lines: {
    line_no: number;
    delivery_note: { id: number; number: string };
    product_code: string;
    description: string;
    po_no: string;
    unit: string;
    quantity: string;
    rate: string;
    amount: string;
    discount: string;
    tax_code: string | null;
    tax_amount: string;
    account: { id: number; number: string; name: string };
  }[];
  taxes: { label: string; rate: string; on_tax: boolean; amount: string }[];
  journal_entry: { id: number; number: string } | null;
  issued_by: string | null;
  issued_at: string | null;
  /** Its credit notes (P2-06). */
  credit_notes?: { id: number; number: string; status: string; credit_date: string; total_amount: string }[];
  can_credit?: boolean;
  /** What has been paid (P2-07): decimals as text. "pending" is receipts waiting for
   * approval or a post-dated cheque's date. Null on a draft. */
  settlement?: { total: string; credited: string; received: string; pending: string; set_off: string; open: string } | null;
  receipts?: { id: number; number: string; receipt_date: string; status: string; amount: string }[];
  set_offs?: { advance: { id: number; number: string }; set_off_date: string; amount: string }[];
  can_edit: boolean;
  can_issue: boolean;
  can_email: boolean;
  emails: { to: string; subject: string; status: "sent" | "failed"; error: string; sent_at: string; by: string }[];
}

export interface OrderToInvoice {
  id: number;
  number: string;
  division: string;
  customer: string;
  customer_po: string;
  currency: string;
  delivery_notes: { id: number; number: string; delivery_date: string }[];
}

export interface InvoiceHeader {
  invoice_date?: string;
  supply_date?: string;
  place_of_supply?: string;
  terms?: string;
  notes?: string;
}

export interface SalesAccountRow {
  division: { code: string; name: string };
  account: { id: number; number: string; name: string } | null;
  tooling_account: { id: number; number: string; name: string } | null;
}

export const invoicesKey = ["tax-invoices"];

export function listInvoices(filters: { status?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<InvoiceSummary[]>(`/tax-invoices/${query ? `?${query}` : ""}`);
}
export const ordersToInvoice = () => apiGet<OrderToInvoice[]>("/tax-invoices/orders/");
export const getInvoice = (id: number) => apiGet<InvoiceDetail>(`/tax-invoices/${id}/`);
export const createInvoice = (order: number, deliveryNotes: number[]) =>
  apiSend<InvoiceDetail>("POST", "/tax-invoices/", { order, delivery_notes: deliveryNotes });
export const updateInvoice = (id: number, header: InvoiceHeader) => apiSend<InvoiceDetail>("PUT", `/tax-invoices/${id}/`, header);
export const deleteInvoice = (id: number) => apiSend<null>("DELETE", `/tax-invoices/${id}/`);
export const issueInvoice = (id: number) => apiSend<InvoiceDetail>("POST", `/tax-invoices/${id}/issue/`, {});
export const invoicePdfUrl = (id: number) => `${API_BASE}/tax-invoices/${id}/pdf/`;
export const getInvoiceEmail = (id: number) => apiGet<EmailDraft>(`/tax-invoices/${id}/email/`);
export const sendInvoiceEmail = (id: number, email: EmailToSend) => apiSend<InvoiceDetail>("POST", `/tax-invoices/${id}/email/`, email);
export const listSalesAccounts = () => apiGet<SalesAccountRow[]>("/sales-accounts/");
export const setSalesAccount = (division: string, account: number, tooling: number) =>
  apiSend<SalesAccountRow[]>("PUT", "/sales-accounts/", { division, account, tooling_account: tooling });
