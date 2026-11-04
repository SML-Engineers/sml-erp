import { apiGet, apiSend } from "./client";

/** Stock issues, returns, adjustments and counts (P2-18). */

export interface ItemRef {
  id: number;
  code: string;
  name: string;
  unit: string;
}

export interface StockIssueDoc {
  id: number;
  number: string;
  kind: "issue" | "return";
  store: string;
  division: string;
  section: string | null;
  issue_date: string;
  purpose: string;
  returns: { id: number; number: string } | null;
  total_value: string;
  journal_entry: string | null;
  created_by: string;
  lines: { id: number; item: ItemRef; lot_no: string; quantity: string; unit_cost: string; value: string; returned: string | null }[];
}

export type AdjustmentStatus = "draft" | "awaiting_approval" | "posted" | "rejected";

export interface StockAdjustmentDoc {
  id: number;
  number: string;
  kind: "adjustment" | "write_off" | "count";
  status: AdjustmentStatus;
  store: { id: number; code: string };
  adjustment_date: string;
  reason: string;
  count: { id: number; number: string } | null;
  total_value: string;
  journal_entry: string | null;
  created_by: string;
  can_edit: boolean;
  can_submit: boolean;
  can_approve: boolean;
  lines: { item: ItemRef; lot_no: string; quantity: string; unit_cost: string | null; value: string; notes: string }[];
}

export interface StockCountDoc {
  id: number;
  number: string;
  store: { id: number; code: string };
  count_date: string;
  status: "counting" | "submitted" | "agreed" | "cancelled";
  notes: string;
  created_by: string;
  adjustment: { id: number; number: string; status: AdjustmentStatus } | null;
  lines: { item: ItemRef; lot_no: string; system_quantity: string; counted_quantity: string | null }[];
}

export const stockOpsKey = ["stock-ops"];

export const listIssues = () => apiGet<StockIssueDoc[]>("/stock-issues/");
export const getLots = (item: number, store: number) =>
  apiGet<{ unit_cost: string; lots: { lot_no: string; quantity: string }[] }>(`/stock-issues/lots/?item=${item}&store=${store}`);
export const makeIssue = (input: { store: number; issue_date: string; section: number | null; purpose: string; lines: { item: number; quantity: string; lot_no: string }[] }) =>
  apiSend<StockIssueDoc>("POST", "/stock-issues/", input);
export const returnIssue = (id: number, input: { return_date: string; lines: { line: number; quantity: string }[] }) =>
  apiSend<StockIssueDoc>("POST", `/stock-issues/${id}/return/`, input);

export const listAdjustments = () => apiGet<StockAdjustmentDoc[]>("/stock-adjustments/");
export const makeAdjustment = (input: { store: number; kind: string; reason: string; lines: { item: number; quantity: string; lot_no: string; unit_cost: string }[] }) =>
  apiSend<StockAdjustmentDoc>("POST", "/stock-adjustments/", input);
export const adjustmentAction = (id: number, action: "submit" | "approve" | "return" | "reject", text = "") =>
  apiSend<StockAdjustmentDoc>(
    "POST",
    `/stock-adjustments/${id}/${action}/`,
    action === "submit" || action === "approve" ? { comment: text } : { reason: text },
  );

export const listCounts = () => apiGet<StockCountDoc[]>("/stock-counts/");
export const startCount = (store: number, count_date: string) => apiSend<StockCountDoc>("POST", "/stock-counts/", { store, count_date });
export const enterCounts = (id: number, lines: { item: number; lot_no: string; counted_quantity: string | null }[]) =>
  apiSend<StockCountDoc>("POST", `/stock-counts/${id}/enter/`, { lines });
export const countAction = (id: number, action: "submit" | "cancel") => apiSend<StockCountDoc>("POST", `/stock-counts/${id}/${action}/`, {});
