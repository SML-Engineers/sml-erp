import { API_BASE, apiGet, apiSend } from "./client";
import type { EmailDraft, EmailToSend } from "./documentEmail";

/** Receivables (P2-08): aging, statements, reminders and credit holds. Money as text. */
export const BUCKETS = ["current", "d30", "d60", "d90", "over90"] as const;
export type Bucket = (typeof BUCKETS)[number];

export interface AgingRow {
  customer_id: number;
  code: string;
  customer: string;
  current: string;
  d30: string;
  d60: string;
  d90: string;
  over90: string;
  total: string;
  /** The customer's receivables ledger balance, to show any difference. */
  ledger: string;
}

export interface StatementLine {
  date: string;
  reference: string;
  source_type: string;
  description: string;
  debit: string;
  credit: string;
  balance: string;
}

export interface ReminderPlan {
  is_on: boolean;
  every_days: number;
  set_by: string | null;
  recipient: string;
  last_sent_on: string | null;
  can_manage: boolean;
}

export interface Statement {
  customer: { id: number; code: string; name: string; credit_limit: string | null; payment_terms_days: number };
  from: string;
  to: string;
  opening: string;
  closing: string;
  lines: StatementLine[];
  items: {
    invoice: { id: number; number: string; invoice_date: string; due_date: string; total_amount: string };
    open: string;
    days_overdue: number;
    bucket: Bucket;
  }[];
  buckets: Record<Bucket, string>;
  overdue: string;
  advances_held: string;
  credit: { owed: string; overdue: string; over_limit: boolean; on_hold: boolean };
  reminders: ReminderPlan;
  can_email: boolean;
  emails: { to: string; subject: string; status: "sent" | "failed"; error: string; sent_at: string; by: string; reminder: boolean }[];
}

export interface CreditHold {
  id: number;
  document_type: "sales_order" | "tax_invoice";
  document_label: string;
  link: string;
  customer: { id: number; code: string; name: string };
  amount_lkr: string;
  exposure_lkr: string;
  credit_limit: string | null;
  overdue_lkr: string;
  reasons: string;
  status: "waiting" | "allowed";
  requested_by: string;
  requested_at: string;
  decided_by: string | null;
  decided_at: string | null;
  note: string;
  can_allow: boolean;
}

export const receivablesKey = ["receivables"];

export const getAging = (asAt: string) =>
  apiGet<{ as_at: string; rows: AgingRow[] }>(`/receivables/aging/${asAt ? `?as_at=${asAt}` : ""}`);

function period(from: string, to: string): string {
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const statementPath = (customer: number) => `/receivables/statements/${customer}/`;
export const getStatement = (customer: number, from: string, to: string) =>
  apiGet<Statement>(`${statementPath(customer)}${period(from, to)}`);
export const statementPdfUrl = (customer: number, from: string, to: string) => {
  const query = period(from, to);
  return `${API_BASE}${statementPath(customer)}${query ? `${query}&` : "?"}export=pdf`;
};
export const getStatementEmail = (customer: number, from: string, to: string) =>
  apiGet<EmailDraft>(`${statementPath(customer)}email/${period(from, to)}`);
export const sendStatementEmail = (customer: number, from: string, to: string, email: EmailToSend) =>
  apiSend<Statement>("POST", `${statementPath(customer)}email/${period(from, to)}`, email);
export const setReminders = (customer: number, isOn: boolean, everyDays: number) =>
  apiSend<ReminderPlan>("PUT", `${statementPath(customer)}reminders/`, { is_on: isOn, every_days: everyDays });

export const listCreditHolds = (status: string) =>
  apiGet<CreditHold[]>(`/credit-holds/${status ? `?status=${status}` : ""}`);
export const allowCreditHold = (id: number, note: string) => apiSend<CreditHold>("POST", `/credit-holds/${id}/allow/`, { note });
