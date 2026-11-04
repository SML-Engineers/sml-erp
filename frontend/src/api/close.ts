import { apiGet, apiSend } from "./client";

/** Month-end checklist and year-end close (P2-23). */

export interface ChecklistItem {
  key: string;
  label: string;
  done: boolean;
  detail: string;
  ticked_by: string | null;
  ticked_at: string | null;
  note: string;
}

export interface Checklist {
  month: string;
  is_closed: boolean;
  can_tick: boolean;
  can_close: boolean;
  ready: boolean;
  items: ChecklistItem[];
}

export interface YearClose {
  year: number;
  label: string;
  open_months: string[];
  closed: boolean;
  can_close: boolean;
  history: {
    profit: string;
    entry: string;
    entry_date: string;
    closed_by: string;
    closed_at: string;
    reopened: boolean;
    reopen_reason: string;
    reopen_entry: string | null;
    reopened_by: string | null;
    reopened_at: string | null;
  }[];
}

export const closeKey = ["close"] as const;

export const getChecklist = (month: string) => apiGet<Checklist>(`/month-end/${month}/`);
export const tickItem = (month: string, item: string, note: string) =>
  apiSend<Checklist>("POST", `/month-end/${month}/tick/`, { item, note });
export const closeMonth = (month: string) => apiSend<unknown>("POST", `/accounting-periods/${month}/close/`, {});
export const getYear = (year?: number) => apiGet<YearClose>(`/year-end/${year ? `?year=${year}` : ""}`);
export const yearAction = (year: number, action: "close" | "reopen", reason = "") =>
  apiSend<YearClose>("POST", `/year-end/${year}/${action}/`, { reason });
