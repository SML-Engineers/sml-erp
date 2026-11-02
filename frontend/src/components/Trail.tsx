import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { getTrail, prKey } from "../api/purchasingReports";
import { formatDecimal } from "../lib/decimal";

/** The full trail of a purchase order (spec 5A.6): PO ↔ GRN ↔ QC ↔ invoice ↔ voucher ↔
 * payment, with returns, shown on the PO, GRN and invoice pages. */
export default function Trail({ by, id }: { by: "po" | "grn" | "invoice"; id: number }) {
  const { t } = useTranslation();
  const trail = useQuery({ queryKey: [...prKey, "trail", by, id], queryFn: () => getTrail(by, id) });
  const d = trail.data;
  if (!d) return null;
  return (
    <section className="panel" aria-label={t("pr.trail")}>
      <h2>{t("pr.trail")}</h2>
      <ol className="changes">
        <li>
          <strong>{t("pr.trailPo")}</strong> <Link to={`/purchase-orders/${d.po.id}`}>{d.po.label}</Link> · {d.po.status} · LKR {formatDecimal(d.po.total_lkr)}
          {d.po.parent && (
            <>
              {" · "}
              {t("po.revisionOf")} <Link to={`/purchase-orders/${d.po.parent.id}`}>{d.po.parent.label}</Link>
            </>
          )}
        </li>
        <li>
          <strong>{t("pr.trailGrns")}</strong>{" "}
          {d.grns.length === 0
            ? "—"
            : d.grns.map((g, i) => (
                <span key={g.id}>
                  {i > 0 && ", "}
                  <Link to={`/goods-receipts/${g.id}`}>{g.number}</Link> ({g.date}, {g.status})
                </span>
              ))}
        </li>
        {d.inspections.length > 0 && (
          <li>
            <strong>{t("pr.trailQc")}</strong>{" "}
            {d.inspections.map((q, i) => (
              <span key={q.id}>
                {i > 0 && ", "}
                <Link to={`/inspections/${q.id}`}>
                  {q.grn} {q.item}
                </Link>
                : {q.decision || q.status} ({t("pr.acceptedRejected", { accepted: q.accepted, rejected: q.rejected })})
              </span>
            ))}
          </li>
        )}
        <li>
          <strong>{t("pr.trailInvoices")}</strong>{" "}
          {d.invoices.length === 0
            ? "—"
            : d.invoices.map((inv, i) => (
                <span key={inv.id}>
                  {i > 0 && ", "}
                  <Link to={`/supplier-invoices/${inv.id}`}>{inv.invoice_no}</Link> ({inv.status}, LKR {formatDecimal(inv.total_lkr)},{" "}
                  {t("pr.unpaid", { amount: formatDecimal(inv.unpaid) })})
                </span>
              ))}
        </li>
        {d.returns.length > 0 && (
          <li>
            <strong>{t("pr.trailReturns")}</strong>{" "}
            {d.returns.map((r, i) => (
              <span key={r.id}>
                {i > 0 && ", "}
                <Link to={`/supplier-returns/${r.id}`}>{r.number}</Link> ({r.kind}, {r.status})
              </span>
            ))}
          </li>
        )}
        <li>
          <strong>{t("pr.trailVouchers")}</strong>{" "}
          {d.vouchers.length === 0
            ? "—"
            : d.vouchers.map((v, i) => (
                <span key={v.id}>
                  {i > 0 && ", "}
                  <Link to={`/vouchers/${v.id}`}>{v.number}</Link> ({v.advance ? `${t("pr.advance")}, ` : ""}
                  {v.status}, LKR {formatDecimal(v.amount)}
                  {v.payments.length > 0 && `; ${t("pr.paidBy", { payments: v.payments.map((p) => `${p.number} ${p.date}`).join(", ") })}`})
                </span>
              ))}
        </li>
      </ol>
    </section>
  );
}
