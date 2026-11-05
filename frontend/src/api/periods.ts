import { apiGet, apiSend } from "./client";

/** Pay periods (P2B-15): pay month November 2026 = 21 October to 20 November by default. */

export interface PayPeriod {
  month: string;
  start: string;
  end: string;
}

export interface PayPeriodRule {
  id: number;
  effective_from: string;
  start_day: number;
  reason: string;
  created_by: string | null;
  can_withdraw: boolean;
}

export interface PayPeriodRuleList {
  results: PayPeriodRule[];
  current: PayPeriod;
  last: PayPeriod;
  can_manage: boolean;
}

export const payPeriodsKey = ["pay-periods"] as const;

export const listPayPeriods = () => apiGet<PayPeriodRuleList>("/pay-periods/");
export const addPayPeriod = (values: Record<string, string>) => apiSend<PayPeriodRule>("POST", "/pay-periods/", values);
export const withdrawPayPeriod = (id: number, reason: string) =>
  apiSend<null>("DELETE", `/pay-periods/${id}/`, { reason });
