import { apiGet, apiSend } from "./client";

export interface Shift {
  id: number;
  code: string;
  name: string;
  /** "HH:MM:SS" */
  start_time: string;
  end_time: string;
  break_minutes: number;
  crosses_midnight: boolean;
  working_minutes: number;
  is_active: boolean;
}

export interface RosterPattern {
  id: number;
  name: string;
  /** Shift codes in cycle order; null = Off. */
  days: (string | null)[];
  summary: { cycle_days: number; hours_per_cycle: number; average_hours_per_week: number };
  is_active: boolean;
}

export interface Crew {
  id: number;
  code: string;
  name: string;
  division: string;
  is_active: boolean;
}

export interface RosterAssignment {
  id: number;
  pattern: string;
  pattern_id: number;
  division: string;
  section: string | null;
  start_date: string;
  end_date: string | null;
  note: string;
  crews: { crew: string; start_day: number }[];
  started: boolean;
}

export interface RosterPreview {
  start: string;
  days: {
    date: string;
    shifts: { shift: string; shift_name: string; crew: string | null; section: string | null }[];
  }[];
  warnings: string[];
}

export interface ShiftChange {
  code?: string;
  name?: string;
  start_time?: string;
  end_time?: string;
  break_minutes?: number;
  is_active?: boolean;
  reason?: string;
}

export interface AssignmentChange {
  pattern?: number;
  division?: string;
  section?: string | null;
  start_date?: string;
  end_date?: string | null;
  crews?: { crew: string; start_day: number }[];
  note?: string;
  reason?: string;
}

export const rosterKeys = {
  shifts: ["settings", "shifts"],
  patterns: ["settings", "roster-patterns"],
  crews: ["settings", "crews"],
  rosters: ["settings", "rosters"],
  preview: ["settings", "rosters", "preview"],
};

export const listShifts = () => apiGet<Shift[]>("/settings/shifts/");
export const createShift = (change: ShiftChange) =>
  apiSend<Shift>("POST", "/settings/shifts/", change);
export const updateShift = (id: number, change: ShiftChange) =>
  apiSend<Shift>("PATCH", `/settings/shifts/${id}/`, change);

export const listPatterns = () => apiGet<RosterPattern[]>("/settings/roster-patterns/");
export const createPattern = (name: string, days: (string | null)[], reason = "") =>
  apiSend<RosterPattern>("POST", "/settings/roster-patterns/", { name, days, reason });
export const updatePattern = (
  id: number,
  change: { name?: string; days?: (string | null)[]; is_active?: boolean; reason?: string },
) => apiSend<RosterPattern>("PATCH", `/settings/roster-patterns/${id}/`, change);

export const listCrews = () => apiGet<Crew[]>("/settings/crews/");
export const createCrew = (division: string, code: string, name: string) =>
  apiSend<Crew>("POST", "/settings/crews/", { division, code, name });
export const updateCrew = (id: number, change: { is_active?: boolean; name?: string; reason?: string }) =>
  apiSend<Crew>("PATCH", `/settings/crews/${id}/`, change);

export const listAssignments = () => apiGet<RosterAssignment[]>("/settings/rosters/");
export const createAssignment = (change: AssignmentChange) =>
  apiSend<RosterAssignment>("POST", "/settings/rosters/", change);
export const updateAssignment = (id: number, change: AssignmentChange) =>
  apiSend<RosterAssignment>("PATCH", `/settings/rosters/${id}/`, change);
export const deleteAssignment = (id: number, reason: string) =>
  apiSend<null>("DELETE", `/settings/rosters/${id}/`, { reason });

export function getPreview(division: string, section: string, start: string, days = 28) {
  const params = new URLSearchParams({ division, start, days: String(days) });
  if (section) params.set("section", section);
  return apiGet<RosterPreview>(`/settings/rosters/preview/?${params.toString()}`);
}
