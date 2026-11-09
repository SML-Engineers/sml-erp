import { apiGet, apiSend } from "./client";
import type { OrderCosts } from "./orderCosts";

/** Moulding production orders (P3-06). */

export type OrderStatus = "draft" | "released" | "completed" | "closed" | "cancelled";

export interface OrderRow {
  id: number;
  number: string;
  item: string;
  item_name: string;
  quantity: string;
  unit: string;
  division: string;
  purpose: "sales" | "stock";
  sales_order: string;
  customer: string;
  first_due: string | null;
  status: OrderStatus;
  status_label: string;
}

export interface Requirement {
  seq: number;
  code: string;
  name: string;
  line_type: string;
  required: string;
  unit: string;
  on_hand: string;
  coming: string;
  other_orders: string;
  shortage: string;
  customer_supplied: boolean;
  buy: boolean;
}

export interface SalesLine {
  id: number;
  order: string;
  line_no: number;
  customer: string;
  description: string;
  quantity: string;
  unit: string;
}

export interface Due {
  due_date: string;
  quantity: string;
}

export interface ProductionOrder extends OrderRow {
  made: string;
  sales_line: SalesLine | null;
  dues: Due[];
  notes: string;
  end_reason: string;
  bom: { id: number; revision: number; item: string; status: string } | null;
  mould: string;
  family_shots: string;
  requirements: Requirement[];
  short: boolean;
  created_by: string;
  released_by: string;
  released_at: string | null;
  can_edit: boolean;
  can_release: boolean;
  can_complete: boolean;
  can_close: boolean;
  can_cancel: boolean;
  can_request: boolean;
  costs: OrderCosts | null;
  purchase_request?: { id: number; number: string };
}

export interface OrderList {
  results: OrderRow[];
  can_plan: boolean;
  statuses: { value: string; label: string }[];
}

export interface OpenSalesLine extends SalesLine {
  division: string;
  planned: string;
  left: string;
  schedule: Due[];
}

export interface OrderValues {
  item: string;
  quantity: string;
  purpose: "sales" | "stock";
  sales_line?: number;
  due_date?: string;
  dues?: Due[];
  notes: string;
}

export interface OrderWhereUsed {
  item: string;
  name: string;
  making: OrderRow[];
  making_total: string;
  needing: { id: number; number: string; item: string; required: string; unit: string }[];
}

export type OrderAction = "release" | "complete" | "close" | "cancel" | "purchase-request" | "refresh-costs";

export const ordersKey = ["production-orders"] as const;
export const getOrders = (q: string, status: string) =>
  apiGet<OrderList>(`/production-orders/?q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}`);
export const getOrder = (id: number) => apiGet<ProductionOrder>(`/production-orders/${id}/`);
export const addOrder = (values: OrderValues) => apiSend<ProductionOrder>("POST", "/production-orders/", values);
export const changeOrder = (id: number, values: Partial<OrderValues>) =>
  apiSend<ProductionOrder>("PATCH", `/production-orders/${id}/`, values);
export const orderAction = (id: number, action: OrderAction, body: Record<string, string> = {}) =>
  apiSend<ProductionOrder>("POST", `/production-orders/${id}/${action}/`, body);
export const getSalesLines = (q: string) =>
  apiGet<{ results: OpenSalesLine[] }>(`/production-orders/sales-lines/?q=${encodeURIComponent(q)}`);
export const orderWhereUsed = (item: string) => apiGet<OrderWhereUsed>(`/production-orders/where-used/?item=${encodeURIComponent(item)}`);
