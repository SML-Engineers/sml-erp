import { API_BASE, apiGet, apiSend } from "./client";
import type { PayPeriod } from "./periods";

/** The monthly payroll run (P2B-06). */

export type RunStatus = "draft" | "awaiting" | "approved" | "rejected";

export interface PayrollTotals {
  gross: string;
  epf_employee: string;
  epf_employer: string;
  etf: string;
  apit: string;
  deductions: string;
  net: string;
  employees: number;
}

export interface PayrollRunSummary {
  id: number;
  division: string;
  month: string;
  period: PayPeriod;
  status: RunStatus;
  status_label: string;
  created_by: string | null;
  worked_out_at: string;
  approved_at: string | null;
  /** Given on approval (P2B-07): the payroll's number and the journal entry that posted it. */
  number: string;
  journal: string;
  totals: PayrollTotals;
}

export interface PayrollItem {
  code: string;
  name: string;
  kind: "earning" | "deduction" | "employer";
  amount: string;
  basis: string;
}

export interface PayrollLine {
  employee: { id: number; number: string; name: string; category: string };
  days_employed: number;
  days_in_period: number;
  day_rate: string;
  hourly_rate: string;
  gross: string;
  epf_earnings: string;
  apit_earnings: string;
  epf_employee: string;
  epf_employer: string;
  etf: string;
  apit: string;
  deductions: string;
  net: string;
  items: PayrollItem[];
}

export interface PayrollRun extends PayrollRunSummary {
  statutory: { epf_employee: string; epf_employer: string; etf: string };
  returned: boolean;
  history: { action: string; user: string | null; reason: string; at: string }[];
  can_work_out: boolean;
  can_submit: boolean;
  can_approve: boolean;
  sees_people: boolean;
  can_email_payslips: boolean;
  lines: PayrollLine[];
  entries: { employee: number; component: string; amount: string; note: string }[];
  components: { code: string; name: string; kind: "earning" | "deduction" }[];
}

export interface PayrollList {
  results: PayrollRunSummary[];
  divisions: string[];
  last_month: string;
  can_prepare: boolean;
}

export interface TaxBand {
  up_to: string | null;
  rate: string;
  constant: string;
}

export interface TaxTables {
  tables: { id: number; kind: string; kind_label: string; effective_from: string; reason: string; bands: TaxBand[] }[];
  statutory: { effective_from: string; epf_employee: string; epf_employer: string; etf: string; reason: string }[];
}

export const payrollKey = ["payroll"] as const;
export const payrollRunKey = (id: number) => ["payroll", id] as const;
export const taxTablesKey = ["payroll-tax-tables"] as const;

export const listPayroll = () => apiGet<PayrollList>("/payroll/");
export const preparePayroll = (division: string, month: string) =>
  apiSend<PayrollRun>("POST", "/payroll/", { division, month });
export const getPayroll = (id: number) => apiGet<PayrollRun>(`/payroll/${id}/`);
export type PayrollAction = "work-out" | "submit" | "approve" | "return" | "reject";
export const actOnPayroll = (id: number, action: PayrollAction, reason = "") =>
  apiSend<PayrollRun>("POST", `/payroll/${id}/${action}/`, { reason });
export const setPayrollEntry = (id: number, entry: { employee: number; component: string; amount: string; note: string }) =>
  apiSend<PayrollRun>("POST", `/payroll/${id}/entries/`, entry);
export const listTaxTables = () => apiGet<TaxTables>("/payroll-tax-tables/");
export const addTaxTable = (values: { kind: string; effective_from: string; reason: string; bands: TaxBand[] }) =>
  apiSend<unknown>("POST", "/payroll-tax-tables/", values);

/** Payslips of an approved payroll (P2B-08): all in one PDF to print, or one employee's. */
export const payslipsUrl = (id: number, employee?: number) =>
  `${API_BASE}/payroll/${id}/payslips/${employee ? `?employee=${employee}` : ""}`;
export interface EmailedPayslips {
  sent: string[];
  failed: string[];
  no_email: string[];
}
export const emailPayslips = (id: number) => apiSend<EmailedPayslips>("POST", `/payroll/${id}/email-payslips/`, {});

/** Statutory returns (P2B-09): a table, and the same as Excel or PDF. */
export interface StatutoryReturn {
  title: string;
  lines: string[];
  columns: string[];
  rows: (string | number)[][];
  totals: (string | number)[];
  notes: string[];
  money_from: number;
}
export type ReturnKind = "epf" | "etf" | "apit" | "etf-half" | "apit-year";
export const returnUrl = (kind: ReturnKind | "apit-certificates", query: string, format?: "xlsx" | "pdf") =>
  `${API_BASE}/payroll-returns/${kind}/?${query}${format ? `&download=${format}` : ""}`;
export const getReturn = (kind: ReturnKind, query: string) =>
  apiGet<StatutoryReturn>(`/payroll-returns/${kind}/?${query}`);
