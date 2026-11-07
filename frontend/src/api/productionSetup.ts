import { apiGet, apiSend } from "./client";

/** Reject and downtime reasons, and the dated production settings (P3-02). */

export interface Reason {
  id: number;
  division: string;
  kind: "reject" | "downtime";
  code: string;
  name: string;
  planned: boolean;
  is_active: boolean;
  sort_order: number;
  in_use: boolean;
}

export interface ProductionSetting {
  id: number;
  effective_from: string;
  grace_hours: string;
  reject_alert_pct: string;
  overrun_alert_pct: string;
  min_margin_pct: string;
  reason: string;
  created_by: string;
  in_force: boolean;
}

export interface ProductionSetup {
  reasons: Reason[];
  divisions: string[];
  settings: ProductionSetting[];
  current: number;
  can_manage: boolean;
}

export interface SettingValues {
  effective_from: string;
  grace_hours: string;
  reject_alert_pct: string;
  overrun_alert_pct: string;
  min_margin_pct: string;
  reason: string;
}

export const setupKey = ["production-setup"] as const;
export const getSetup = () => apiGet<ProductionSetup>("/production-setup/");
export const addSetting = (values: SettingValues) => apiSend<ProductionSetup>("POST", "/production-setup/", values);
export const addReason = (values: { division: string; kind: string; code: string; name: string; planned: boolean }) =>
  apiSend<ProductionSetup>("POST", "/production-reasons/", values);
export const changeReason = (id: number, values: Partial<Pick<Reason, "name" | "planned" | "is_active" | "sort_order">>) =>
  apiSend<ProductionSetup>("PATCH", `/production-reasons/${id}/`, values);
