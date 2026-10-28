import { apiGet, apiSend } from "./client";

export interface JournalSummary {
  id: number;
  number: string;
  entry_date: string;
  source_type: string;
  source_id: string;
  narration: string;
  amount: string;
  posted_by: string;
  posted_at: string;
  reversal_of: { id: number; number: string } | null;
  reversed_by: { id: number; number: string } | null;
}

export interface JournalLine {
  line_no: number;
  account: { id: number; number: string; name: string };
  division: string | null;
  supplier: { code: string; name: string } | null;
  description: string;
  debit: string;
  credit: string;
}

export interface JournalDetail extends JournalSummary {
  lines: JournalLine[];
}

export interface PeriodMonth {
  month: string;
  is_closed: boolean;
  changed_by: string | null;
  changed_at: string | null;
  entries: number;
}

export interface PeriodYear {
  year: number;
  months: PeriodMonth[];
}

export interface JournalFilter {
  from?: string;
  to?: string;
  q?: string;
}

export const journalKey = ["journal"];
export const periodsKey = ["accounting-periods"];

export function listJournal(filter: JournalFilter) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filter)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<JournalSummary[]>(`/journal/${query ? `?${query}` : ""}`);
}
export const getJournal = (id: number) => apiGet<JournalDetail>(`/journal/${id}/`);
export const reverseJournal = (id: number, reason: string) =>
  apiSend<JournalSummary>("POST", `/journal/${id}/reverse/`, { reason });

export const listPeriods = (year: number) => apiGet<PeriodYear>(`/accounting-periods/?year=${year}`);
export const changePeriod = (month: string, action: "close" | "reopen", reason: string) =>
  apiSend<PeriodYear>("POST", `/accounting-periods/${month}/${action}/`, { reason });
