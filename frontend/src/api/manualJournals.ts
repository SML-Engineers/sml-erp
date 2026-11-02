import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

export type MJStatus = "draft" | "awaiting_approval" | "posted" | "rejected";
export const MJ_STATUSES: MJStatus[] = ["draft", "awaiting_approval", "posted", "rejected"];

export interface MJSummary {
  id: number;
  number: string;
  entry_date: string;
  narration: string;
  status: MJStatus;
  status_label: string;
  /** Decimals as text, e.g. "25000.00". */
  total_debit: string;
  total_credit: string;
  created_by: string;
  journal_entry: { id: number; number: string } | null;
  /** An accrual: reversed automatically on this date (the first of the next month). */
  reverse_on?: string | null;
  /** The recurring journal that made this draft, if any. */
  recurring?: { id: number; name: string } | null;
}

export interface MJLine {
  line_no: number;
  account: { id: number; number: string; name: string; account_type: string };
  division: string | null;
  supplier: { id: number; code: string; name: string } | null;
  description: string;
  debit: string;
  credit: string;
}

export interface MJDetail extends MJSummary {
  lines: MJLine[];
  attachments: { id: number; file_name: string; uploaded_by: string; uploaded_at: string }[];
  can_edit: boolean;
  can_approve: boolean;
  approval: { status: string; history: { action: string; action_label: string; by: string; at: string; reason: string }[] } | null;
}

export interface MJLineInput {
  account: number;
  debit: string;
  credit: string;
  division: string | null;
  supplier: number | null;
  description: string;
}

export interface MJInput {
  entry_date: string;
  narration: string;
  reverse_next_month?: boolean;
  lines: MJLineInput[];
}

export const mjKey = ["manual-journals"];

export function listManualJournals(filters: { status?: string; waiting?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<MJSummary[]>(`/manual-journals/${query ? `?${query}` : ""}`);
}
export const manualJournalsExportUrl = (format: "xlsx" | "pdf") => `${API_BASE}/manual-journals/?export=${format}`;
export const getManualJournal = (id: number) => apiGet<MJDetail>(`/manual-journals/${id}/`);
export const createManualJournal = (input: MJInput) => apiSend<MJDetail>("POST", "/manual-journals/", input);
export const updateManualJournal = (id: number, input: MJInput) => apiSend<MJDetail>("PUT", `/manual-journals/${id}/`, input);
export const deleteManualJournal = (id: number) => apiSend<null>("DELETE", `/manual-journals/${id}/`);
const act = (id: number, what: string, body: object = {}) => apiSend<MJDetail>("POST", `/manual-journals/${id}/${what}/`, body);
export const submitManualJournal = (id: number, comment = "") => act(id, "submit", { comment });
export const approveManualJournal = (id: number, comment = "") => act(id, "approve", { comment });
export const returnManualJournal = (id: number, reason: string) => act(id, "return", { reason });
export const rejectManualJournal = (id: number, reason: string) => act(id, "reject", { reason });
export function addJournalFile(id: number, file: File) {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<MJDetail>(`/manual-journals/${id}/attachments/`, form, "POST");
}
export const removeJournalFile = (id: number, attachment: number) =>
  apiSend<MJDetail>("DELETE", `/manual-journals/${id}/attachments/${attachment}/`);
export const journalFileUrl = (id: number, attachment: number) => `${API_BASE}/manual-journals/${id}/attachments/${attachment}/`;
