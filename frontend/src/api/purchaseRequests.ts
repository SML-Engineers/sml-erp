import { apiGet, apiSend } from "./client";

/** Reorder levels and purchase requests (P2-13). */

export interface Ref {
  id: number;
  code: string;
  name: string;
}

export interface ReorderRow {
  id: number;
  item: Ref;
  unit: string;
  store: Ref;
  division: string;
  level: string;
  quantity: string;
  usual_supplier: Ref | null;
  suggested_supplier: Ref | null;
  on_hand: string;
  on_order: string;
  requested: string;
  low: boolean;
  alerted_at: string | null;
}

export type RequestStatus = "draft" | "awaiting_approval" | "approved" | "rejected" | "ordered" | "cancelled";

export interface RequestSummary {
  id: number;
  number: string;
  status: RequestStatus;
  division: string;
  store: string | null;
  supplier: Ref | null;
  needed_by: string | null;
  from_reorder: boolean;
  created_by: string;
  created_at: string;
  purchase_order: { id: number; label: string } | null;
}

export interface RequestDetail extends RequestSummary {
  reason: string;
  end_reason: string;
  approved_at: string | null;
  lines: { line_no: number; item: Ref; unit: string; quantity: string; notes: string; last_price: string | null }[];
  approvals: { level: number; action: string; user: string; reason: string; acted_at: string }[];
  can_edit: boolean;
  can_approve: boolean;
  can_order: boolean;
  can_cancel: boolean;
}

export interface RequestInput {
  division?: string;
  store?: number | null;
  supplier: number | null;
  needed_by: string | null;
  reason: string;
  lines: { item: number; quantity: string; notes?: string }[];
}

export const requestsKey = ["purchase-requests"];

export const listReorder = (low = false) => apiGet<ReorderRow[]>(`/reorder-levels/${low ? "?low=1" : ""}`);
export const saveReorder = (input: { item: number; store: number; level: string; quantity: string; usual_supplier: number | null }) =>
  apiSend<ReorderRow>("POST", "/reorder-levels/", input);
export const removeReorder = (id: number) => apiSend<null>("DELETE", `/reorder-levels/${id}/`);
export const requestFromReorder = (id: number) => apiSend<RequestDetail>("POST", `/reorder-levels/${id}/request/`);

export const listRequests = (status = "") =>
  apiGet<RequestSummary[]>(`/purchase-requests/${status ? `?status=${status}` : ""}`);
export const getRequest = (id: number) => apiGet<RequestDetail>(`/purchase-requests/${id}/`);
export const createRequest = (input: RequestInput) => apiSend<RequestDetail>("POST", "/purchase-requests/", input);
export const updateRequest = (id: number, input: RequestInput) =>
  apiSend<RequestDetail>("PATCH", `/purchase-requests/${id}/`, input);
export const requestAction = (
  id: number,
  action: "submit" | "approve" | "return" | "reject" | "cancel",
  text = "",
) =>
  apiSend<RequestDetail>(
    "POST",
    `/purchase-requests/${id}/${action}/`,
    action === "submit" || action === "approve" ? { comment: text } : { reason: text },
  );
export const orderRequest = (id: number, input: { supplier: number | null; prices: Record<string, string> }) =>
  apiSend<RequestDetail>("POST", `/purchase-requests/${id}/order/`, input);
