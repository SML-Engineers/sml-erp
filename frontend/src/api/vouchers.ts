import { apiGet, apiSend } from "./client";

export type PaymentMethod = "cheque" | "transfer" | "cheque_or_transfer" | "cash" | "internal" | "any";
export const PAYMENT_METHODS: PaymentMethod[] = ["cheque", "transfer", "cheque_or_transfer", "cash", "internal", "any"];
export const PAYEE_CATEGORIES = ["", "supplier", "utility", "bank_card", "government", "employee", "other"];

export interface VoucherType {
  id: number;
  code: string;
  name: string;
  payment_method: PaymentMethod;
  needs_payee: boolean;
  payee_category: string;
  is_advance: boolean;
  notes: string;
  sort_order: number;
  is_active: boolean;
  in_use: boolean;
}

export type VoucherTypeChange = Partial<Omit<VoucherType, "id" | "in_use">> & { reason?: string };

export const voucherTypesKey = ["voucher-types"];

export const listVoucherTypes = (includeInactive: boolean) =>
  apiGet<VoucherType[]>(`/voucher-types/${includeInactive ? "?include_inactive=1" : ""}`);
export const createVoucherType = (change: VoucherTypeChange) =>
  apiSend<VoucherType>("POST", "/voucher-types/", change);
export const updateVoucherType = (id: number, change: VoucherTypeChange) =>
  apiSend<VoucherType>("PATCH", `/voucher-types/${id}/`, change);
export const deleteVoucherType = (id: number, reason: string) =>
  apiSend<null>("DELETE", `/voucher-types/${id}/`, { reason });
