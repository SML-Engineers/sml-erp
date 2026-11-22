import type { TFunction } from "i18next";

import { approvalStatus, type StatusPeople } from "../lib/docStatus";
import { API_BASE, apiGet, apiSend } from "./client";
import type { EmailDraft } from "./quotations";

export type POStatus = "draft" | "awaiting_approval" | "approved" | "partly_received" | "received" | "closed" | "cancelled" | "revised";
export const PO_STATUSES: POStatus[] = ["draft", "awaiting_approval", "approved", "partly_received", "received", "closed", "cancelled", "revised"];
export type PayMode = "online" | "cheque" | "cash";

export interface POSummary {
  id: number;
  number: string;
  revision: number;
  label: string;
  po_date: string;
  delivery_date: string | null;
  status: POStatus;
  division: string;
  supplier: { id: number; code: string; name: string };
  currency: string;
  /** Decimals as text, e.g. "177000.00". */
  total_amount: string;
  total_lkr: string;
  created_by: string;
  /** Who it waits for and who last acted (clear statuses, owner 16 Nov 2026). */
  people?: StatusPeople | null;
}

/** "Draft of Kasun", "Waiting for Ruwan (Director)", "Returned by Ruwan", "Approved by Ruwan";
 * after that "Partly received", "Received" and so on (owner, 16 Nov 2026). */
export function poStatus(t: TFunction, o: Pick<POSummary, "status" | "created_by" | "people">): string {
  return approvalStatus(t, o, "approved") ?? t(`po.statuses.${o.status}`);
}

export interface POLine {
  line_no: number;
  item: { id: number; code: string };
  description: string;
  unit: string;
  quantity: string;
  unit_price: string;
  amount: string;
  tax_code: string | null;
  tax_amount: string;
  total: string;
  received_quantity: string;
}

export interface PODetail extends POSummary {
  deliver_to: string;
  pay_mode: PayMode;
  payment_terms: string;
  exchange_rate: string;
  notes: string;
  subtotal: string;
  tax_total: string;
  approved_at: string | null;
  end_reason: string;
  /** Who cancelled it or closed it short, and when (testing T30). */
  ended_by?: string | null;
  ended_at?: string | null;
  parent: { id: number; label: string } | null;
  revisions: { id: number; label: string; status: POStatus }[];
  lines: POLine[];
  can_edit: boolean;
  can_approve: boolean;
  can_revise: boolean;
  can_cancel: boolean;
  can_close: boolean;
  can_email: boolean;
  emails: { to: string; subject: string; status: "sent" | "failed"; error: string; sent_at: string; by: string }[];
  approval: { status: string; history: { action: string; action_label: string; by: string; at: string; reason: string }[] } | null;
}

export interface POLineInput {
  item: number;
  quantity: string;
  unit_price: string;
  tax_code: string | null;
  description: string;
}

export interface POInput {
  delivery_date: string | null;
  deliver_to: string;
  pay_mode: PayMode;
  payment_terms: string;
  notes: string;
  lines: POLineInput[];
}

export const poKey = ["purchase-orders"];

export function listPurchaseOrders(filters: { status?: string; waiting?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<POSummary[]>(`/purchase-orders/${query ? `?${query}` : ""}`);
}
export const getPurchaseOrder = (id: number) => apiGet<PODetail>(`/purchase-orders/${id}/`);
export const createPurchaseOrder = (input: POInput & { supplier: number; division: string }) =>
  apiSend<PODetail>("POST", "/purchase-orders/", input);
export const updatePurchaseOrder = (id: number, input: POInput) => apiSend<PODetail>("PUT", `/purchase-orders/${id}/`, input);
const act = (id: number, what: string, body: object = {}) => apiSend<PODetail>("POST", `/purchase-orders/${id}/${what}/`, body);
export const submitPurchaseOrder = (id: number, comment = "") => act(id, "submit", { comment });
export const approvePurchaseOrder = (id: number, comment = "") => act(id, "approve", { comment });
export const returnPurchaseOrder = (id: number, reason: string) => act(id, "return", { reason });
export const revisePurchaseOrder = (id: number, reason: string) => act(id, "revise", { reason });
export const cancelPurchaseOrder = (id: number, reason: string) => act(id, "cancel", { reason });
export const closePurchaseOrder = (id: number, reason: string) => act(id, "close", { reason });
export const purchaseOrderPdfUrl = (id: number) => `${API_BASE}/purchase-orders/${id}/pdf/`;
export const getPurchaseOrderEmail = (id: number) => apiGet<EmailDraft>(`/purchase-orders/${id}/email/`);
export const sendPurchaseOrderEmail = (id: number, message: { to: string[]; cc: string[]; subject: string; body: string }) =>
  apiSend<PODetail>("POST", `/purchase-orders/${id}/email/`, message);
