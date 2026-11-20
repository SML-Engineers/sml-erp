import { useTranslation } from "react-i18next";

import { dayMonthYear } from "../lib/invoiceDates";

/** For the Accountant and the Director: lines whose invoice date was more than 2 months old
 * when the Clerk entered it, and the Clerk confirmed (owner, 20 Nov 2026). */
export default function OldInvoiceDates({
  lines,
}: {
  lines: { line_no: number; invoice_date: string | null; old_date_confirmed?: boolean }[];
}) {
  const { t } = useTranslation();
  const old = lines.filter((l) => l.old_date_confirmed && l.invoice_date);
  if (old.length === 0) return null;
  return (
    <div className="notice notice-warn" role="note" aria-label={t("vouchers.oldDatesNote")}>
      <strong>{t("vouchers.oldDatesNote")}</strong>
      <ul>
        {old.map((l) => (
          <li key={l.line_no}>{t("vouchers.oldDateNoteLine", { n: String(l.line_no), date: dayMonthYear(l.invoice_date!) })}</li>
        ))}
      </ul>
    </div>
  );
}
