import { apiGet, apiSend } from "./client";

/** Dated production cost rates kept by the Accountant (P3-05). */

export type RateKind = "labour" | "overhead" | "regrind" | "mould";

export interface RateBrief {
  id: number;
  rate: string;
  effective_from: string;
  source: "manual" | "payroll";
}

export interface SectionRates {
  code: string;
  name: string;
  division: string;
  labour: RateBrief | null;
  labour_next: RateBrief | null;
  overhead: RateBrief | null;
  overhead_next: RateBrief | null;
  /** Only for those who keep the rates. */
  payroll: { per_hour: string; basis: "section" | "division"; payroll: string } | null;
}

export interface MachineRates {
  code: string;
  name: string;
  section: string;
  overhead: RateBrief | null;
  overhead_next: RateBrief | null;
  in_force: string;
}

export interface MaterialRates {
  code: string;
  name: string;
  per_kg: string;
  basis: "set" | "material";
  set: RateBrief | null;
  set_next: RateBrief | null;
}

export interface MouldRates {
  code: string;
  name: string;
  rate: RateBrief | null;
  mould_cost: string;
  life_shots: number | null;
  next: RateBrief | null;
}

export interface RateRow {
  id: number;
  kind: RateKind;
  kind_label: string;
  target: string;
  effective_from: string;
  rate: string;
  mould_cost: string;
  life_shots: number | null;
  source: "manual" | "payroll";
  reason: string;
  created_by: string;
  in_force: boolean;
}

export interface CostRates {
  sections: SectionRates[];
  machines: MachineRates[];
  materials: MaterialRates[];
  moulds: MouldRates[];
  history: RateRow[];
  can_keep: boolean;
  today: string;
}

export interface RateValues {
  kind: RateKind;
  section?: string;
  machine?: string;
  material?: string;
  mould?: string;
  effective_from: string;
  rate?: string;
  mould_cost?: string;
  life_shots?: string;
  reason: string;
}

export const costRatesKey = ["cost-rates"] as const;
export const getCostRates = () => apiGet<CostRates>("/cost-rates/");
export const addCostRate = (values: RateValues) => apiSend<CostRates>("POST", "/cost-rates/", values);
export const acceptPayroll = (values: { sections: string[]; effective_from: string }) =>
  apiSend<CostRates>("POST", "/cost-rates/accept/", values);
export const removeCostRate = (id: number) => apiSend<CostRates>("DELETE", `/cost-rates/${id}/`);
