import { apiGet, apiSend } from "./client";

export type MaterialKind = "metal" | "resin" | "masterbatch" | "other";
export const MATERIAL_KINDS: MaterialKind[] = ["metal", "resin", "masterbatch", "other"];
export type MaterialForm = "round_bar" | "hex_bar" | "flat_bar" | "plate" | "tube" | "granules" | "other";
export const MATERIAL_FORMS: MaterialForm[] = ["round_bar", "hex_bar", "flat_bar", "plate", "tube", "granules", "other"];

export interface Material {
  id: number;
  code: string;
  name: string;
  kind: MaterialKind;
  form: MaterialForm;
  grade: string;
  /** g/cm³ as text, e.g. "7.850"; null when not given. */
  density: string | null;
  notes: string;
  is_active: boolean;
  /** LKR per kg in force today, as text; null when no price has started. */
  current_rate: string | null;
  in_use: boolean;
}

export interface MaterialRate {
  id: number;
  effective_from: string;
  rate: string;
  reason: string;
  created_by: string | null;
  created_at: string;
  in_force: boolean;
}

export interface DivisionRate {
  id: number;
  division: string;
  effective_from: string;
  overhead_pct: string;
  margin_pct: string;
  setup_rate: string;
  reason: string;
  created_by: string | null;
  created_at: string;
  in_force: boolean;
  /** The rates in force today for the division. */
  current: boolean;
}

export type MaterialChange = Partial<Pick<Material, "code" | "name" | "kind" | "form" | "grade" | "density" | "notes" | "is_active">> & {
  reason?: string;
};

export const costingKey = ["costing"];

export const listMaterials = (includeInactive: boolean) =>
  apiGet<Material[]>(`/costing/materials/${includeInactive ? "?include_inactive=1" : ""}`);
export const createMaterial = (change: MaterialChange) => apiSend<Material>("POST", "/costing/materials/", change);
export const updateMaterial = (id: number, change: MaterialChange) =>
  apiSend<Material>("PATCH", `/costing/materials/${id}/`, change);
export const listMaterialRates = (id: number) => apiGet<MaterialRate[]>(`/costing/materials/${id}/rates/`);
export const addMaterialRate = (id: number, rate: { effective_from: string; rate: string; reason: string }) =>
  apiSend<MaterialRate>("POST", `/costing/materials/${id}/rates/`, rate);
export const removeMaterialRate = (id: number, rateId: number, reason: string) =>
  apiSend<null>("DELETE", `/costing/materials/${id}/rates/${rateId}/`, { reason });
export const listDivisionRates = () => apiGet<DivisionRate[]>("/costing/division-rates/");
export const addDivisionRate = (rate: {
  division: string;
  effective_from: string;
  overhead_pct: string;
  margin_pct: string;
  setup_rate: string;
  reason: string;
}) => apiSend<DivisionRate>("POST", "/costing/division-rates/", rate);
export const removeDivisionRate = (id: number, reason: string) =>
  apiSend<null>("DELETE", `/costing/division-rates/${id}/`, { reason });
