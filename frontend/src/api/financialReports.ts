import { apiGet } from "./client";

const query = (params: Record<string, string>) => {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) q.set(key, value);
  const text = q.toString();
  return text ? `?${text}` : "";
};

export interface ReportAccount {
  id: number;
  number: string;
  /** Full name, Parent:Child. */
  name: string;
  account_type: string;
  account_type_label: string;
}

/** All decimals are text, e.g. "1112750.00". */
export interface TrialBalance {
  as_at: string;
  compare_date: string | null;
  division: string | null;
  rows: { account: ReportAccount; debit: string; credit: string; compare_debit: string; compare_credit: string }[];
  total_debit: string;
  total_credit: string;
  compare_total_debit: string;
  compare_total_credit: string;
}

export interface BalanceSheet {
  as_at: string;
  compare_date: string | null;
  division: string | null;
  sections: {
    key: "assets" | "liabilities" | "equity";
    title: string;
    rows: { label: string; kind: "account" | "profit" | "company"; account: ReportAccount | null; amount: string; compare: string }[];
    total: string;
    compare_total: string;
  }[];
}

export interface LedgerLine {
  entry: { id: number; number: string };
  entry_date: string;
  narration: string;
  description: string;
  division: string | null;
  supplier: string | null;
  debit: string;
  credit: string;
  balance: string;
  source_type: string;
  source_id: string;
  /** The page of the document behind the entry, if there is one. */
  source_page: string | null;
}

export interface GeneralLedger {
  from: string;
  to: string;
  division: string | null;
  accounts: { account: ReportAccount; opening: string; closing: string; total_debit: string; total_credit: string; lines: LedgerLine[] }[];
}

export interface ProfitAndLoss {
  from: string;
  to: string;
  division: string | null;
  rows: { account: { id: number; number: string; name: string }; account_type: string; account_type_label: string; amount: string }[];
  profit: string;
}

export const reportsKey = ["financial-reports"];
export const trialBalance = (p: Record<string, string>) => apiGet<TrialBalance>(`/reports/trial-balance/${query(p)}`);
export const balanceSheet = (p: Record<string, string>) => apiGet<BalanceSheet>(`/reports/balance-sheet/${query(p)}`);
export const generalLedger = (p: Record<string, string>) => apiGet<GeneralLedger>(`/reports/general-ledger/${query(p)}`);
export const profitAndLoss = (p: Record<string, string>) => apiGet<ProfitAndLoss>(`/reports/profit-and-loss/${query(p)}`);
