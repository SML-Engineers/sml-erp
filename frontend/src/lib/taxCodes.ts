import type { TaxCode } from "../api/taxes";

/**
 * The tax codes a form offers (testing T1, 21 Nov 2026): active, for sales or purchases,
 * and with a rate in force today for every tax in them, so a save is never stopped by a
 * missing rate. A code already on one of the form's lines stays offered, so the line still
 * shows it.
 */
export function offeredTaxCodes(
  codes: TaxCode[] | undefined,
  side: "sales" | "purchases",
  keep: (string | null | undefined)[] = [],
): TaxCode[] {
  const other = side === "sales" ? "purchases" : "sales";
  return (codes ?? []).filter((c) => (c.is_active && c.use !== other && c.has_rate_today !== false) || keep.includes(c.code));
}
