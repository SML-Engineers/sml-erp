import { apiGet, apiSend } from "./client";

export type SalesOrderStatus = "draft" | "awaiting_approval" | "open" | "partly_delivered" | "delivered" | "completed" | "cancelled";
export const SALES_ORDER_STATUSES: SalesOrderStatus[] = ["draft", "awaiting_approval", "open", "partly_delivered", "delivered", "completed", "cancelled"];
export type SalesOrderSource = "quotation" | "proforma" | "direct";

export interface SalesOrderSummary {
  id: number;
  number: string;
  order_date: string;
  status: SalesOrderStatus;
  source: SalesOrderSource;
  division: string;
  customer: { id: number; code: string; name: string };
  customer_po: string;
  currency: string;
  /** Decimals as text, e.g. "23500.00". */
  total_amount: string;
  total_lkr: string;
  /** The first delivery date of an open order. */
  next_delivery: string | null;
  created_by: string;
}

export interface Delivery {
  due_date: string;
  quantity: string;
}

export interface SalesOrderLine {
  line_no: number;
  quotation_line: number | null;
  description: string;
  drawing_no: string;
  quantity: string;
  unit: string;
  unit_price: string;
  tax_code: string | null;
  is_tooling: boolean;
  amount: string;
  discount: string;
  tax_amount: string;
  total: string;
  /** Quantity delivered by issued delivery notes (P2-04). */
  delivered?: string;
  schedule: Delivery[];
}

export interface SalesOrderDetail extends SalesOrderSummary {
  quotation: { id: number; label: string } | null;
  proforma: { id: number; number: string } | null;
  contact: { id: number; name: string } | null;
  po_date: string | null;
  exchange_rate: string;
  payment_terms: string;
  incoterm: string;
  delivery_address: string;
  notes: string;
  discount_pct: string;
  discount_total: string;
  subtotal: string;
  tax_total: string;
  cancel_reason: string;
  confirmed_at: string | null;
  lines: SalesOrderLine[];
  quotation_lines: { id: number; line_no: number; description: string; quantity: string }[];
  can_edit: boolean;
  can_approve: boolean;
  can_complete: boolean;
  can_cancel: boolean;
  approval: {
    status: string;
    history: { action: string; action_label: string; by: string; at: string; reason: string }[];
  } | null;
  advances: { id: number; number: string; status: string; amount: string }[];
  /** Its delivery notes (P2-04). */
  deliveries?: { id: number; number: string; delivery_date: string; status: string; status_label: string }[];
  can_deliver?: boolean;
}

export interface SalesOrderLineInput {
  quantity: string;
  quotation_line?: number | null;
  description?: string;
  unit_price?: string;
  unit?: string;
  drawing_no?: string;
  tax_code?: string | null;
  schedule: Delivery[];
}

export interface SalesOrderInput {
  customer_po: string;
  po_date: string | null;
  payment_terms: string;
  incoterm: string;
  delivery_address: string;
  notes: string;
  discount_pct?: string;
  lines: SalesOrderLineInput[];
}

export interface DirectOrderInput extends Partial<SalesOrderInput> {
  customer: number;
  division: string;
  lines: SalesOrderLineInput[];
}

export const salesOrdersKey = ["sales-orders"];

export function listSalesOrders(filters: { status?: string; waiting?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<SalesOrderSummary[]>(`/sales-orders/${query ? `?${query}` : ""}`);
}
export const getSalesOrder = (id: number) => apiGet<SalesOrderDetail>(`/sales-orders/${id}/`);
export const orderFromQuotation = (quotation: number) => apiSend<SalesOrderDetail>("POST", "/sales-orders/", { quotation });
export const orderFromProforma = (proforma: number) => apiSend<SalesOrderDetail>("POST", "/sales-orders/", { proforma });
export const createDirectOrder = (input: DirectOrderInput) => apiSend<SalesOrderDetail>("POST", "/sales-orders/", input);
export const updateSalesOrder = (id: number, input: SalesOrderInput) => apiSend<SalesOrderDetail>("PUT", `/sales-orders/${id}/`, input);
export const confirmSalesOrder = (id: number, comment = "") => apiSend<SalesOrderDetail>("POST", `/sales-orders/${id}/confirm/`, { comment });
export const approveSalesOrder = (id: number, comment = "") => apiSend<SalesOrderDetail>("POST", `/sales-orders/${id}/approve/`, { comment });
export const returnSalesOrder = (id: number, reason: string) => apiSend<SalesOrderDetail>("POST", `/sales-orders/${id}/return/`, { reason });
export const completeSalesOrder = (id: number) => apiSend<SalesOrderDetail>("POST", `/sales-orders/${id}/complete/`, {});
export const cancelSalesOrder = (id: number, reason: string) => apiSend<SalesOrderDetail>("POST", `/sales-orders/${id}/cancel/`, { reason });
