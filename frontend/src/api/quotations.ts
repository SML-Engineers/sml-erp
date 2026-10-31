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
  line_no: number;
  description: string;
  drawing_no: string;
  drawing_rev: string;
  quantity: string;
  unit: string;
  min_order_qty: string | null;
  unit_price: string;
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
  upload_warnings?: string[];
}

export interface LineInput {
  description: string;
  drawing_no: string;
  drawing_rev: string;
  quantity: string;
  unit: string;
  min_order_qty: string | null;
  unit_price: string;
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
