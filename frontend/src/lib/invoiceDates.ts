// Voucher invoice dates (owner, 20 Nov 2026): more than 2 months old needs the Clerk's
// "Yes, the date is right"; more than a year old cannot be entered. The server checks the
// same rule (apps/vouchers/services.invoice_date_age); this only shows it while typing.

/** The same day of the month `months` earlier, or that month's last day: "YYYY-MM-DD". */
export function monthsBack(date: string, months: number): string {
  const [y, m, d] = date.split("-").map(Number);
  const total = y * 12 + (m - 1) - months;
  const year = Math.floor(total / 12);
  const month = (total % 12) + 1;
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(Math.min(d, last)).padStart(2, "0")}`;
}

export type InvoiceDateAge = "ok" | "old" | "too_old";

/** How old a "YYYY-MM-DD" invoice date is on `today`. */
export function invoiceDateAge(date: string | null | undefined, today: string): InvoiceDateAge {
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return "ok";
  if (date < monthsBack(today, 12)) return "too_old";
  if (date < monthsBack(today, 2)) return "old";
  return "ok";
}

/** "2026-08-13" -> "13/08/2026". */
export function dayMonthYear(date: string): string {
  const [y, m, d] = date.split("-");
  return `${d}/${m}/${y}`;
}
