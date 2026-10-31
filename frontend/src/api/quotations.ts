import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

export type QuotationStatus = "draft" | "awaiting_approval" | "approved" | "sent" | "accepted" | "lost" | "expired" | "revised";

export interface QuotationSummary {
  id: number;
  number: string;
  revision: number;
  status: QuotationStatus;
  quote_date: string;
  valid_until: string;
  division: string;
  customer: { id: number; code: string; name: string };
  enquiry_ref: string;
  currency: string;
  /** Decimals as text, e.g. "48380.00". */
  total_amount: string;
  total_lkr: string;
  created_by: string;
}

export interface QtyBreak {
  quantity: string;
  unit_price: string;
}

export interface QuotationLine {
  id: number;
  line_no: number;
  description: string;
  drawing_no: string;
  drawing_rev: string;
  quantity: string;
  unit: string;
  min_order_qty: string | null;
  unit_price: string;
  /** The mould or other tooling, charged once. */
  is_tooling: boolean;
  tax_code: string | null;
  amount: string;
  discount: string;
  tax_amount: string;
  total: string;
  breaks: QtyBreak[];
}

export interface QuotationFile {
  id: number;
  line_no: number | null;
  file_name: string;
  content_type: string;
  size: number;
  uploaded_at: string;
}

export interface QuotationDetail extends QuotationSummary {
  contact: { id: number; name: string; email: string } | null;
  exchange_rate: string;
  rate_date: string | null;
  payment_terms: string;
  delivery_lead_time: string;
  incoterm: string;
  notes: string;
  /** A % off every line before taxes (P15-07b); the subtotal is after it. */
  discount_pct: string;
  discount_total: string;
  subtotal: string;
  tax_total: string;
  created_by_id: number;
  created_at: string;
  lines: QuotationLine[];
  files: QuotationFile[];
  can_edit: boolean;
  /** Whether this user may open the costing (creator, Sales Manager, Accountant, Director). */
  can_see_costing: boolean;
  upload_warnings?: string[];
  approved_at: string | null;
  sent_at: string | null;
  outcome: { reason: string; reason_label: string; note: string; at: string; by: string } | null;
  /** Approved by the Director: may be printed as final and emailed. */
  is_final: boolean;
  can_submit: boolean;
  can_approve: boolean;
  can_mark_sent: boolean;
  can_record_outcome: boolean;
  can_revise: boolean;
  /** Approved and the user is its creator or the Sales Manager (P15-07). */
  can_email: boolean;
  can_make_proforma: boolean;
  proformas: { id: number; number: string; status: "draft" | "issued" | "cancelled" }[];
  emails: { to: string; cc: string; subject: string; status: "sent" | "failed"; error: string; sent_at: string; by: string }[];
  approval: {
    status: "in_progress" | "approved" | "returned" | "rejected" | "withdrawn";
    /** The role the quotation waits for, e.g. "Director"; empty when nothing waits. */
    waiting_with: string;
    history: { action: string; action_label: string; level: number; by: string; at: string; reason: string }[];
  } | null;
  /** Every revision of this number the user may see, oldest first. */
  revisions: { id: number; revision: number; status: QuotationStatus; quote_date: string }[];
  /** For those who see costing: overall margin, value and the Director's warnings. */
  review?: {
    margin_pct: string | null;
    value_lkr: string;
    min_margin_pct: string | null;
    limit_lkr: string | null;
    warnings: string[];
  };
}

export const OUTCOME_REASONS = ["price", "lead_time", "quality", "relationship", "competitor", "cancelled", "no_response", "other"];

export interface LineInput {
  /** The saved line this is; left out for a new line. Kept lines keep their costing. */
  id?: number;
  description: string;
  drawing_no: string;
  drawing_rev: string;
  quantity: string;
  unit: string;
  min_order_qty: string | null;
  unit_price: string;
  is_tooling?: boolean;
  tax_code: string | null;
  breaks: QtyBreak[];
}

