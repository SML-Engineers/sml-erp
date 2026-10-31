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
}

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
  lines: LineInput[];
}

export const quotationsKey = ["quotations"];

export function listQuotations(filters: { q?: string; status?: string; division?: string } = {}) {
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
