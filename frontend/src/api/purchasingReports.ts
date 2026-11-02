import { API_BASE, apiGet } from "./client";

export const prKey = ["purchasing-reports"];

export type ReportName = "open-orders" | "grni" | "held-invoices" | "exceptions" | "suppliers";

export interface PurchasingDashboard {
  open_orders: number;
  overdue: number;
  waiting_for_me: number;
  qc_waiting: number;
  grni: { count: number; total: string };
  held_invoices: number;
  stock_value: string;
}

export interface Trail {
  po: { id: number; label: string; status: string; total_lkr: string; parent: { id: number; label: string } | null; revisions: { id: number; label: string }[] };
  grns: { id: number; number: string; date: string; status: string }[];
  inspections: { id: number; grn: string; item: string; status: string; decision: string; accepted: string; rejected: string }[];
  invoices: { id: number; number: string; invoice_no: string; status: string; total_lkr: string; unpaid: string; set_off: string; debited: string }[];
  returns: { id: number; number: string; kind: string; status: string }[];
  vouchers: { id: number; number: string; status: string; amount: string; advance: boolean; payments: { number: string; date: string; amount: string }[] }[];
}

function query(filters: Record<string, string>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const text = params.toString();
  return text ? `?${text}` : "";
}

export type Row = Record<string, string | number | boolean | null>;

export const getReport = <T,>(name: ReportName, filters: Record<string, string>) => apiGet<T>(`/purchasing-reports/${name}/${query(filters)}`);
export const reportExportUrl = (name: ReportName, filters: Record<string, string>, format: "xlsx" | "pdf") =>
  `${API_BASE}/purchasing-reports/${name}/${query({ ...filters, export: format })}`;
export const getDashboard = (division = "") => apiGet<PurchasingDashboard>(`/purchasing-reports/dashboard/${query({ division })}`);
export const getTrail = (by: "po" | "grn" | "invoice", id: number) => apiGet<Trail>(`/purchasing-reports/trail/?${by}=${id}`);
