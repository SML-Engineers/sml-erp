import { apiGet, apiSend } from "./client";
import type { VoucherStatus } from "./vouchers";

export type PaymentMethod = "cheque" | "transfer" | "cash" | "card" | "qr";

/** A Director-approved voucher not yet fully paid (the Cashier's list). */
export interface ToPayRow {
  id: number;
  number: string;
  status: VoucherStatus;
  voucher_type: { code: string; name: string };
  division: string;
  payee: { id: number; name: string } | null;
  transfer_to: string | null;
  voucher_date: string;
  total_amount: string;
  paid: string;
  remaining: string;
  methods: PaymentMethod[];
  suggested_account: number | null;
}

export interface PayAccount {
  id: number;
  code: string;
  name: string;
  kind: "current" | "savings" | "cash" | "petty_cash";
  currency: string;
  has_ledger: boolean;
  next_cheque: string | null;
}

export interface Payment {
  id: number;
  number: string;
  voucher: { id: number; number: string };
  payee: string;
  account: { id: number; code: string; name: string };
  method: PaymentMethod;
  reference: string;
  cheque_date: string | null;
  payment_date: string;
  amount: string;
  journal_entry: string;
  notes: string;
  created_by: string;
  created_at: string;
}

export interface PaymentInput {
  voucher: number;
  account: number;
  method: PaymentMethod;
  amount: string;
  payment_date: string;
  reference: string;
  cheque_number: string | null;
  cheque_date: string | null;
  notes: string;
}

export const paymentsKey = ["payments"];

export const listToPay = () => apiGet<ToPayRow[]>("/payments/to-pay/");
export const listPayAccounts = () => apiGet<PayAccount[]>("/payments/accounts/");
export function listPayments(filter: { from?: string; to?: string } = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filter)) if (value) query.set(key, value);
  const text = query.toString();
  return apiGet<Payment[]>(`/payments/${text ? `?${text}` : ""}`);
}
export const recordPayment = (input: PaymentInput) => apiSend<Payment>("POST", "/payments/", input);

/** Which accounts each method pays from: cash from cash boxes, cheques from current
 * accounts, the rest from any bank account (spec 4.4). */
export function accountFits(account: PayAccount, method: PaymentMethod): boolean {
  if (!account.has_ledger || account.currency !== "LKR") return false;
  if (method === "cash") return account.kind === "cash" || account.kind === "petty_cash";
  if (method === "cheque") return account.kind === "current";
  return account.kind === "current" || account.kind === "savings";
}
