import { apiGet, apiSend } from "./client";

/** Overtime and attendance rules (P2B-05). */

export interface WorkRule {
  id: number;
  division: string;
  effective_from: string;
  normal_day_minutes: number;
  grace_minutes: number;
  short_leaves_per_month: number;
  short_leave_minutes: number;
  ot_min_minutes: number;
  ot_step_minutes: number;
  hourly_divisor: number;
  rate_working_day: string;
  rate_sunday: string;
  rate_holiday: string;
  reason: string;
  created_by: string | null;
  can_withdraw: boolean;
}

export interface WorkRuleList {
  results: WorkRule[];
  divisions: string[];
  can_manage: boolean;
}

export interface OvertimeRow {
  employee: { id: number; number: string; name: string; section: string };
  ot_working: string;
  ot_sunday: string;
  ot_holiday: string;
  short: string;
  short_leaves: number;
  nopay_time: string;
  nopay_days: string;
  checked_by: string | null;
  checked_at: string | null;
  can_check: boolean;
}

export interface OvertimeMonth {
  month: string;
  division: string;
  divisions: string[];
  confirmed: boolean;
  rule: WorkRule | null;
  rows: OvertimeRow[];
}

export const workRulesKey = ["work-rules"] as const;
export const overtimeKey = ["overtime"] as const;

export const listWorkRules = () => apiGet<WorkRuleList>("/work-rules/");
export const addWorkRule = (values: Record<string, string>) => apiSend<WorkRule>("POST", "/work-rules/", values);
export const withdrawWorkRule = (id: number, reason: string) => apiSend<null>("DELETE", `/work-rules/${id}/`, { reason });

export const getOvertime = (query: string) => apiGet<OvertimeMonth>(`/overtime/${query ? `?${query}` : ""}`);
export const checkOvertime = (division: string, month: string, employees: number[]) =>
  apiSend<{ checked: number }>("POST", "/overtime/check/", { division, month, employees });
