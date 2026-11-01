import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

export interface Item {
  id: number;
  code: string;
  name: string;
  description: string;
  category: string;
  unit: string;
  is_stock: boolean;
  package_type: string;
  inspection_required: boolean;
  inventory_account: { number: string; name: string } | null;
  expense_account: { number: string; name: string } | null;
  material: string | null;
  division: string | null;
  notes: string;
  is_active: boolean;
  /** Used on a document: its code is fixed and it can only be deactivated. */
  used: boolean;
}

export interface ItemOptions {
  can_enter: boolean;
  can_set_accounts: boolean;
  categories: { value: string; label: string }[];
  units: string[];
  package_types: { value: string; label: string }[];
  inventory_accounts: { number: string; name: string }[];
  expense_accounts: { number: string; name: string }[];
  materials: { code: string; name: string }[];
}

export interface ItemChange {
  code?: string;
  name?: string;
  description?: string;
  category?: string;
  unit?: string;
  is_stock?: boolean;
  package_type?: string;
  inspection_required?: boolean;
  inventory_account?: string | null;
  expense_account?: string | null;
  material?: string | null;
  division?: string | null;
  notes?: string;
}

export interface Store {
  id: number;
  code: string;
  name: string;
  division: string;
  kind: "main" | "quarantine" | "rejected";
  is_active: boolean;
  used: boolean;
}

export const itemsKey = ["items"];
export const storesKey = ["stores"];

export function listItems(q: string, category: string, includeInactive: boolean) {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (category) params.set("category", category);
  if (includeInactive) params.set("include_inactive", "1");
  const query = params.toString();
  return apiGet<Item[]>(`/items/${query ? `?${query}` : ""}`);
}
export const getItemOptions = () => apiGet<ItemOptions>("/items/options/");
export const createItem = (change: ItemChange) => apiSend<Item>("POST", "/items/", change);
export const updateItem = (id: number, change: ItemChange) => apiSend<Item>("PATCH", `/items/${id}/`, change);
export const deleteItem = (id: number) => apiSend<null>("DELETE", `/items/${id}/`);
export const setItemActive = (id: number, active: boolean, reason: string) =>
  apiSend<Item>("POST", `/items/${id}/active/`, { active, reason });
export const itemsExportUrl = (includeInactive: boolean) =>
  `${API_BASE}/items/export/${includeInactive ? "?include_inactive=1" : ""}`;
export function importItems(file: File, reason: string, dryRun: boolean) {
  const form = new FormData();
  form.append("file", file);
  form.append("reason", reason);
  form.append("dry_run", dryRun ? "1" : "");
  return apiUpload<{ dry_run: boolean; created: number; updated: number }>("/items/import/", form, "POST");
}

export const listStores = () => apiGet<Store[]>("/stores/");
export const createStore = (change: { code: string; name: string; division: string; kind: string }) =>
  apiSend<Store>("POST", "/stores/", change);
export const updateStore = (id: number, change: { name?: string; is_active?: boolean; reason?: string }) =>
  apiSend<Store>("PATCH", `/stores/${id}/`, change);