export interface QuotationInput {
  customer?: number;
  contact?: number | null;
  division?: string;
  currency?: string;
  valid_until?: string;
  enquiry_ref?: string;
  payment_terms?: string;
  delivery_lead_time?: string;
  incoterm?: string;
  notes?: string;
  discount_pct?: string;
  lines: LineInput[];
}

export const quotationsKey = ["quotations"];

export function listQuotations(filters: { q?: string; status?: string; division?: string; waiting?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<QuotationSummary[]>(`/quotations/${query ? `?${query}` : ""}`);
}
export const getQuotation = (id: number) => apiGet<QuotationDetail>(`/quotations/${id}/`);
export const createQuotation = (input: QuotationInput) => apiSend<QuotationDetail>("POST", "/quotations/", input);
export const updateQuotation = (id: number, input: QuotationInput) =>
  apiSend<QuotationDetail>("PUT", `/quotations/${id}/`, input);
export function uploadQuotationFile(id: number, file: File, lineNo: number | null) {
  const form = new FormData();
  form.append("file", file);
  if (lineNo !== null) form.append("line_no", String(lineNo));
  return apiUpload<QuotationDetail>(`/quotations/${id}/files/`, form, "POST");
}
export const removeQuotationFile = (id: number, fileId: number) =>
  apiSend<QuotationDetail>("DELETE", `/quotations/${id}/files/${fileId}/`);
export const quotationFileUrl = (id: number, fileId: number) => `${API_BASE}/quotations/${id}/files/${fileId}/`;

// --- Costing (P15-04): internal only, never on the customer's copy ---------------------

export interface CostingOperation {
  machine: { id: number; code: string; name: string };
  description: string;
  minutes: string;
  /** LKR per hour on the quotation's date. */
  rate: string;
}

export interface CostingExtra {
  description: string;
  amount: string;
  /** For the whole order (shared over the quantity) instead of per piece. */
  per_order: boolean;
}

export interface LineCosting {
  rates_date: string;
  material: { id: number; code: string; name: string } | null;
  material_rate: string | null;
  density: string | null;
  form: string;
  size_a_mm: string | null;
  size_b_mm: string | null;
  length_mm: string | null;
  cutting_allowance_mm: string;
  entered_weight_kg: string | null;
  weight_kg: string;
  setup_hours: string;
  setup_rate: string;
  overhead_pct: string;
  margin_pct: string;
  notes: string;
  operations: CostingOperation[];
  extras: CostingExtra[];
  method: CostingMethod;
  masterbatch: { id: number; code: string; name: string } | null;
  masterbatch_rate: string | null;
  masterbatch_pct: string;
  part_weight_g: string | null;
  runner_weight_g: string | null;
  cavities: number | null;
  machine: { id: number; code: string; name: string } | null;
  machine_rate: string | null;
  cycle_time_s: string | null;
  reject_pct: string;
  packing_amount: string;
  packing_per: PackingPer;
  pcs_per_carton: number | null;
  tooling: ToolingMode;
  tooling_cost: string;
  tooling_qty: string | null;
  updated_by: string;
  updated_at: string;
}

export type CostingMethod = "machining" | "moulding";
export type PackingPer = "piece" | "carton";
export type ToolingMode = "none" | "separate" | "amortised" | "customer";
export const TOOLING_MODES: ToolingMode[] = ["none", "separate", "amortised", "customer"];

/** One piece, at the line's quantity or at a quantity break. LKR unless said. */
export interface CostingResult {
  quantity: string;
  material: string;
  machining: string;
  /** Moulding: press hours per 1,000 pieces; null for machining. */
  hours_per_1000: string | null;
  rejects: string;
  setup: string;
  packing: string;
  subcontract: string;
  direct_cost: string;
  overhead: string;
  cost: string;
  margin: string;
  /** A mould spread over a quantity: added to the price without overhead or margin. */
  tooling: string;
  suggested_price_lkr: string;
  /** In the quotation's currency. */
  suggested_price: string;
  /** In the quotation's currency. */
  quoted_price: string;
  quoted_price_lkr: string;
  quoted_margin_pct: string | null;
  below_cost: boolean;
}

export interface CostingLine {
  line_no: number;
  description: string;
  drawing_no: string;
  quantity: string;
  unit: string;
  unit_price: string;
  is_tooling: boolean;
  costing: LineCosting | null;
  results: CostingResult[] | null;
}

export interface CostingPage {
  quotation_id: number;
  number: string;
  revision: number;
  division: string;
  currency: string;
  exchange_rate: string;
  quote_date: string;
  can_edit: boolean;
  default_method: CostingMethod;
  defaults: { overhead_pct: string; margin_pct: string; setup_rate: string } | null;
  materials: { id: number; code: string; name: string; kind: string; form: string; density: string | null; rate: string }[];
  machines: { id: number; code: string; name: string; rate: string }[];
  lines: CostingLine[];
}

export interface CostingInput {
  material: number | null;
  size_a_mm: string | null;
  size_b_mm: string | null;
  length_mm: string | null;
  cutting_allowance_mm: string | null;
  weight_kg: string | null;
  setup_hours: string | null;
  overhead_pct: string | null;
  margin_pct: string | null;
  notes: string;
  operations: { machine: number | null; minutes: string; description: string }[];
  extras: CostingExtra[];
  method: CostingMethod;
  masterbatch: number | null;
  masterbatch_pct: string | null;
  part_weight_g: string | null;
  runner_weight_g: string | null;
  cavities: string | null;
  machine: number | null;
  cycle_time_s: string | null;
  reject_pct: string | null;
  packing_amount: string | null;
  packing_per: PackingPer;
  pcs_per_carton: string | null;
  tooling: ToolingMode;
  tooling_cost: string | null;
  tooling_qty: string | null;
}

export const getCosting = (id: number) => apiGet<CostingPage>(`/quotations/${id}/costing/`);
export const saveLineCosting = (id: number, lineNo: number, input: CostingInput) =>
  apiSend<CostingPage>("PUT", `/quotations/${id}/costing/${lineNo}/`, input);
export const removeLineCosting = (id: number, lineNo: number) =>
  apiSend<CostingPage>("DELETE", `/quotations/${id}/costing/${lineNo}/`);

// --- Approval, sending, outcome and revisions (P15-06) ----------------------------------

export const submitQuotation = (id: number, comment: string) =>
  apiSend<QuotationDetail>("POST", `/quotations/${id}/submit/`, { comment });
export const approveQuotation = (id: number, comment: string) =>
  apiSend<QuotationDetail>("POST", `/quotations/${id}/approve/`, { comment });
export const returnQuotation = (id: number, reason: string) =>
  apiSend<QuotationDetail>("POST", `/quotations/${id}/return/`, { reason });
export const markQuotationSent = (id: number) => apiSend<QuotationDetail>("POST", `/quotations/${id}/sent/`, {});
export const recordOutcome = (id: number, outcome: "accepted" | "lost", reason: string, note: string) =>
  apiSend<QuotationDetail>("POST", `/quotations/${id}/outcome/`, { outcome, reason, note });
export const reviseQuotation = (id: number) => apiSend<QuotationDetail>("POST", `/quotations/${id}/revise/`, {});

// --- Printed quotation and email (P15-07) ------------------------------------------------

export interface EmailDraft {
  from: string;
  ready: boolean;
  to: string[];
  cc: string[];
  subject: string;
  body: string;
}

export const quotationPdfUrl = (id: number) => `${API_BASE}/quotations/${id}/pdf/`;
export const getQuotationEmail = (id: number) => apiGet<EmailDraft>(`/quotations/${id}/email/`);
export const sendQuotationEmail = (id: number, message: { to: string[]; cc: string[]; subject: string; body: string }) =>
  apiSend<QuotationDetail>("POST", `/quotations/${id}/email/`, message);
