import { apiGet } from "./client";

/** Live order profitability (P3-17). Amounts are LKR decimals as text; null when not known
 * (no sales price for stock or internal work, no estimate yet). */

export type Rag = "red" | "amber" | "green";
export type ProfitFlag = "overrun" | "margin" | "rejects";

export interface ProfitFigures {
  quantity: string;
  good: string;
  rejected: string;
  complete_pct: string;
  price: string | null;
  value: string | null;
  earned: string | null;
  estimate_basis: "quotation" | "bom" | "";
  estimate_unit: string | null;
  estimate_cost: string | null;
  estimate_margin: string | null;
  cost: string;
  per_good: string | null;
  forecast_cost: string | null;
  forecast_revenue: string | null;
  forecast_margin: string | null;
  margin_pct: string | null;
  min_margin_pct: string;
  overrun_pct: string | null;
  overrun_limit: string | null;
  reject_pct: string | null;
  reject_limit: string | null;
  flags: ProfitFlag[];
  status: Rag;
}

export interface OrderProfit extends ProfitFigures {
  snapshots: { day: string; cost: string; forecast_margin: string | null; margin_pct: string | null; complete_pct: string; status: Rag }[];
  alerts: { kind: ProfitFlag; label: string; detail: string; at: string }[];
}

export interface ProfitRow extends ProfitFigures {
  kind: "job" | "production";
  id: number;
  number: string;
  link: string;
  status_label: string;
  division: string;
  customer: string;
  customer_id: number | null;
  sales_order: string;
  part: string;
  description: string;
  due_date: string | null;
  sections: string[];
}

/** P3-18: the final report kept when an order closes. */
export interface CloseReport {
  basis: "quotation" | "bom" | "";
  quantity: string;
  good: string;
  rejected: string;
  revenue: string | null;
  revenue_basis: "invoices" | "order" | "";
  cost: string;
  margin: string | null;
  margin_pct: string | null;
  estimate_cost: string | null;
  variance: string | null;
  rows: { key: string; label: string; estimate: string | null; actual: string; variance: string | null }[];
  material_price: string | null;
  material_usage: string | null;
  actuals: { kg_per_piece: string | null; hours_per_1000: string | null; setup_hours: string | null; cycle_s: string | null };
  quoted: { kg_per_piece: string | null; setup_hours: string | null; cycle_s: string | null };
  standard_cycle_s: string | null;
  automatic: boolean;
  closed_by: string;
  closed_at: string;
}

export interface PartActuals {
  item: string;
  name: string;
  orders: ({ number: string; closed_at: string; good: string; margin_pct: string | null } & CloseReport["actuals"])[];
  average: CloseReport["actuals"];
}

export const getPartActuals = (item: string) => apiGet<PartActuals>(`/order-profits/part/?item=${encodeURIComponent(item)}`);

export interface ProfitDashboard {
  state: "open" | "completed" | "closed";
  counts: Record<Rag, number>;
  orders: ProfitRow[];
}

export interface MouldingProfitRow {
  machine: string;
  mould: string;
  orders: string[];
  good: string;
  rejected: number;
  reject_pct: string | null;
  standard_cycle_s: string;
  actual_cycle_s: string | null;
  material_per_piece: string | null;
  cost_per_1000: string | null;
  margin_per_1000: string | null;
}

export const orderProfitsKey = ["order-profits"];

export function getOrderProfits(filters: { state?: string; division?: string; due_by?: string }) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<ProfitDashboard>(`/order-profits/${query ? `?${query}` : ""}`);
}

export const getMouldingProfits = (start: string, end: string) =>
  apiGet<{ start: string; end: string; rows: MouldingProfitRow[] }>(`/order-profits/moulding/?start=${start}&end=${end}`);

/** P3-20: closed orders' margins and the estimate accuracy. */
export type MarginGroup = "order" | "customer" | "part" | "mould" | "division";

export interface ClosedMargins {
  by: MarginGroup;
  rows: { key: string; name: string; orders: number; revenue: string; cost: string; margin: string; margin_pct: string | null }[];
  total: { revenue: string; cost: string; margin: string; margin_pct: string | null };
  without_revenue: number;
}

export interface EstimateAccuracy {
  orders: number;
  rows: { key: string; label: string; estimate: string; actual: string; variance: string; variance_pct: string | null }[];
  material_price: string;
  material_usage: string;
}

export const getClosedMargins = (by: MarginGroup, start: string, end: string) =>
  apiGet<ClosedMargins>(`/order-profits/closed/margins/?by=${by}&start=${start}&end=${end}`);
export const getEstimateAccuracy = (start: string, end: string) =>
  apiGet<EstimateAccuracy>(`/order-profits/closed/accuracy/?start=${start}&end=${end}`);
