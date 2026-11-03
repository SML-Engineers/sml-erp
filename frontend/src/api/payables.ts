import { apiGet, apiSend, apiUpload } from "./client";

/** Payables aging and supplier statements (P2-10). Money as text. */
export const PAYABLE_BUCKETS = ["current", "d30", "d60", "d90", "over90"] as const;

export interface PayableRow {
  supplier_id: number;
  code: string;
  supplier: string;
  current: string;
  d30: string;
  d60: string;
  d90: string;
  over90: string;
  total: string;
}

export interface PayableItem {
  kind: "invoice" | "voucher";
  reference: string;
  document: string;
  link: string;
  division: string;
  date: string;
  due_date: string;
  days_overdue: number;
  total: string;
  open: string;
}

export interface StatementLine {
  line_no?: number;
  date: string;
  reference: string;
  description: string;
  debit: string;
  credit: string;
}

export interface OurRecord {
  date: string;
  reference: string;
  document: string;
  link: string;
  amount: string;
}

export interface SupplierStatementSummary {
  id: number;
  supplier: { id: number; code: string; name: string };
  currency: string;
  from_date: string | null;
  statement_date: string;
  closing_balance: string;
  status: "open" | "checked";
  created_by: string;
}

export interface SupplierStatementDetail extends SupplierStatementSummary {
  notes: string;
  lines: StatementLine[];
  checked_by: string | null;
  checked_at: string | null;
  check_note: string;
  can_edit: boolean;
  can_check: boolean;
  reconciliation: {
    from: string;
    to: string;
    matched: { line: StatementLine; ours: OurRecord; difference: string }[];
    theirs_only: StatementLine[];
    ours_only: (OurRecord & { side: "charge" | "credit" })[];
    their_balance: string;
    our_balance: string | null;
    difference: string | null;
  };
}

export interface StatementInput {
  supplier?: number;
  statement_date: string;
  from_date: string | null;
  closing_balance: string;
  notes: string;
  lines: StatementLine[];
}

export const payablesKey = ["payables"];

export function getPayables(asAt: string, supplier = "", division = "") {
  const params = new URLSearchParams();
  if (asAt) params.set("as_at", asAt);
  if (supplier) params.set("supplier", supplier);
  if (division) params.set("division", division);
  const query = params.toString();
  return apiGet<{ as_at: string; rows: PayableRow[]; items: PayableItem[] }>(`/payables/aging/${query ? `?${query}` : ""}`);
}
export const listSupplierStatements = () => apiGet<SupplierStatementSummary[]>("/supplier-statements/");
export const getSupplierStatement = (id: number) => apiGet<SupplierStatementDetail>(`/supplier-statements/${id}/`);
export const createSupplierStatement = (input: StatementInput) =>
  apiSend<SupplierStatementDetail>("POST", "/supplier-statements/", input);
export const checkSupplierStatement = (id: number, note: string) =>
  apiSend<SupplierStatementDetail>("POST", `/supplier-statements/${id}/check/`, { note });
export function importStatementFile(file: File) {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<{ lines: StatementLine[] }>("/supplier-statements/import/", form, "POST");
}
