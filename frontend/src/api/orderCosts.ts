/** Order costs (P3-16): what a job order or production order has cost so far, by element,
 * with each entry and its source. Part of the order's own page data. */

export type CostElement = "material" | "labour" | "overhead" | "setup" | "mould" | "subcontract" | "direct";

export interface OrderCosts {
  elements: { element: CostElement; label: string; amount: string }[];
  total: string;
  good: string;
  rejected: string;
  per_good: string;
  on_rejects: string;
  not_costed: string[];
  out_of_date: boolean;
  entries: {
    id: number;
    day: string;
    element: CostElement;
    description: string;
    quantity: string;
    unit: string;
    rate: string;
    amount: string;
    adjusts: boolean;
  }[];
  can_refresh: boolean;
}
