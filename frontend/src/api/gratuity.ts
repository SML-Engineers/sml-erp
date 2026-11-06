import { apiGet, apiSend } from "./client";

/** Gratuity (P2B-19): each employee's terms and liability; settings by the Accountant, approved
 * by the Director. */

export interface GratuitySetting {
  id: number;
  effective_from: string;
  service_from: string;
  months_per_year: string;
  after_years: number;
  reason: string;
  status: string;
  status_label: string;
  created_by: string;
  can_approve: boolean;
  can_withdraw: boolean;
}

export interface GratuityRow {
  id: number;
  number: string;
  name: string;
  division: string;
  join_date: string;
  service_from: string;
  months_per_year: string;
  after_years: number;
  by_act: boolean;
  years: number;
  wage: string;
  liability: string;
  provided: string;
  waiting: GratuitySetting | null;
}

export interface GratuityList {
  results: GratuityRow[];
  can_enter: boolean;
}

export interface GratuityValues {
  employee_id: number;
  effective_from: string;
  service_from: string;
  months_per_year: string;
  after_years: string;
  reason: string;
}

export const gratuityKey = ["gratuity"] as const;
export const getGratuity = () => apiGet<GratuityList>("/gratuity/");
export const proposeGratuity = (values: GratuityValues) => apiSend<GratuityList>("POST", "/gratuity/", values);
export const decideGratuity = (id: number, action: "approve" | "reject" | "withdraw", reason: string) =>
  apiSend<GratuityList>("POST", `/gratuity/settings/${id}/${action}/`, { reason });
