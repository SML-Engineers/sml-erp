import { API_BASE, apiGet, apiSend, apiUpload } from "./client";

export type GRNStatus = "draft" | "awaiting_approval" | "confirmed" | "reversal_requested" | "reversed";
export const GRN_STATUSES: GRNStatus[] = ["draft", "awaiting_approval", "confirmed", "reversal_requested", "reversed"];

export interface GRNSummary {
  id: number;
  number: string;
  receipt_date: string;
  status: GRNStatus;
  division: string;
  store: string;
  purchase_order: { id: number; label: string };
  supplier: { id: number; code: string; name: string };
  delivery_note_no: string;
  created_by: string;
}

export type PackageType = "none" | "bag" | "bar" | "plate" | "coil" | "counted";

export interface PackageFields {
  supplier_lot: string;
  gross_weight: string | null;
  tare_weight: string | null;
  declared_weight: string | null;
  pieces: string | null;
  piece_length: string | null;
  length_mm: string | null;
  width_mm: string | null;
  thickness_mm: string | null;
  damaged: boolean;
  notes: string;
}

export interface ReceiptPackage extends PackageFields {
  package_no: number;
  lot_no: string;
  net_weight: string | null;
  quantity: string | null;
  check: { basis: "" | "declared" | "kg_per_m" | "theoretical"; expected: string | null; actual: string | null; variance_pct: string | null; outside: boolean };
}

export interface GRNLine {
  line_no: number;
  po_line: number;
  item: { id: number; code: string; name: string; unit: string; package_type: PackageType; package_tare: string };
  description: string;
  unit: string;
  /** Quantities as text with 3 decimals, e.g. "300.000". */
  ordered_quantity: string;
  outstanding_quantity: string;
  received_quantity: string;
  damaged_quantity: string;
  good_quantity: string;
  excess_quantity: string;
  notes: string;
  weight_tolerance_pct: string;
  inspection: {
    id: number;
    status: "draft" | "deviation_requested" | "decided";
    decision: "" | "accepted" | "rejected" | "deviation";
    automatic: boolean;
    accepted_quantity: string;
    rejected_quantity: string;
  } | null;
  packages: ReceiptPackage[];
  package_totals: { count: number; net_weight: string; declared_weight: string; net_of_declared: string; outside: number };
}

export interface ApprovalStep {
  action: string;
  action_label: string;
  by: string;
  at: string;
  reason: string;
}

export interface GRNDetail extends GRNSummary {
  vehicle_no: string;
  supplier_invoice_no: string;
  notes: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
  reversal_reason: string;
  reversed_at: string | null;
  lines: GRNLine[];
  photos: { id: number; file_name: string; content_type: string; size: number; uploaded_by: string; uploaded_at: string }[];
  can_edit: boolean;
  can_add_photo: boolean;
  can_approve_excess: boolean;
  can_request_reversal: boolean;
  can_approve_reversal: boolean;
  excess_history: ApprovalStep[];
  reversal_history: ApprovalStep[];
}

export interface ReceivablePO {
  id: number;
  label: string;
  po_date: string;
  delivery_date: string | null;
  status: string;
  division: string;
  supplier: { id: number; code: string; name: string };
  outstanding_lines: number;
}

export interface GRNInput {
  receipt_date: string;
  delivery_note_no: string;
  vehicle_no: string;
  supplier_invoice_no: string;
  notes: string;
  lines: { po_line: number; received_quantity: string; damaged_quantity: string; notes: string }[];
}

export const grnKey = ["goods-receipts"];

export function listGoodsReceipts(filters: { status?: string; waiting?: string; purchase_order?: string } = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const query = params.toString();
  return apiGet<GRNSummary[]>(`/goods-receipts/${query ? `?${query}` : ""}`);
}
export const listReceivable = () => apiGet<ReceivablePO[]>("/goods-receipts/receivable/");
export const getGoodsReceipt = (id: number) => apiGet<GRNDetail>(`/goods-receipts/${id}/`);
export const createGoodsReceipt = (purchaseOrder: number) =>
  apiSend<GRNDetail>("POST", "/goods-receipts/", { purchase_order: purchaseOrder });
export const updateGoodsReceipt = (id: number, input: GRNInput) => apiSend<GRNDetail>("PUT", `/goods-receipts/${id}/`, input);
export const deleteGoodsReceipt = (id: number) => apiSend<void>("DELETE", `/goods-receipts/${id}/`);
const act = (id: number, what: string, body: object = {}) => apiSend<GRNDetail>("POST", `/goods-receipts/${id}/${what}/`, body);
export const confirmGoodsReceipt = (id: number, comment = "") => act(id, "confirm", { comment });
export const approveExcess = (id: number, comment = "") => act(id, "approve", { comment });
export const returnGoodsReceipt = (id: number, reason: string) => act(id, "return", { reason });
export const requestReversal = (id: number, reason: string) => act(id, "reverse", { reason });
export const approveReversal = (id: number, comment = "") => act(id, "reversal/approve", { comment });
export const refuseReversal = (id: number, reason: string) => act(id, "reversal/refuse", { reason });
export function addGoodsReceiptPhoto(id: number, file: File) {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<GRNDetail>(`/goods-receipts/${id}/photos/`, form, "POST");
}
export const removeGoodsReceiptPhoto = (id: number, photo: number) => apiSend<GRNDetail>("DELETE", `/goods-receipts/${id}/photos/${photo}/`);
export const goodsReceiptPhotoUrl = (id: number, photo: number) => `${API_BASE}/goods-receipts/${id}/photos/${photo}/`;
export const saveGoodsReceiptPackages = (id: number, lineNo: number, packages: PackageFields[]) =>
  apiSend<GRNDetail>("PUT", `/goods-receipts/${id}/lines/${lineNo}/packages/`, { packages });
export const goodsReceiptLabelsUrl = (id: number, lineNo?: number) => `${API_BASE}/goods-receipts/${id}/labels/${lineNo ? `?line=${lineNo}` : ""}`;
