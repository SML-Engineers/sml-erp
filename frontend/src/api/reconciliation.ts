import { apiGet, apiSend } from "./client";

/** Bank reconciliation (P2-16). */

export interface BookItem {
  entry: { id: number; number: string };
  date: string;
  narration: string;
  source_type: string;
  source_id: string;
  amount: string;
  reference_found?: boolean;
}

export interface Coding {
  ledger: { id: number; number: string; name: string };
  division: string | null;
  from: "rule" | "earlier";
}

export interface RecLine {
  id: number;
  date: string;
  description: string;
  reference: string;
  money_out: string;
  money_in: string;
  balance: string | null;
  match: { entry: { id: number; number: string }; narration: string; posted: boolean; by: string } | null;
  suggestion?: BookItem | null;
  coding?: Coding | null;
}

export interface Reconciliation {
  account: { id: number; code: string; name: string };
  period_end: string;
  locked_to: string | null;
  bank_balance: string | null;
  book_balance: string;
  unpresented_total: string;
  not_in_books_total: string;
  difference: string | null;
  unpresented: BookItem[];
  lines: RecLine[];
  done: { period_end: string; bank_balance: string; done_by: string; done_at: string }[];
}

export interface BankRule {
  id: number;
  account: string | null;
  account_id: number | null;
  text: string;
  direction: "any" | "out" | "in";
  ledger: { id: number; number: string; name: string };
  division: string | null;
  is_active: boolean;
}

export const reconciliationKey = ["reconciliation"];

export const getReconciliation = (account: string, periodEnd: string) =>
  apiGet<Reconciliation>(`/reconciliation/?account=${account}&period_end=${periodEnd}`);
export const getCandidates = (line: number) => apiGet<BookItem[]>(`/reconciliation/lines/${line}/candidates/`);
export const matchLine = (line: number, entry: number) => apiSend<{ ok: boolean }>("POST", "/reconciliation/match/", { line, entry });
export const unmatchLine = (line: number) => apiSend<{ ok: boolean }>("POST", "/reconciliation/unmatch/", { line });
export const postLine = (input: { line: number; account: number; division: string; description: string }) =>
  apiSend<{ ok: boolean }>("POST", "/reconciliation/post/", input);
export const acceptSuggestions = (account: string, periodEnd: string) =>
  apiSend<{ matched: number }>("POST", "/reconciliation/accept/", { account, period_end: periodEnd });
export const finishReconciliation = (account: string, periodEnd: string, note: string) =>
  apiSend<{ ok: boolean }>("POST", "/reconciliation/finish/", { account, period_end: periodEnd, note });
export const listRules = () => apiGet<BankRule[]>("/bank-rules/");
export const saveRule = (input: { text: string; direction: string; ledger: number; division: string; account: number | null }) =>
  apiSend<BankRule>("POST", "/bank-rules/", input);
