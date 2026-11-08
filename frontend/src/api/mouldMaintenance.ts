import { apiGet, apiSend } from "./client";

/** Mould maintenance (P3-10). */

export interface MouldDue {
  code: string;
  name: string;
  owner: "company" | "customer";
  status: string;
  status_label: string;
  shot_count: number;
  since: number;
  interval: number | null;
  left: number | null;
  state: "due" | "approaching" | "ok" | "";
}

export interface MaintenanceRecord {
  id: number;
  mould: string;
  kind: "planned" | "repair";
  kind_label: string;
  done_on: string;
  shot_count: number;
  work_done: string;
  cost: string;
  done_by: string;
  by_workshop: boolean;
  created_by: string;
}

export interface MaintenanceOverview {
  moulds: MouldDue[];
  history: MaintenanceRecord[];
  total_cost: string;
  can_record: boolean;
}

export interface RecordValues {
  mould: string;
  kind: "planned" | "repair";
  done_on: string;
  work_done: string;
  cost: string;
  done_by: string;
  by_workshop: boolean;
  status: "" | "active" | "maintenance";
}

export const maintenanceKey = ["mould-maintenance"] as const;
export const getMaintenance = (mould: string) => apiGet<MaintenanceOverview>(`/mould-maintenance/?mould=${encodeURIComponent(mould)}`);
export const recordMaintenance = (values: RecordValues) => apiSend<MaintenanceOverview>("POST", "/mould-maintenance/", values);
