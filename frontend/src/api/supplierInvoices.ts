import type { TFunction } from "i18next";

import { approvalStatus, firstName, type StatusPeople } from "../lib/docStatus";
import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

export type InvoiceStatus = "draft" | "held" | "exception_requested" | "posted" | "cancelled";
export const INVOICE_STATUSES: InvoiceStatus[] = ["draft", "held", "exception_requested", "posted", "cancelled"];

export interface InvoiceSummary {
  id: number;
  number: string;
  invoice_no: string;
  invoice_date: string;
  due_date: string;
  status: InvoiceStatus;
  division: string;
  supplier: { id: number; code: string; name: string };
  currency: string;
  total_amount: string;
  total_lkr: string;
  created_by: string;
  /** For clear statuses (owner, 16 Nov 2026). */
  cancelled_by?: string | null;
  people?: StatusPeople | null;
}

/** "Waiting for Ruwan (Director)" → "waiting for Ruwan (Director)", to follow "Exception, ". */
const lowerFirst = (text: string) => text.charAt(0).toLowerCase() + text.slice(1);

/** "Draft of Kumari", "Exception, waiting for Ruwan (Director)", "Held: exception returned by
 * Ruwan", "Matched and posted, exception approved by Ruwan", "Cancelled by Kumari" (owner, 16 Nov 2026). */
export function supplierInvoiceStatus(t: TFunction, i: Pick<InvoiceSummary, "status" | "created_by" | "cancelled_by" | "people">): string {
  const last = i.people?.last;
  if (i.status === "draft") return t("docStatus.draftOf", { person: firstName(i.created_by) });
  if (i.status === "exception_requested") {
    const waiting = approvalStatus(t, i, "");
    if (waiting) return t("si.exceptionWaiting", { status: lowerFirst(waiting) });
  }
  if (i.status === "held" && last?.action === "return") return t("si.exceptionReturnedBy", { person: firstName(last.by) });
  if (i.status === "held" && last?.action === "reject") return t("si.exceptionRefusedBy", { person: firstName(last.by) });
  if (i.status === "posted" && last?.action === "approve") return t("si.exceptionApprovedBy", { person: firstName(last.by) });
  if (i.status === "cancelled" && i.cancelled_by) return t("cancelled.by", { person: firstName(i.cancelled_by) });
  return t(`si.statuses.${i.status}`);
}

export interface OpenLine {
  grn_line: number;
  grn: { id: number; number: string; date: string };
  po: { id: number; label: string; currency: string };
  item: { code: string; name: string; unit: string };
  accepted_quantity: string;
  open_quantity: string;
  po_unit_price: string;
  po_tax_code: string | null;
}

export interface InvoiceLine {
  line_no: number;
  grn_line: number;
  grn: { id: number; number: string };
  po: { id: number; label: string };
  item: { code: string; name: string; unit: string };
  quantity: string;
  accepted_quantity: string;
  unit_price: string;
  po_unit_price: string;
  tax_code: string | null;
  po_tax_code: string | null;
  amount: string;
  tax_amount: string;
  total: string;
  order: string; // P3-13: the job or production order the cost belongs to
}

export interface InvoiceDetail extends InvoiceSummary {
  stated_total: string | null;
  subtotal: string;
  tax_total: string;
  discrepancies: string[];
  notes: string;
  exception_reason: string;
  cancel_reason: string;
  cancelled_at?: string | null;
  journal: string | null;
  posted_at: string | null;
  on_vouchers?: string;
  unpaid?: string;
  vouchers?: { id: number; number: string; status: string; amount: string }[];
  set_offs?: { voucher: { id: number; number: string }; amount: string; journal: string; at: string }[];
  advances_waiting?: string;
  debit_notes?: DebitNoteRow[];
  can_record_credit_note?: boolean;
  can_remove_credit_note?: boolean;
  can_set_off?: boolean;
  lines: InvoiceLine[];
  attachments: { id: number; file_name: string; uploaded_by: string; uploaded_at: string }[];
  can_edit: boolean;
  can_reopen: boolean;
  can_cancel: boolean;
  can_request_exception: boolean;
  can_approve: boolean;
  history: { action: string; action_label: string; by: string; at: string; reason: string }[];
}

