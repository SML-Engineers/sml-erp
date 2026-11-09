import { useTranslation } from "react-i18next";

import type { CloseReport } from "../api/orderProfits";
import { formatDecimal } from "../lib/decimal";

const money = (value: string | null) => (value === null ? "–" : formatDecimal(value));

/** P3-18: a closed order's final report: revenue, cost and margin, and the estimate against
 * actual by element with the variances (a minus is cheaper than quoted). */
export default function OrderClosePanel({ report }: { report: CloseReport }) {
  const { t } = useTranslation();
  const r = report;
  return (
    <section className="panel" aria-label={t("closeReport.title")}>
      <h3>{t("closeReport.title")}</h3>
      <p className="muted">
        {t(r.automatic ? "closeReport.byDelivery" : "closeReport.byHand", { name: r.closed_by, at: r.closed_at.slice(0, 10) })}
        {" · "}
        {t("closeReport.pieces", { good: formatDecimal(r.good), rejected: formatDecimal(r.rejected), quantity: formatDecimal(r.quantity) })}
      </p>
      <dl className="details">
        <dt>{t("profit.revenue")}</dt>
        <dd>
          {money(r.revenue)} {r.revenue_basis && <span className="muted">({t(`closeReport.revenueBasis.${r.revenue_basis}`)})</span>}
        </dd>
        <dt>{t("profit.cost")}</dt>
        <dd>{money(r.cost)}</dd>
        <dt>{t("profit.margin")}</dt>
        <dd>
          <strong>{money(r.margin)}</strong> {r.margin_pct !== null && `(${r.margin_pct}%)`}
        </dd>
      </dl>
      <div className="table-wrap">
        <table aria-label={t("closeReport.variances")}>
          <thead>
            <tr>
              <th />
              <th className="num">{t("closeReport.estimate")}</th>
              <th className="num">{t("profit.actual")}</th>
              <th className="num">{t("closeReport.variance")}</th>
            </tr>
          </thead>
          <tbody>
            {r.rows.map((x) => (
              <tr key={x.key}>
                <th>{t(`closeReport.rows.${x.key}`)}</th>
                <td className="num">{money(x.estimate)}</td>
                <td className="num">{money(x.actual)}</td>
                <td className="num">{money(x.variance)}</td>
              </tr>
            ))}
            {r.material_price !== null && (
              <tr>
                <td>{t("closeReport.materialPrice")}</td>
                <td />
                <td />
                <td className="num">{money(r.material_price)}</td>
              </tr>
            )}
            {r.material_usage !== null && (
              <tr>
                <td>{t("closeReport.materialUsage")}</td>
                <td />
                <td />
                <td className="num">{money(r.material_usage)}</td>
              </tr>
            )}
          </tbody>
          <tfoot>
            <tr>
              <th>{t("closeReport.total")}</th>
              <td className="num">{money(r.estimate_cost)}</td>
              <td className="num">{money(r.cost)}</td>
              <td className="num">
                <strong>{money(r.variance)}</strong>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="muted">
        {r.basis === "quotation" ? t("closeReport.basisQuotation") : t("closeReport.basisOther")}{" "}
        {t("closeReport.actuals", {
          kg: r.actuals.kg_per_piece ?? "–",
          quotedKg: r.quoted.kg_per_piece ?? "–",
          hours: r.actuals.hours_per_1000 ?? "–",
          setup: r.actuals.setup_hours ?? "–",
          quotedSetup: r.quoted.setup_hours ?? "–",
        })}
        {r.actuals.cycle_s !== null && ` ${t("closeReport.cycle", { actual: r.actuals.cycle_s, standard: r.standard_cycle_s ?? "–" })}`}
      </p>
    </section>
  );
}
