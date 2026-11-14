import { API_BASE, apiGet, apiSend, apiUpload } from "./client";
import type { Payment } from "./payments";

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
  | "deleted"
  | "amended";

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
  /** Row actions this user may take (spec 4.4); the server checks each one again. */
  actions?: VoucherAction[];
  deleted?: { at: string; by: string; reason: string };
}

/** "edit": the Clerk's form; "edit_coding": the Accountant's review (L2); "revise": the
 * Director's changes (L3), which send the voucher back to the Accountant. */
export type VoucherAction =
  | "resources"
  | "print"
  | "edit"
  | "edit_coding"
  | "revise"
  | "amend"
  | "cancel"
  | "pay"
  | "delete";

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
  /** P2-12: withholding tax kept from the payment for this line. */
  wht_component?: string | null;
  wht_rate?: string;
  wht_amount?: string;
  /** The matched supplier invoice this line pays (P16-11), with PO, GRN and invoice. */
  supplier_invoice?: PaidInvoice | null;
  /** An advance on this purchase order before the goods arrive (P16-11a). */
  advance_order?: { id: number; label: string; total_lkr: string; status: string } | null;
}

export interface PaidInvoice {
  id: number;
  number: string;
  invoice_no: string;
  invoice_date: string;
  due_date: string;
  total_lkr: string;
  on_vouchers: string;
  lines: {
    item: { code: string; name: string; unit: string };
    po: { id: number; label: string; quantity: string; unit_price: string };
    grn: { id: number; number: string; received: string; accepted: string };
    invoice: { quantity: string; unit_price: string; total: string };
    matches: boolean;
  }[];
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
  amendment_reason: string;
  /** The voucher this one amends, and the amendments of this one (P1-05). */
  parent: { id: number; number: string } | null;
  revisions: { id: number; number: string; status: VoucherStatus }[];
  /** The latest cancellation request, if any (P1-06). */
  cancellation?: Cancellation | null;
  /** Payments made against the voucher (P1-07). */
  paid?: string;
  remaining?: string;
  /** P2-12: what is left to pay the payee after the withholding tax still to keep. */
  to_receive?: string;
  payments?: Payment[];
  /** P2-12: the WHT kept, what the payee receives and the withholding taxes to choose from
   * (empty until a rate is confirmed: built switched off). */
  wht_total?: string;
  payable?: string;
  wht_choices?: { code: string; name: string; rate: string }[];
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
  /** The Director can send it back to the Accountant (it waits after the first level). */
  can_send_to_accountant?: boolean;
  uncoded_lines: number[];
}

