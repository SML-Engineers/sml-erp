import { apiGet } from "./client";

/** OEE of the moulding machines (P3-19). Percentages are text with one decimal; null when
 * there was nothing to measure (no planned time, no run, nothing moulded). */
export interface OeeFigures {
  planned_h: string;
  planned_stops_h: string;
  run_h: string;
  unplanned_stops_h: string;
  good: string;
  made: number;
  availability: string | null;
  performance: string | null;
  quality: string | null;
  oee: string | null;
}

export interface OeeMachine extends OeeFigures {
  machine: string;
  name: string;
  section: string;
  months: ({ month: string } & OeeFigures)[];
  days: ({ day: string } & OeeFigures)[];
  shifts: ({ day: string; shift: string } & OeeFigures)[];
}

export interface OeeReport {
  start: string;
  end: string;
  sections: string[];
  total: OeeFigures;
  machines: OeeMachine[];
}

export const oeeKey = ["oee"];
export function getOee(start: string, end: string, section: string) {
  const params = new URLSearchParams({ start, end });
  if (section) params.set("section", section);
  return apiGet<OeeReport>(`/oee/?${params.toString()}`);
}
