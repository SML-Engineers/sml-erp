import { API_BASE, apiGet } from "./client";

/** Tax reports (P2-20). */

export type Category = "standard" | "zero" | "exempt" | "outside";

export interface VatReport {
  year: number;
  month: number;
  supplies: Record<Category, string>;
  output_vat: string;
  ledger_output_vat: string;
  input_vat: string;
  payable: string;
  sales: ({ date: string; document: string; kind: string; link: string; customer: string; tin: string; vat: string } & Record<Category, string>)[];
  purchases: { date: string; entry: string; source_type: string; document: string; supplier: string; tin: string; narration: string; vat: string }[];
}

export interface SsclReport {
  year: number;
  month: number;
  total: string;
  rows: { date: string; document: string; kind: string; customer: string; component: string; rate: string; base: string; sscl: string }[];
}

export interface WhtReport {
  year: number;
  month: number;
  total: string;
  rows: { date: string; certificate: string; payment: string; voucher: string; supplier: string; tin: string; rate: string; gross: string; wht: string; paid: string }[];
}

export const taxReportsKey = ["tax-reports"];

const query = (year: number, month: number) => `?year=${year}&month=${month}`;
export const getVat = (year: number, month: number) => apiGet<VatReport>(`/tax-reports/vat/${query(year, month)}`);
export const getSscl = (year: number, month: number) => apiGet<SsclReport>(`/tax-reports/sscl/${query(year, month)}`);
export const getWht = (year: number, month: number) => apiGet<WhtReport>(`/tax-reports/wht/${query(year, month)}`);
export const taxExportUrl = (report: "vat" | "vat/purchases" | "sscl" | "wht", year: number, month: number, fmt: "xlsx" | "pdf") =>
  `${API_BASE}/tax-reports/${report}/${query(year, month)}&export=${fmt}`;