export interface VoucherLineInput {
  invoice_no: string;
  invoice_date: string | null;
  description: string;
  amount: string;
  tax_code: string | null;
  tax_amount: string;
  /** Pays this matched supplier invoice (P16-11). */
  supplier_invoice?: number | null;
  /** An advance on this purchase order (P16-11a). */
  advance_order?: number | null;
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

export function listVouchers(filter: { status?: string; type?: string; q?: string; division?: string; from?: string; to?: string }) {
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

// --- Row actions (P1-04b) ---------------------------------------------------------------

export type Paper = "A4" | "A5";
export const voucherPrintUrl = (id: number, paper: Paper) => `${API_BASE}/vouchers/${id}/print/?paper=${paper}`;
export const deleteVoucher = (id: number, reason: string) =>
  apiSend<VoucherDetail>("POST", `/vouchers/${id}/delete/`, { reason });
export const reviseVoucher = (id: number, input: VoucherInput) =>
  apiSend<VoucherDetail>("PATCH", `/vouchers/${id}/revise/`, input);
export const listDeletedVouchers = () => apiGet<VoucherSummary[]>("/vouchers/deleted/");

// --- Amendments (P1-05) -----------------------------------------------------------------

export interface AmendmentRow extends VoucherSummary {
  revision: number;
  amendment_reason: string;
  parent: { id: number; number: string; total_amount: string };
}

export const amendVoucher = (id: number, reason: string) =>
  apiSend<VoucherDetail>("POST", `/vouchers/${id}/amend/`, { reason });
export const listAmendments = () => apiGet<AmendmentRow[]>("/vouchers/amendments/");

// --- Cancellation (P1-06) ---------------------------------------------------------------

export interface Cancellation {
  id: number;
  status: "pending" | "approved" | "rejected";
  reason: string;
  requested_by: string;
  requested_at: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_reason: string;
  can_decide: boolean;
}

export interface CancellationRow extends Cancellation {
  voucher: { id: number; number: string; status: VoucherStatus; payee: string; total_amount: string };
}

export const requestCancellation = (id: number, reason: string) =>
  apiSend<VoucherDetail>("POST", `/vouchers/${id}/cancel/`, { reason });
export const decideCancellation = (id: number, decision: "approve" | "reject", reason: string) =>
  apiSend<VoucherDetail>("POST", `/vouchers/cancellations/${id}/${decision}/`, { reason });
export const listCancellations = (pendingOnly: boolean) =>
  apiGet<CancellationRow[]>(`/vouchers/cancellations/${pendingOnly ? "?pending=1" : ""}`);

// --- Lists and reports (P1-08) -----------------------------------------------------------

/** A list or report as an Excel or PDF download (the server builds it from the same rows). */
export function exportUrl(path: string, params: Record<string, string>, format: "xlsx" | "pdf") {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, value);
  query.set("export", format);
  return `${API_BASE}${path}?${query.toString()}`;
}

export interface ApprovedRow {
  id: number;
  number: string;
  voucher_date: string;
  type: string;
  division: string;
  payee: string;
  approved_at: string | null;
  approved_by: string;
  status: string;
  status_code: VoucherStatus;
  total_amount: string;
  paid: string;
}

export interface PendingRow {
  id: number;
  number: string;
  type: string;
  division: string;
  payee: string;
  level: number;
  waiting_for: string;
  approvers: string;
  since: string;
  days: number;
  band: string;
  total_amount: string;
}

export interface PendingReport {
  rows: PendingRow[];
  summary: { waiting_for: string; count: number; bands: Record<string, number> }[];
}

export interface HistoryRow {
  acted_at: string;
  round: number;
  level: number;
  action: string;
  user: string;
  reason: string;
}

const query = (params: Record<string, string | undefined>) => {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) q.set(key, value);
  const text = q.toString();
  return text ? `?${text}` : "";
};

export const approvedReport = (params: { from: string; to: string; division: string }) =>
  apiGet<ApprovedRow[]>(`/vouchers/reports/approved/${query(params)}`);
export const pendingReport = (params: { division?: string; level?: string } = {}) =>
  apiGet<PendingReport>(`/vouchers/reports/pending/${query(params)}`);

// --- Dashboard (P1-08b) -----------------------------------------------------------------

export interface Figure {
  count: number;
  total: string;
}

export interface VoucherDashboard {
  division: string;
  can_approve: boolean;
  can_enter: boolean;
  sees_approvals: boolean;
  waiting_for_me: Figure;
  my_vouchers: { draft?: Figure; returned?: Figure };
  by_level: { level: number; waiting_for: string; count: number; total: string; bands: Record<string, number> }[];
  pending_count: number;
  unpaid: Figure & { remaining: string };
  paid_this_month: (Figure & { from: string; to: string }) | null;
  by_division: {
    code: string;
    name: string;
    pending: number;
    pending_total: string;
    unpaid: Figure & { remaining: string };
    paid_this_month: string | null;
  }[];
  oldest: PendingRow[];
}

export const voucherDashboard = (division: string) =>
  apiGet<VoucherDashboard>(`/vouchers/dashboard/${query({ division })}`);
export const voucherHistory = (id: number) => apiGet<HistoryRow[]>(`/vouchers/${id}/history/`);
