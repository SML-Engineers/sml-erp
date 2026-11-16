import { apiGet } from "./client";

/** Views and downloads (owner, 14 Nov 2026), as far as the activity log level asks. */
export interface ActivityRow {
  id: number;
  occurred_at: string;
  user_email: string;
  ip_address: string | null;
  kind: "view" | "download";
  category: "payslip" | "salary" | "bank" | "other";
  path: string;
  file_name: string;
  level: string;
}

export interface ActivityFilters {
  person?: string;
  kind?: string;
  category?: string;
  from?: string;
  to?: string;
}

export function listActivity(filters: ActivityFilters) {
  const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][]);
  const text = query.toString();
  return apiGet<ActivityRow[]>(`/activity-log/${text ? `?${text}` : ""}`);
}