export interface InvoiceInput {
  invoice_no: string;
  invoice_date: string;
  stated_total: string | null;
  notes: string;
  lines: { grn_line: number; quantity: string; unit_price: string; tax_code: string | null; order: string }[];
}

/** Our debit note, and the supplier's credit note recorded for it (owner, 22 Nov 2026). */
export interface DebitNoteRow {
  id: number;
  number: string;
  return: { id: number; number: string };
  quantity: string;
  total_lkr: string;
  credit_note: { number: string; date: string; file_name: string; recorded_by: string; recorded_at: string } | null;
}

export const siKey = ["supplier-invoices"];

export function listSupplierInvoices(filters: { status?: string; waiting?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<InvoiceSummary[]>(`/supplier-invoices/${query ? `?${query}` : ""}`);
}
export const getOpenLines = (supplier: string, division: string) =>
  apiGet<OpenLine[]>(`/supplier-invoices/open-lines/?supplier=${supplier}&division=${division}`);
export const getSupplierInvoice = (id: number) => apiGet<InvoiceDetail>(`/supplier-invoices/${id}/`);
export const createSupplierInvoice = (input: InvoiceInput & { supplier: number; division: string }) =>
  apiSend<InvoiceDetail>("POST", "/supplier-invoices/", input);
export const updateSupplierInvoice = (id: number, input: InvoiceInput) => apiSend<InvoiceDetail>("PUT", `/supplier-invoices/${id}/`, input);
export const deleteSupplierInvoice = (id: number) => apiSend<void>("DELETE", `/supplier-invoices/${id}/`);
const act = (id: number, what: string, body: object = {}) => apiSend<InvoiceDetail>("POST", `/supplier-invoices/${id}/${what}/`, body);
export const matchSupplierInvoice = (id: number) => act(id, "match");
export const reopenSupplierInvoice = (id: number) => act(id, "reopen");
export const requestInvoiceException = (id: number, reason: string) => act(id, "exception", { reason });
export const approveInvoiceException = (id: number, comment = "") => act(id, "approve", { comment });
export const returnInvoiceException = (id: number, reason: string) => act(id, "return", { reason });
export const cancelSupplierInvoice = (id: number, reason: string) => act(id, "cancel", { reason });
export function addInvoiceScan(id: number, file: File) {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<InvoiceDetail>(`/supplier-invoices/${id}/attachments/`, form, "POST");
}
export const removeInvoiceScan = (id: number, attachment: number) =>
  apiSend<InvoiceDetail>("DELETE", `/supplier-invoices/${id}/attachments/${attachment}/`);
export const invoiceScanUrl = (id: number, attachment: number) => `${API_BASE}/supplier-invoices/${id}/attachments/${attachment}/`;
export const getPayableInvoices = (supplier: number, division: string) =>
  apiGet<(InvoiceSummary & { unpaid: string })[]>(`/supplier-invoices/payable/?supplier=${supplier}&division=${division}`);
export const getAdvanceOrders = (supplier: number, division: string) =>
  apiGet<{ id: number; label: string; po_date: string; total_lkr: string; advanced: string; left: string }[]>(
    `/supplier-invoices/advance-orders/?supplier=${supplier}&division=${division}`,
  );
export const setOffAdvances = (id: number) => apiSend<InvoiceDetail>("POST", `/supplier-invoices/${id}/set-off/`, {});

const creditNotePath = (invoice: number, note: number) => `/supplier-invoices/${invoice}/debit-notes/${note}/credit-note/`;
export function recordCreditNote(invoice: number, note: number, values: { number: string; date: string; file: File }) {
  const form = new FormData();
  form.append("number", values.number);
  form.append("date", values.date);
  form.append("file", values.file);
  return apiUpload<InvoiceDetail>(creditNotePath(invoice, note), form, "POST");
}
export const removeCreditNote = (invoice: number, note: number, reason: string) =>
  apiSend<InvoiceDetail>("POST", `${creditNotePath(invoice, note)}remove/`, { reason });
export const creditNoteScanUrl = (invoice: number, note: number) => `${API_BASE}${creditNotePath(invoice, note)}`;
