import { API_BASE, apiGet, apiSend } from "./client";
import type { EmailDraft, QuotationDetail } from "./quotations";

export type ProformaStatus = "draft" | "issued" | "cancelled";

export interface ProformaSummary {
  id: number;
  number: string;
  issue_date: string;
  status: ProformaStatus;
  division: string;
  customer: { id: number; code: string; name: string };
  quotation: { id: number; label: string };
  currency: string;
  /** Decimals as text, e.g. "645268.25". */
  total_amount: string;
  total_lkr: string;
  created_by: string;
}

export const PACKING_FIELDS = [
  "cartons",
  "qty_per_carton",
  "net_weight_kg",
  "gross_weight_kg",
  "carton_length_cm",
  "carton_width_cm",
  "carton_height_cm",
] as const;
export type PackingField = (typeof PACKING_FIELDS)[number];

export interface ProformaLine extends Record<PackingField, string | null> {
  line_no: number;
  quotation_line: number;
  description: string;
  drawing_no: string;
  quantity: string;
  unit: string;
  unit_price: string;
  is_tooling: boolean;
  amount: string;
  discount: string;
  tax_amount: string;
  total: string;
  volume_m3: string | null;
}

export interface ProformaDetail extends ProformaSummary {
  contact: { id: number; name: string } | null;
  exchange_rate: string;
  rate_date: string | null;
  customer_po: string;
  payment_terms: string;
  delivery_lead_time: string;
  incoterm: string;
  port_of_loading: string;
  port_of_destination: string;
  bank_account: { id: number; code: string; name: string } | null;
  advance_pct: string;
  advance_amount: string;
  notes: string;
  discount_pct: string;
  discount_total: string;
  subtotal: string;
  tax_total: string;
  cancel_reason: string;
  lines: ProformaLine[];
  packing_totals: { cartons: string | null; net_weight_kg: string | null; gross_weight_kg: string | null; volume_m3: string | null };
  quotation_lines: {
    id: number;
    line_no: number;
    description: string;
    quantity: string;
    unit_price: string;
    breaks: { quantity: string; unit_price: string }[];
  }[];
  can_edit: boolean;
  bank_choices: { id: number; code: string; name: string; bank_name: string; currency: string }[];
  can_cancel: boolean;
  can_email: boolean;
  emails: { to: string; subject: string; status: "sent" | "failed"; error: string; sent_at: string; by: string }[];
  advances: { id: number; number: string; status: string; amount: string }[];
}

export type ProformaLineInput = { quotation_line: number; quantity: string } & Partial<Record<PackingField, string>>;

export interface ProformaInput {
  customer_po: string;
  payment_terms: string;
  delivery_lead_time: string;
  incoterm: string;
  port_of_loading: string;
  port_of_destination: string;
  bank_account: number | null;
  advance_pct: string;
  discount_pct: string;
  notes: string;
  lines: ProformaLineInput[];
}

export const proformasKey = ["proformas"];

export function listProformas(filters: { status?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<ProformaSummary[]>(`/proformas/${query ? `?${query}` : ""}`);
}
export const getProforma = (id: number) => apiGet<ProformaDetail>(`/proformas/${id}/`);
export const createProforma = (quotation: QuotationDetail["id"]) => apiSend<ProformaDetail>("POST", "/proformas/", { quotation });
export const updateProforma = (id: number, input: ProformaInput) => apiSend<ProformaDetail>("PUT", `/proformas/${id}/`, input);
export const issueProforma = (id: number) => apiSend<ProformaDetail>("POST", `/proformas/${id}/issue/`, {});
export const cancelProforma = (id: number, reason: string) => apiSend<ProformaDetail>("POST", `/proformas/${id}/cancel/`, { reason });
export const proformaPdfUrl = (id: number) => `${API_BASE}/proformas/${id}/pdf/`;
export const getProformaEmail = (id: number) => apiGet<EmailDraft>(`/proformas/${id}/email/`);
export const sendProformaEmail = (id: number, message: { to: string[]; cc: string[]; subject: string; body: string }) =>
  apiSend<ProformaDetail>("POST", `/proformas/${id}/email/`, message);
