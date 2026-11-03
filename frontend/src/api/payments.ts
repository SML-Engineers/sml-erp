import { API_BASE, apiGet, apiSend } from "./client";
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
  /** P2-12: the WHT to keep and what is left to pay the payee after it. */
  wht_total?: string;
  to_receive?: string;
  methods: PaymentMethod[];
  suggested_account: number | null;
  /** P2-11: a voucher of supplier invoices in one foreign currency may be paid in it. */
  foreign?: { currency: string; total: string; left: string } | null;
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
  /** P2-11: what left the account in its currency, the rate, and cancelling. */
  currency?: string;
  paid_amount?: string;
  exchange_rate?: string;
  /** P2-12: the withholding tax kept and its certificate number. */
  wht_amount?: string;
  wht_certificate?: string;
  cancelled?: boolean;
  can_cancel?: boolean;
  cancellation?: {
    id: number;
    status: "pending" | "approved" | "rejected";
    reason: string;
    requested_by: string;
    requested_at: string;
    decided_by: string | null;
    decided_at: string | null;
    reversal_entry: string | null;
    can_decide: boolean;
  } | null;
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

export const listToPay = (division = "") =>
  apiGet<ToPayRow[]>(`/payments/to-pay/${division ? `?division=${division}` : ""}`);
export const listPayAccounts = () => apiGet<PayAccount[]>("/payments/accounts/");
export function listPayments(filter: { from?: string; to?: string; division?: string } = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filter)) if (value) query.set(key, value);
  const text = query.toString();
  return apiGet<Payment[]>(`/payments/${text ? `?${text}` : ""}`);
}
/** P2-12: the withholding tax certificate of a payment, as a PDF. */
export const whtCertificateUrl = (id: number) => `${API_BASE}/payments/${id}/wht-certificate/`;
export const recordPayment = (input: PaymentInput) => apiSend<Payment>("POST", "/payments/", input);

/** Which accounts each method pays from: cash from cash boxes, cheques from current
 * accounts, the rest from any bank account (spec 4.4). */
export function accountFits(account: PayAccount, method: PaymentMethod, foreign: string | null = null): boolean {
  if (!account.has_ledger || (account.currency !== "LKR" && account.currency !== foreign)) return false;
  if (method === "cash") return account.kind === "cash" || account.kind === "petty_cash";
  if (method === "cheque") return account.kind === "current";
  return account.kind === "current" || account.kind === "savings";
}

export const cancelPayment = (id: number, reason: string) => apiSend<Payment>("POST", `/payments/${id}/cancel/`, { reason });
export const approvePaymentCancellation = (id: number, comment: string) =>
  apiSend<Payment>("POST", `/payment-cancellations/${id}/approve/`, { comment });
export const rejectPaymentCancellation = (id: number, reason: string) =>
  apiSend<Payment>("POST", `/payment-cancellations/${id}/reject/`, { reason });
