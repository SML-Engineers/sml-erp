import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

export type SectionType = "machining" | "moulding" | "support";
export type Category = "" | "manual" | "cnc";
export type MachineStatus = "active" | "maintenance" | "retired";

export interface Section {
  id: number;
  code: string;
  name: string;
  division: string;
  section_type: SectionType;
  category: Category;
  supervisors: { id: number; name: string }[];
  is_active: boolean;
  in_use: boolean;
  machine_count: number;
}

export const MOULDING_FIELDS = [
  "clamping_force_t",
  "max_shot_weight_g",
  "screw_diameter_mm",
  "tie_bar_h_mm",
  "tie_bar_v_mm",
  "max_mould_height_mm",
  "max_mould_thickness_mm",
] as const;
export type MouldingField = (typeof MOULDING_FIELDS)[number];

export interface Machine extends Record<MouldingField, string | null> {
  id: number;
  code: string;
  name: string;
  section: string;
  division: string;
  make: string;
  model: string;
  serial_no: string;
  year: number | null;
  status: MachineStatus;
  notes: string;
  in_use: boolean;
  has_photo: boolean;
  /** Exact amount as text (LKR), or null when no rate has started. */
  current_rate: string | null;
}

export interface MachineRate {
  id: number;
  effective_from: string;
  rate: string;
  reason: string;
  created_by: string | null;
  created_at: string;
  in_force: boolean;
}

export interface SectionChange {
  code?: string;
  name?: string;
  division?: string;
  section_type?: SectionType;
  category?: Category;
  supervisors?: number[];
  is_active?: boolean;
  reason?: string;
}

export type MachineChange = Partial<
  Omit<Machine, "id" | "division" | "in_use" | "has_photo" | "current_rate">
> & { reason?: string };

export interface ImportResult {
  dry_run: boolean;
  sections_created: number;
  sections_updated: number;
  machines_created: number;
  machines_updated: number;
}

export interface PickerSection {
  id: number;
  code: string;
  name: string;
  division: string;
}

export const sectionsKey = ["settings", "sections"];
export const machinesKey = ["settings", "machines"];

export const listSections = () => apiGet<Section[]>("/settings/sections/");
export const createSection = (change: SectionChange) =>
  apiSend<Section>("POST", "/settings/sections/", change);
export const updateSection = (id: number, change: SectionChange) =>
  apiSend<Section>("PATCH", `/settings/sections/${id}/`, change);
export const deleteSection = (id: number, reason: string) =>
  apiSend<null>("DELETE", `/settings/sections/${id}/`, { reason });

export const listMachines = () => apiGet<Machine[]>("/settings/machines/");
export const createMachine = (change: MachineChange) =>
  apiSend<Machine>("POST", "/settings/machines/", change);
export const updateMachine = (id: number, change: MachineChange) =>
  apiSend<Machine>("PATCH", `/settings/machines/${id}/`, change);
export const deleteMachine = (id: number, reason: string) =>
  apiSend<null>("DELETE", `/settings/machines/${id}/`, { reason });

export const listRates = (id: number) => apiGet<MachineRate[]>(`/settings/machines/${id}/rates/`);
export const addRate = (id: number, rate: { effective_from: string; rate: string; reason: string }) =>
  apiSend<MachineRate>("POST", `/settings/machines/${id}/rates/`, rate);
export const removeRate = (id: number, rateId: number, reason: string) =>
  apiSend<null>("DELETE", `/settings/machines/${id}/rates/${rateId}/`, { reason });

export const photoUrl = (machine: Machine) => `${API_BASE}/settings/machines/${machine.id}/photo/`;
export function uploadPhoto(id: number, file: File) {
  const form = new FormData();
  form.append("photo", file);
  return apiUpload<Machine>(`/settings/machines/${id}/photo/`, form);
}

export const exportUrl = `${API_BASE}/settings/factory/export/`;
export function importFactory(file: File, reason: string, dryRun: boolean) {
  const form = new FormData();
  form.append("file", file);
  form.append("reason", reason);
  form.append("dry_run", dryRun ? "1" : "");
  return apiUpload<ImportResult>("/settings/factory/import/", form, "POST");
}

export const listPickerSections = () => apiGet<PickerSection[]>("/sections/");
export const getUserSections = (userId: number) =>
  apiGet<{ all_sections: boolean; sections: string[] }>(`/users/${userId}/sections/`);
export const setUserSections = (userId: number, all_sections: boolean, sections: string[]) =>
  apiSend<{ all_sections: boolean; sections: string[] }>("PUT", `/users/${userId}/sections/`, {
    all_sections,
    sections,
  });
