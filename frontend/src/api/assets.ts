import { apiGet, apiSend } from "./client";

/** Fixed assets and depreciation (P2-19). */

export type DepMethod = "straight_line" | "reducing_balance" | "none";
export type Approval = "awaiting" | "approved" | "rejected";

/** An asset's depreciation terms, approved by the Director (owner, 8 Nov 2026). */
export interface AssetTerms {
  id: number;
  effective_from: string;
  method: DepMethod;
  rate: string;
  life_years: number | null;
  status: Approval;
  reason: string;
}

export interface Waiting {
  rates: {
    id: number;
    asset_class: string;
    effective_from: string;
    method: DepMethod;
    rate: string;
    life_years: number | null;
    reason: string;
    by: string;
    can_decide: boolean;
  }[];
  terms: (AssetTerms & { asset: string; asset_name: string; asset_class: string; cost: string; by: string; can_decide: boolean })[];
  without_terms: number;
  can_send_all: boolean;
}

export interface AssetClassRow {
  id: number;
  code: string;
  name: string;
  cost_account: string;
  accumulated_account: string;
  expense_account: string;
  is_active: boolean;
  current: { method: DepMethod; rate: string; life_years: number | null; from: string } | null;
  rates: {
    id: number;
    effective_from: string;
    method: DepMethod;
    rate: string;
    life_years: number | null;
    status: Approval;
    reason: string;
  }[];
}

export interface FixedAssetRow {
  id: number;
  code: string;
  name: string;
  asset_class: { id: number; code: string; name: string };
  division: string;
  machine: { id: number; code: string } | null;
  serial_no: string;
  supplier: string;
  acquisition_date: string;
  depreciation_from: string;
  cost: string;
  residual_value: string;
  accumulated: string;
  book_value: string;
  status: "active" | "disposed";
  disposed_on: string | null;
  proceeds: string;
  disposal_reason: string;
  shot_count: number;
  notes: string;
  terms: AssetTerms | null;
}

export interface DepreciationRunRow {
  id: number;
  month_end: string;
  status: "draft" | "posted";
  total: string;
  journal_entry: string | null;
  prepared_by: string;
  posted_by: string | null;
  lines: {
    asset: { id: number; code: string; name: string };
    division: string;
    method: DepMethod;
    rate: string;
    book_value_before: string;
    amount: string;
  }[];
}

export const assetsKey = ["fixed-assets"];

export const listClasses = () => apiGet<AssetClassRow[]>("/asset-classes/");
export const addClassRate = (
  id: number,
  input: { effective_from: string; method: DepMethod; rate: string; life_years: string; reason: string },
) => apiSend<AssetClassRow>("POST", `/asset-classes/${id}/rates/`, input);
export const listAssets = () => apiGet<FixedAssetRow[]>("/fixed-assets/");
export const registerAsset = (input: Record<string, string | number | null>) => apiSend<FixedAssetRow>("POST", "/fixed-assets/", input);
export const disposeAsset = (id: number, input: { disposed_on: string; proceeds: string; account: number | null; reason: string }) =>
  apiSend<FixedAssetRow>("POST", `/fixed-assets/${id}/dispose/`, input);
export const listRuns = () => apiGet<{ next_month: string | null; runs: DepreciationRunRow[] }>("/depreciation/");
export const prepareRun = (month_end: string) => apiSend<DepreciationRunRow>("POST", "/depreciation/", { month_end });
export const postRun = (id: number) => apiSend<DepreciationRunRow>("POST", `/depreciation/${id}/post/`, {});
export const discardRun = (id: number) => apiSend<null>("POST", `/depreciation/${id}/discard/`, {});
export const getWaiting = () => apiGet<Waiting>("/fixed-assets/waiting/");
export const decideTerms = (id: number, action: "approve" | "reject", reason: string) =>
  apiSend<{ status: Approval }>("POST", `/fixed-assets/terms/${id}/decide/`, { action, reason });
export const decideClassRate = (id: number, action: "approve" | "reject", reason: string) =>
  apiSend<{ status: Approval }>("POST", `/asset-classes/rates/${id}/decide/`, { action, reason });
export const sendAllTerms = () => apiSend<{ sent: number }>("POST", "/fixed-assets/send-all/", {});
export const proposeTerms = (
  id: number,
  input: { effective_from: string; method: DepMethod; rate: string; life_years: string; reason: string },
) => apiSend<FixedAssetRow>("POST", `/fixed-assets/${id}/terms/`, input);
