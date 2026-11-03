import { apiGet, apiSend } from "./client";

/** Cheque register, deposits and returned cheques (P2-14). */

export type ReceivedStatus = "awaiting_approval" | "post_dated" | "in_hand" | "deposited" | "cleared" | "returned";
export type IssuedStatus = "issued" | "cleared" | "spoiled";

export interface ReceivedCheque {
  id: number;
  number: string;
  customer: { id: number; name: string };
  reference: string;
  cheque_bank: string;
  cheque_date: string | null;
  receipt_date: string;
  currency: string;
  amount: string;
  amount_lkr: string;
  status: ReceivedStatus;
  deposit: { id: number; number: string; date: string } | null;
  cleared_on: string | null;
  returned_on: string | null;
  return_reason: string;
}

export interface IssuedCheque {
  id: number;
  number: string;
  account: { id: number; code: string };
  status: IssuedStatus;
  reason: string;
  used_at: string;
  cleared_on: string | null;
  payment: {
    id: number;
    number: string;
    date: string;
    cheque_date: string | null;
    amount: string;
    payee: string;
    voucher: { id: number; number: string };
  } | null;
}

export interface DepositSlip {
  id: number;
  number: string;
  account: { id: number; code: string; name: string };
  deposit_date: string;
  slip_no: string;
  total: string;
  journal_entry: string;
  created_by: string;
  cheques: ReceivedCheque[];
}

export const chequesKey = ["cheques"];

export const listReceived = (status = "") =>
  apiGet<ReceivedCheque[]>(`/cheques/received/${status ? `?status=${status}` : ""}`);
export const listIssued = (status = "") =>
  apiGet<IssuedCheque[]>(`/cheques/issued/${status ? `?status=${status}` : ""}`);
export const clearIssued = (id: number, on: string) => apiSend<IssuedCheque>("POST", `/cheques/issued/${id}/clear/`, { on });
export const clearReceived = (id: number, on: string) =>
  apiSend<ReceivedCheque>("POST", `/cheques/received/${id}/clear/`, { on });
export const returnReceived = (id: number, on: string, reason: string) =>
  apiSend<ReceivedCheque>("POST", `/cheques/received/${id}/return/`, { on, reason });
export const listDeposits = () => apiGet<DepositSlip[]>("/deposits/");
export const makeDeposit = (input: { account: number; deposit_date: string; slip_no: string; receipts: number[] }) =>
  apiSend<DepositSlip>("POST", "/deposits/", input);
