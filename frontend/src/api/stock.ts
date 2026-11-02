import { apiGet } from "./client";

export interface StockRow {
  item: { id: number; code: string; name: string; unit: string };
  store: { id: number; code: string; kind: "main" | "quarantine" | "rejected"; division: string };
  lot_no: string | null;
  /** Decimals as text. */
  quantity: string;
  value: string;
  average_cost: string | null;
}

export interface Movement {
  id: number;
  date: string;
  kind: "received" | "damaged" | "accepted" | "rejected" | "reversed";
  item: { id: number; code: string; unit: string };
  store: string;
  lot_no: string;
  quantity: string;
  value: string;
  grn: { id: number; number: string } | null;
  opening?: { id: number; number: string } | null;
  journal: string | null;
  by: string;
}

export const stockKey = ["stock"];

function query(filters: Record<string, string>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
  const text = params.toString();
  return text ? `?${text}` : "";
}

export const getStock = (filters: { division?: string; lots?: string }) =>
  apiGet<{ total_value: string; rows: StockRow[] }>(`/stock/${query(filters)}`);
export const listMovements = (filters: { item?: string; lot?: string; division?: string }) =>
  apiGet<Movement[]>(`/stock/movements/${query(filters)}`);
