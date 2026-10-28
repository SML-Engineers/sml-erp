/**
 * Exact decimal arithmetic for money and quantities shown in the browser.
 *
 * The API sends money as strings (CLAUDE.md rule 1). Adding them with JavaScript numbers
 * would introduce floating-point errors (0.1 + 0.2 = 0.30000000000000004), so totals are
 * added as whole numbers of the smallest unit with BigInt.
 */

function toUnits(value: string, scale: number): bigint {
  const text = value.trim();
  if (!/^-?\d+(\.\d+)?$/.test(text)) throw new Error(`Not a decimal number: "${value}"`);
  const negative = text.startsWith("-");
  const [whole, fraction = ""] = text.replace("-", "").split(".");
  if (fraction.length > scale && /[1-9]/.test(fraction.slice(scale))) {
    throw new Error(`"${value}" has more than ${scale} decimal places`);
  }
  const units = BigInt(whole + fraction.slice(0, scale).padEnd(scale, "0"));
  return negative ? -units : units;
}

function fromUnits(units: bigint, scale: number): string {
  const negative = units < 0n;
  const digits = (negative ? -units : units).toString().padStart(scale + 1, "0");
  const whole = digits.slice(0, digits.length - scale);
  const fraction = scale ? `.${digits.slice(-scale)}` : "";
  return `${negative ? "-" : ""}${whole}${fraction}`;
}

/** Sum decimal strings exactly, e.g. sumDecimal(["0.10", "0.20"]) === "0.30". */
export function sumDecimal(values: (string | null | undefined)[], scale = 2): string {
  let total = 0n;
  for (const value of values) {
    if (value === null || value === undefined || value === "") continue;
    total += toUnits(String(value), scale);
  }
  return fromUnits(total, scale);
}

/** Show a decimal string with thousands separators, e.g. "230150.00" -> "230,150.00". */
export function formatDecimal(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  const [whole, fraction] = String(value).split(".");
  const sign = whole.startsWith("-") ? "-" : "";
  const grouped = whole.replace("-", "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${sign}${grouped}${fraction !== undefined ? `.${fraction}` : ""}`;
}
