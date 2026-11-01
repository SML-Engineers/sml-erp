import { apiGet, apiSend } from "./client";

export type ReturnKind = "rejected" | "accepted";
export type ReturnStatus = "draft" | "awaiting_approval" | "confirmed";

export interface ReturnSummary {
  id: number;
  number: string;
  kind: ReturnKind;
  status: ReturnStatus;
  return_date: string;
  division: string;
  supplier: { id: number; code: string; name: string };
  grn: { id: number; number: string };
  reason: string;
  created_by: string;
}

export interface ReturnLot {
  grn_line: number;
  lot_no: string;
  item: { code: string; name: string; unit: string };
  quantity: string;
  value: string;
}

export interface ReturnDetail extends ReturnSummary {
  vehicle_no: string;
  confirmed_at: string | null;
  journal: string | null;
  lines: {
    line_no: number;
    grn_line: number;
    lot_no: string;
    item: { code: string; name: string; unit: string };
    quantity: string;
    uninvoiced_quantity: string;
    invoiced_quantity: string;
    value: string;
  }[];
  debit_notes: { number: string; invoice: { id: number; invoice_no: string }; quantity: string; total_lkr: string }[];
  available: ReturnLot[];
  can_edit: boolean;
  can_approve: boolean;
  history: { action: string; action_label: string; by: string; at: string; reason: string }[];
}

export interface ReturnInput {
  reason: string;
  vehicle_no: string;
  lines: { grn_line: number; lot_no: string; quantity: string }[];
}

export const rtnKey = ["supplier-returns"];

export function listReturns(filters: { status?: string; waiting?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<ReturnSummary[]>(`/supplier-returns/${query ? `?${query}` : ""}`);
}
export const getReturnLots = (grn: number, kind: ReturnKind) => apiGet<ReturnLot[]>(`/supplier-returns/lots/?grn=${grn}&kind=${kind}`);
export const getReturn = (id: number) => apiGet<ReturnDetail>(`/supplier-returns/${id}/`);
export const createReturn = (input: ReturnInput & { grn: number; kind: ReturnKind }) => apiSend<ReturnDetail>("POST", "/supplier-returns/", input);
export const deleteReturn = (id: number) => apiSend<void>("DELETE", `/supplier-returns/${id}/`);
export const confirmReturn = (id: number) => apiSend<ReturnDetail>("POST", `/supplier-returns/${id}/confirm/`, {});
export const approveReturn = (id: number, comment = "") => apiSend<ReturnDetail>("POST", `/supplier-returns/${id}/approve/`, { comment });
export const sendBackReturn = (id: number, reason: string) => apiSend<ReturnDetail>("POST", `/supplier-returns/${id}/return/`, { reason });
