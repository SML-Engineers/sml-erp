import { apiGet } from "./client";

/** What waits for this person's approval, by kind of document (owner, 12 Nov 2026). */
export interface WaitingKind {
  document_type: string;
  label: string;
  count: number;
}

export const waitingKey = ["approvals-waiting"] as const;

export function getWaiting() {
  return apiGet<WaitingKind[]>("/approvals/waiting/");
}

/** The page where each kind of document is approved. */
export const WAITING_PAGES: Record<string, string> = {
  voucher: "/vouchers/review",
  voucher_cancellation: "/vouchers/cancellations",
  quotation: "/quotations",
  customer_advance: "/advances",
  sales_order: "/sales-orders",
  purchase_order: "/purchase-orders",
  purchase_request: "/purchase-requests",
  goods_receipt: "/goods-receipts",
  goods_receipt_reversal: "/goods-receipts",
  quality_deviation: "/inspections",
  invoice_exception: "/supplier-invoices",
  supplier_return: "/supplier-returns",
  manual_journal: "/journals/manual",
  opening_stock: "/opening-stock",
  stock_adjustment: "/stores-work",
  credit_note: "/credit-notes",
  payment_cancellation: "/payments",
  budget: "/budgets",
  opening_balances: "/migration",
  customer_receipt: "/receipts",
  pay_change: "/employees",
  payroll: "/payroll",
  staff_credit: "/advances-loans",
  gratuity_setting: "/gratuity",
  routing: "/routings",
  bom: "/boms",
  job_excess: "/job-orders",
  job_deviation: "/job-orders",
  shift_report: "/shift-report",
  shift_correction: "/shift-report",
  asset_terms: "/fixed-assets",
  asset_class_rate: "/fixed-assets",
  payroll_opening: "/payroll-takeover",
};
