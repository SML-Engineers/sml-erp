import { apiGet, apiSend } from "./client";

/** The moulding production plan (P3-07). */

export interface PlanEntry {
  id: number;
  day: string;
  shift: string;
  machine: string;
  section: string;
  order: number;
  order_number: string;
  item: string;
  item_name: string;
  mould: string;
  minutes: number;
  quantity: string;
  notes: string;
  past: boolean;
  warnings: string[];
}

export interface PlanBoard {
  first: string;
  days: string[];
  shifts: { code: string; name: string; minutes: number }[];
  machines: { code: string; name: string; section: string; status: string; supervised: boolean }[];
  entries: PlanEntry[];
  orders: {
    id: number;
    number: string;
    item: string;
    item_name: string;
    mould: string;
    quantity: string;
    planned: string;
    first_due: string | null;
  }[];
  can_plan: boolean;
}

export interface EntryValues {
  day: string;
  shift: string;
  machine: string;
  order?: number;
  minutes: string;
  notes?: string;
}

export const planKey = ["production-plan"] as const;
export const getPlan = (start: string, days: number) =>
  apiGet<PlanBoard>(`/production-plan/?start=${encodeURIComponent(start)}&days=${days}`);
export const addEntry = (values: EntryValues) => apiSend<PlanEntry>("POST", "/production-plan/", values);
export const moveEntry = (id: number, values: Partial<EntryValues>) => apiSend<PlanEntry>("PATCH", `/production-plan/${id}/`, values);
export const removeEntry = (id: number) => apiSend<void>("DELETE", `/production-plan/${id}/`);
export const copyDay = (source: string, target: string) =>
  apiSend<{ copied: number }>("POST", "/production-plan/copy/", { source, target });
