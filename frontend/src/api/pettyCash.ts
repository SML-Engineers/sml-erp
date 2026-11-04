import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

/** Petty cash (P2-17). */

export interface PettyFloat {
  id: number;
  code: string;
  name: string;
  custodian: string | null;
  division: string | null;
  can_record: boolean;
  float: string;
  spent: string;
  not_on_voucher: string;
  cash_in_hand: string;
}

export type PettyStatus = "open" | "on_voucher" | "paid_back";

export interface PettyExpense {
  id: number;
  number: string;
  expense_date: string;
  paid_to: string;
  description: string;
  amount: string;
  ledger: { id: number; number: string; name: string } | null;
  division: string | null;
  slip_name: string;
  status: PettyStatus;
  voucher: { id: number; number: string } | null;
  created_by: string;
}

export const pettyKey = ["petty-cash"];

export const listFloats = () => apiGet<PettyFloat[]>("/petty-cash/");
export const listPettyExpenses = (id: number) =>
  apiGet<{ float: PettyFloat; expenses: PettyExpense[] }>(`/petty-cash/${id}/expenses/`);
export function recordPettyExpense(
  id: number,
  input: { expense_date: string; paid_to: string; description: string; amount: string; ledger: string; slip: File },
) {
  const form = new FormData();
  form.append("expense_date", input.expense_date);
  form.append("paid_to", input.paid_to);
  form.append("description", input.description);
  form.append("amount", input.amount);
  if (input.ledger) form.append("ledger", input.ledger);
  form.append("slip", input.slip);
  return apiUpload<PettyExpense>(`/petty-cash/${id}/expenses/`, form, "POST");
}
export const removePettyExpense = (id: number) => apiSend<null>("DELETE", `/petty-expenses/${id}/`);
export const pettySlipUrl = (id: number) => `${API_BASE}/petty-expenses/${id}/slip/`;
export const replenishFloat = (id: number, payee: number) =>
  apiSend<{ voucher: { id: number; number: string } }>("POST", `/petty-cash/${id}/replenish/`, { payee });
