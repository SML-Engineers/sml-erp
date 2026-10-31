import { apiGet } from "./client";
import type { QuotationStatus } from "./quotations";

const query = (params: Record<string, string>) => {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) q.set(key, value);
  const text = q.toString();
  return text ? `?${text}` : "";
};

export interface RegisterRow {
  id: number;
  label: string;
  quote_date: string;
  valid_until: string;
  division: string;
  customer_id: number;
  customer: string;
  salesperson_id: number;
  salesperson: string;
  status: string;
  status_code: QuotationStatus;
  reason: string;
  currency: string;
  total: string;
  total_amount: string;
  /** Decimals as text, e.g. "23500.00". */
  total_lkr: string;
}

export interface RegisterReport {
  rows: RegisterRow[];
  summary: { status_code: QuotationStatus; status: string; count: number; total_lkr: string }[];
  salespeople: { id: number; name: string }[];
}

export interface WinLossRow {
  id: number;
  label: string;
  decided: string;
  division: string;
  customer: string;
  salesperson: string;
  outcome: string;
  won: boolean;
  reason_code: string;
  reason: string;
  note: string;
  total_lkr: string;
}

export interface WinLossFigures {
  won: number;
  won_lkr: string;
  lost: number;
  lost_lkr: string;
  /** e.g. "33.3", or null when nothing was decided. */
  win_rate: string | null;
}

export interface WinLossReport {
  rows: WinLossRow[];
  summary: {
    total: WinLossFigures & { value_win_rate: string | null };
    by_reason: (WinLossFigures & { reason_code: string; reason: string })[];
    by_salesperson: (WinLossFigures & { salesperson: string })[];
  };
}

export interface AttentionRow {
  id: number;
  kind: "approval" | "expiring";
  label: string;
  why: string;
  approvers: string;
  date: string;
  days: number;
  division: string;
  customer: string;
  salesperson: string;
  total_lkr: string;
}

export interface OpenOrderRow {
  id: number;
  due_date: string;
  number: string;
  customer: string;
  customer_po: string;
  division: string;
  item: string;
  quantity: string;
  overdue: boolean;
  status: string;
  value_lkr: string;
}

export interface OpenAdvanceRow {
  id: number;
  number: string;
  receipt_date: string;
  customer: string;
  against: string;
  division: string;
  amount: string;
  amount_lkr: string;
  set_off_lkr: string;
  balance_lkr: string;
}

export interface SalesDashboard {
  division: string;
  divisions: { code: string; name: string }[];
  can_approve: boolean;
  can_enter: boolean;
  waiting_for_me: { count: number; quotations: number; orders: number; total: string };
  awaiting_approval: number;
  expiring: number;
  live: { count: number; total: string };
  this_month: WinLossFigures & { from: string; to: string; value_win_rate: string | null };
  open_orders: { count: number; total: string };
  deliveries: { overdue: number; this_week: number };
  advances: { count: number; balance: string };
}

export const salesReportsKey = ["sales-reports"];

export const registerReport = (p: Record<string, string>) => apiGet<RegisterReport>(`/sales/reports/register/${query(p)}`);
export const winLossReport = (p: Record<string, string>) => apiGet<WinLossReport>(`/sales/reports/win-loss/${query(p)}`);
export const attentionReport = (p: Record<string, string>) => apiGet<AttentionRow[]>(`/sales/reports/attention/${query(p)}`);
export const openOrdersReport = (p: Record<string, string>) => apiGet<OpenOrderRow[]>(`/sales/reports/open-orders/${query(p)}`);
export const openAdvancesReport = (p: Record<string, string>) => apiGet<OpenAdvanceRow[]>(`/sales/reports/advances/${query(p)}`);
export const salesDashboard = (division: string) => apiGet<SalesDashboard>(`/sales/dashboard/${query({ division })}`);
