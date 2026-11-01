import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { PaidInvoice } from "../api/vouchers";
import { formatDecimal, formatQuantity } from "../lib/decimal";

/** PO, GRN and invoice side by side for the approvers (spec 5A.5). */
export default function MatchedInvoice({ invoice }: { invoice: PaidInvoice }) {
  const { t } = useTranslation();
  const label = t("vouchers.matchOf", { no: invoice.invoice_no });
  return (
    <div className="table-wrap">
      <p>
        <strong>{label}</strong> ·{" "}
        {t("vouchers.matchTotals", { total: formatDecimal(invoice.total_lkr), onVouchers: formatDecimal(invoice.on_vouchers), due: invoice.due_date })}{" "}
        <Link to={`/supplier-invoices/${invoice.id}`}>{invoice.number}</Link>
      </p>
      <table aria-label={label}>
        <thead>
          <tr>
            <th>{t("po.item")}</th>
            <th>{t("vouchers.matchPo")}</th>
            <th>{t("vouchers.matchGrn")}</th>
            <th>{t("vouchers.matchInvoice")}</th>
          </tr>
        </thead>
        <tbody>
          {invoice.lines.map((m, i) => (
            <tr key={i}>
              <td>
                <span className="mono">{m.item.code}</span> {m.item.name}
              </td>
              <td>
                <Link to={`/purchase-orders/${m.po.id}`}>{m.po.label}</Link>: {formatQuantity(m.po.quantity)} {m.item.unit} ×{" "}
                {formatDecimal(m.po.unit_price)}
              </td>
              <td>
                <Link to={`/goods-receipts/${m.grn.id}`}>{m.grn.number}</Link>:{" "}
                {t("vouchers.matchReceived", { received: formatQuantity(m.grn.received), accepted: formatQuantity(m.grn.accepted) })}
              </td>
              <td className={m.matches ? "" : "form-error"}>
                {formatQuantity(m.invoice.quantity)} × {formatDecimal(m.invoice.unit_price)} = {formatDecimal(m.invoice.total)}
                {!m.matches && ` · ${t("vouchers.matchException")}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
