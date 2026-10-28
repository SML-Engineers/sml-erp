import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

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

// --- Vouchers (P1-02) --------------------------------------------------------------------

export type VoucherStatus =
  | "draft"
  | "submitted"
  | "accountant_approved"
  | "director_approved"
  | "returned"
  | "rejected"
  | "partly_paid"
  | "paid"
  | "cancelled"
  | "deleted";

export interface VoucherSummary {
  id: number;
  number: string;
  status: VoucherStatus;
  voucher_type: { code: string; name: string };
  division: string;
  payee: { id: number; name: string } | null;
  voucher_date: string;
  total_amount: string;
  created_by: string;
  attachments: number;
}

export interface VoucherLineData {
  line_no: number;
  invoice_no: string;
  invoice_date: string | null;
  description: string;
  amount: string;
  tax_code: string | null;
  tax_amount: string;
  total: string;
  account: { id: number; number: string; name: string } | null;
  division: string | null;
  job_ref: string;
  splits: { division: string; amount: string; percent: string | null }[];
}

export interface VoucherAttachmentData {
  id: number;
  file_name: string;
  content_type: string;
  size: number;
  sha256: string;
  uploaded_at: string;
}

export interface VoucherDetail extends Omit<VoucherSummary, "voucher_type" | "payee" | "attachments"> {
  voucher_type: VoucherType;
  payee: { id: number; code: string; name: string; category: string } | null;
  transfer_to: { id: number; code: string; name: string } | null;
  description: string;
  created_by_id: number;
  created_at: string;
  submitted_at: string | null;
  revision: number;
  lines: VoucherLineData[];
  attachments: VoucherAttachmentData[];
  warnings: string[];
  can_edit: boolean;
  payee_balance: { waiting_approval: string; approved_unpaid: string; outstanding: string } | null;
  approvals: { level: number; action: string; user: string; reason: string; acted_at: string }[];
  upload_warnings?: string[];
  waiting_level: number | null;
  waiting_for: string | null;
  can_act: boolean;
  uncoded_lines: number[];
}

export interface VoucherLineInput {
  invoice_no: string;
  invoice_date: string | null;
  description: string;
  amount: string;
  tax_code: string | null;
  tax_amount: string;
}

export interface VoucherInput {
  voucher_type: string;
  division?: string;
  payee: number | null;
  transfer_to: number | null;
  description: string;
  lines: VoucherLineInput[];
}

export const vouchersKey = ["vouchers"];

export function listVouchers(filter: { status?: string; type?: string; q?: string }) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filter)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<VoucherSummary[]>(`/vouchers/${query ? `?${query}` : ""}`);
}
export const getVoucher = (id: number) => apiGet<VoucherDetail>(`/vouchers/${id}/`);
export const createVoucher = (input: VoucherInput) => apiSend<VoucherDetail>("POST", "/vouchers/", input);
export const updateVoucher = (id: number, input: VoucherInput) =>
  apiSend<VoucherDetail>("PATCH", `/vouchers/${id}/`, input);
export const submitVoucher = (id: number, comment = "") =>
  apiSend<VoucherDetail>("POST", `/vouchers/${id}/submit/`, { comment });
export function uploadVoucherFile(id: number, file: File) {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<VoucherDetail>(`/vouchers/${id}/attachments/`, form, "POST");
}
export const removeVoucherFile = (id: number, attachmentId: number) =>
  apiSend<VoucherDetail>("DELETE", `/vouchers/${id}/attachments/${attachmentId}/`);
export const voucherFileUrl = (id: number, attachmentId: number) =>
  `${API_BASE}/vouchers/${id}/attachments/${attachmentId}/`;
export const listTransferAccounts = () =>
  apiGet<{ id: number; code: string; name: string }[]>("/vouchers/transfer-accounts/");
export const getPayeeBalance = (payeeId: number) =>
  apiGet<{ waiting_approval: string; approved_unpaid: string; outstanding: string }>(
    `/vouchers/payee-balance/${payeeId}/`,
  );
