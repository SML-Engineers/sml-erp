/** Plain words for a program name that has no wording of its own yet, so no raw program
 * words reach the screen (testing T33, 21-22 Nov 2026): "approved_at" → "Approved at",
 * "is_active" → "Active", "discount_pct" → "Discount %", "po_line_id" → "PO line". */
const TOKENS: Record<string, string> = {
  apit: "APIT",
  bom: "BOM",
  cm: "(cm)",
  epf: "EPF",
  etf: "ETF",
  g: "(g)",
  grn: "GRN",
  kg: "(kg)",
  lkr: "(LKR)",
  mm: "(mm)",
  nic: "NIC",
  no: "number",
  ot: "overtime",
  pct: "%",
  pm: "maintenance",
  po: "PO",
  qty: "quantity",
  s: "(seconds)",
  t: "(tonnes)",
  tin: "TIN",
  vat: "VAT",
  wht: "WHT",
};

export function plainWords(code: string): string {
  const parts = code
    .trim()
    .replace(/_id$/, "")
    .replace(/^is_/, "")
    .split("_")
    .filter(Boolean)
    .map((part) => TOKENS[part] ?? part);
  const words = parts.join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
