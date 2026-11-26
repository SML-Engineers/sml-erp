import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { VoucherDetail } from "../api/vouchers";
import { formatDecimal } from "../lib/decimal";

/** The exception box of each advance line: the PO, its total and what other vouchers have
 * already advanced on it. On the voucher page and the Director's approval screen (testing
 * T46, 21 Nov 2026: the approval screen showed the advance only in small grey text). */
export default function AdvanceNotice({ voucher }: { voucher: VoucherDetail }) {
  const { t } = useTranslation();
  return (
    <>
      {voucher.lines
        .filter((l) => l.advance_order)
        .map((l) => {
          const order = l.advance_order!;
          const before = order.advanced_before ?? "0.00";
          return (
            <p key={`a${l.line_no}`} className="notice" role="note">
              {t("vouchers.advanceException", { po: order.label, amount: formatDecimal(l.total), total: formatDecimal(order.total_lkr) })}{" "}
              {Number(before) > 0 && `${t("vouchers.advancedBefore", { amount: formatDecimal(before) })} `}
              <Link to={`/purchase-orders/${order.id}`}>{order.label}</Link>
            </p>
          );
        })}
    </>
  );
}
