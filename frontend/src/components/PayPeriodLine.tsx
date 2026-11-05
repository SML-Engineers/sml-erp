import { useTranslation } from "react-i18next";

import type { PayPeriod } from "../api/periods";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;
const month = (ym: string) => `${MONTHS[Number(ym.slice(5, 7)) - 1]} ${ym.slice(0, 4)}`;

/** "Pay month Nov 2026: 21 Oct – 20 Nov" (P2B-15). */
export default function PayPeriodLine({ period }: { period: PayPeriod }) {
  const { t } = useTranslation();
  return (
    <p className="muted">
      {t("pp.line", { month: month(period.month), start: day(period.start), end: day(period.end) })}
    </p>
  );
}
