import { apiGet, apiSend } from "./client";

/** Cash flow planner: the bank balance projected for 13 weeks (P2-25). */

export type FlowKind = "receivable" | "cheque" | "payable" | "recurring" | "what_if";

export interface CashPlan {
  today: string;
  end: string;
  opening: string;
  closing: string;
  lowest: { amount: string; day: string };
  weeks: { from: string; to: string; opening: string; in: string; out: string; closing: string; lowest: string }[];
  days: { day: string; opening: string; in: string; out: string; closing: string }[];
  flows: { day: string; amount: string; kind: FlowKind; label: string; link: string; item_id: number | null }[];
  what_ifs: { id: number; description: string; on_date: string; amount: string; created_by: string }[];
  can_plan: boolean;
}

export const cashPlanKey = ["cash-planner"] as const;

export const getCashPlan = (without: number[]) =>
  apiGet<CashPlan>(`/cash-planner/${without.length ? `?without=${without.join(",")}` : ""}`);
export const addWhatIf = (input: { description: string; on_date: string; amount: string; direction: "in" | "out" }) =>
  apiSend<CashPlan>("POST", "/cash-planner/what-ifs/", input);
export const removeWhatIf = (id: number) => apiSend<CashPlan>("DELETE", `/cash-planner/what-ifs/${id}/`);
