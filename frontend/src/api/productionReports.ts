import { apiGet } from "./client";

/** Production reports (P3-20). Quantities and hours are decimals as text. */

export type ReportKind = "daily" | "rejects" | "downtime" | "jobs" | "material" | "moulds";
export type RejectsBy = "reason" | "part" | "mould" | "machine";

export interface DailyReport {
  rows: {
    day: string;
    section: string;
    machine: string;
    shift: string;
    good: string;
    rejected: string;
    reject_pct: string | null;
    run_h: string;
    stopped_h: string;
  }[];
  total: { good: string; rejected: string; reject_pct: string | null; run_h: string; stopped_h: string };
}

export interface RejectsReport {
  by: RejectsBy;
  rows: { key: string; name: string; rejected: string; made: string | null; reject_pct: string | null; share_pct: string | null }[];
  total_rejected: string;
}

export interface ParetoRow {
  key: string;
  name?: string;
  planned?: boolean;
  stops?: number;
  hours: string;
  share_pct: string | null;
  cumulative_pct: string | null;
}

export interface DowntimeReport {
  reasons: ParetoRow[];
  machines: ParetoRow[];
  total_h: string;
}

export interface JobsReport {
  rows: {
    id: number;
    number: string;
    part: string;
    description: string;
    status: string;
    quantity: string;
    due_date: string;
    completed_on: string | null;
    on_time: boolean | null;
    days_late: number;
    estimated_h: string;
    actual_h: string;
    time_variance_pct: string | null;
    estimated_cost: string | null;
    actual_cost: string | null;
  }[];
  completed: number;
  on_time: number;
  on_time_pct: string | null;
  late_open: number;
}

export interface MaterialReport {
  rows: { item: string; name: string; unit: string; issued: string; standard: string; difference: string; difference_pct: string | null }[];
  regrind: { item: string; name: string; unit: string; made: string; issued: string }[];
}

export interface MouldsDueReport {
  rows: { mould: string; name: string; state: "due" | "approaching"; shots_since: number; interval: number; used_pct: string | null }[];
}

export const productionReportsKey = ["production-reports"];

export function getProductionReport<T>(kind: ReportKind | "sections", params: Record<string, string>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, value);
  const text = query.toString();
  return apiGet<T>(`/production-reports/${kind}/${text ? `?${text}` : ""}`);
}
