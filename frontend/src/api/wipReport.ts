import { apiGet } from "./client";

/** The month-end Work in progress report (P3-16). Amounts are decimals as text. */

export interface WipJob {
  id: number;
  number: string;
  description: string;
  status: string;
  wip: string;
}

export interface WipDivision {
  division: string;
  jobs: WipJob[];
  /** Total of the open jobs. */
  orders: string;
  /** Balance of the Work in progress account for the division. */
  ledger: string;
  difference: string;
}

export interface WipReport {
  month: string;
  month_end: string;
  divisions: WipDivision[];
  reconciled: boolean;
  unabsorbed: { division: string; machine: string; reason: string; hours: string; amount: string }[];
  absorbed: { division: string; element: string; amount: string }[];
}

export const wipReportKey = ["wip-report"];
export const getWipReport = (month: string) => apiGet<WipReport>(`/wip-report/?month=${month}`);
