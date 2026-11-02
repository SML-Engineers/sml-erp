import { apiGet, apiSend } from "./client";
import type { MJLine, MJLineInput, MJStatus } from "./manualJournals";

export type Frequency = "monthly" | "quarterly" | "yearly";
export const FREQUENCIES: Frequency[] = ["monthly", "quarterly", "yearly"];
/** day_of_month 31 means the last day of the month. */
export const LAST_DAY = 31;

export interface RecurringJournal {
  id: number;
  name: string;
  narration: string;
  frequency: Frequency;
  day_of_month: number;
  start_date: string;
  end_date: string | null;
  next_date: string;
  reverse_next_month: boolean;
  is_active: boolean;
  created_by: string;
  /** Decimal as text, the total of the debits. */
  amount: string;
  made: { id: number; number: string; entry_date: string; status: MJStatus }[];
  lines: MJLine[];
}

export interface RecurringInput {
  name: string;
  narration: string;
  frequency: Frequency;
  day_of_month: number;
  start_date: string;
  end_date: string | null;
  reverse_next_month: boolean;
  lines: MJLineInput[];
}

export const rjKey = ["recurring-journals"];
export const listRecurringJournals = () => apiGet<RecurringJournal[]>("/recurring-journals/");
export const getRecurringJournal = (id: number) => apiGet<RecurringJournal>(`/recurring-journals/${id}/`);
export const createRecurringJournal = (input: RecurringInput) => apiSend<RecurringJournal>("POST", "/recurring-journals/", input);
export const updateRecurringJournal = (id: number, input: RecurringInput) =>
  apiSend<RecurringJournal>("PUT", `/recurring-journals/${id}/`, input);
export const setRecurringActive = (id: number, active: boolean) =>
  apiSend<RecurringJournal>("POST", `/recurring-journals/${id}/active/`, { active });
