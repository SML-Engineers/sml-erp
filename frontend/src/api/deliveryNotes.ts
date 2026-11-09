import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

export type DNStatus = "draft" | "issued" | "received" | "cancelled";
export const DN_STATUSES: DNStatus[] = ["draft", "issued", "received", "cancelled"];

export interface DNSummary {
  id: number;
  number: string;
  delivery_date: string;
  status: DNStatus;
  status_label: string;
  order: { id: number; number: string; customer_po: string };
  division: string;
  customer: { id: number; name: string };
  vehicle_no: string;
  created_by: string;
}

/** An order line as a delivery note sees it. Quantities are decimals as text. */
export interface DNOrderLine {
  id: number;
  line_no: number;
  description: string;
  drawing_no: string;
  unit: string;
  ordered: string;
  delivered_before: string;
  to_deliver: string;
  /** On this note; null when the line is not on it. */
  quantity: string | null;
  /** P3-16: item code of the finished part taken out of stock ("" = none). */
  item: string;
  /** Stock value taken out when the note was issued, "0.00" before. */
  cost: string;
  schedule: { due_date: string; quantity: string }[];
}

export interface DNDetail extends DNSummary {
  driver: string;
  delivery_address: string;
  notes: string;
  issued_by: string | null;
  issued_at: string | null;
  received_by: string;
  received_on: string | null;
  signed_copy: string | null;
  cancel_reason: string;
  /** Tax invoices of this note (P2-05). */
  invoices?: { id: number; number: string; status: string }[];
  lines: DNOrderLine[];
  can_edit: boolean;
  can_receive: boolean;
  can_cancel: boolean;
}

export interface OrderToDeliver {
  id: number;
  number: string;
  status: string;
  division: string;
  customer: string;
  customer_po: string;
}

export interface OrderForDelivery {
  id: number;
  number: string;
  customer: string;
  customer_po: string;
  delivery_address: string;
  lines: DNOrderLine[];
}

export interface DNInput {
  order?: number;
  delivery_date: string;
  vehicle_no: string;
  driver: string;
  delivery_address: string;
  notes: string;
  lines: { order_line: number; quantity: string; item?: string }[];
}

export const dnKey = ["delivery-notes"];

export function listDeliveryNotes(filters: { status?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<DNSummary[]>(`/delivery-notes/${query ? `?${query}` : ""}`);
}
export const ordersToDeliver = () => apiGet<OrderToDeliver[]>("/delivery-notes/orders/");
export const orderForDelivery = (order: number) => apiGet<OrderForDelivery>(`/delivery-notes/orders/?order=${order}`);
export const getDeliveryNote = (id: number) => apiGet<DNDetail>(`/delivery-notes/${id}/`);
export const createDeliveryNote = (input: DNInput) => apiSend<DNDetail>("POST", "/delivery-notes/", input);
export const updateDeliveryNote = (id: number, input: DNInput) => apiSend<DNDetail>("PUT", `/delivery-notes/${id}/`, input);
export const deleteDeliveryNote = (id: number) => apiSend<null>("DELETE", `/delivery-notes/${id}/`);
export const issueDeliveryNote = (id: number) => apiSend<DNDetail>("POST", `/delivery-notes/${id}/issue/`, {});
export const cancelDeliveryNote = (id: number, reason: string) => apiSend<DNDetail>("POST", `/delivery-notes/${id}/cancel/`, { reason });
export function recordReceipt(id: number, receivedBy: string, receivedOn: string, file: File | null) {
  const form = new FormData();
  form.append("received_by", receivedBy);
  form.append("received_on", receivedOn);
  if (file) form.append("signed_copy", file);
  return apiUpload<DNDetail>(`/delivery-notes/${id}/received/`, form, "POST");
}
export const deliveryPdfUrl = (id: number) => `${API_BASE}/delivery-notes/${id}/pdf/`;
export const signedCopyUrl = (id: number) => `${API_BASE}/delivery-notes/${id}/signed-copy/`;
