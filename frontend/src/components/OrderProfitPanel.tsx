import { useTranslation } from "react-i18next";

import type { OrderProfit, Rag } from "../api/orderProfits";
import { formatDecimal } from "../lib/decimal";

const money = (value: string | null) => (value === null ? "–" : formatDecimal(value));
const pct = (value: string | null) => (value === null ? "–" : `${value}%`);

export function RagTag({ status }: { status: Rag }) {
  const { t } = useTranslation();
  return <span className={`tag rag-${status}`}>{t(`profit.rag.${status}`)}</span>;
}

/** P3-17: an order's estimate, actual to date and forecast at completion, its status, the
 * alerts sent and the forecast margin day by day. */
export default function OrderProfitPanel({ profit }: { profit: OrderProfit }) {
  const { t } = useTranslation();
  const p = profit;
  return (
    <section className="panel" aria-label={t("profit.title")}>
      <h3>
        {t("profit.title")} <RagTag status={p.status} />
      </h3>
      <div className="table-wrap">
        <table aria-label={t("profit.figures")}>
          <thead>
            <tr>
              <th />
              <th className="num">{t("profit.estimate")}</th>
              <th className="num">{t("profit.actual")}</th>
              <th className="num">{t("profit.forecast")}</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <th>{t("profit.revenue")}</th>
              <td className="num">{money(p.value)}</td>
              <td className="num">{money(p.earned)}</td>
              <td className="num">{money(p.forecast_revenue)}</td>
            </tr>
            <tr>
              <th>{t("profit.cost")}</th>
              <td className="num">{money(p.estimate_cost)}</td>
              <td className="num">{money(p.cost)}</td>
              <td className="num">{money(p.forecast_cost)}</td>
            </tr>
            <tr>
              <th>{t("profit.margin")}</th>
              <td className="num">{money(p.estimate_margin)}</td>
              <td />
              <td className="num">
                <strong>{money(p.forecast_margin)}</strong> {p.margin_pct !== null && `(${p.margin_pct}%)`}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="muted">
        {t("profit.complete", { pct: p.complete_pct, good: formatDecimal(p.good), quantity: formatDecimal(p.quantity) })}
        {" · "}
        {p.estimate_basis ? t(`profit.basis.${p.estimate_basis}`, { unit: money(p.estimate_unit) }) : t("profit.basis.none")}
        {" · "}
        {t("profit.limits", {
          overrun: pct(p.overrun_pct),
          overrunLimit: pct(p.overrun_limit),
          rejects: pct(p.reject_pct),
          rejectLimit: pct(p.reject_limit),
          minimum: `${p.min_margin_pct}%`,
        })}
      </p>
      {p.alerts.length > 0 && (
        <ul className="warning-list" aria-label={t("profit.alerts")}>
          {p.alerts.map((a) => (
            <li key={a.kind}>
              <strong>{a.label}:</strong> {a.detail}
            </li>
          ))}
        </ul>
      )}
      {p.snapshots.length > 0 && (
        <details>
          <summary>{t("profit.trend", { count: p.snapshots.length })}</summary>
          <div className="table-wrap">
            <table aria-label={t("profit.trendTable")}>
              <thead>
                <tr>
                  <th>{t("costs.day")}</th>
                  <th className="num">{t("profit.completeCol")}</th>
                  <th className="num">{t("profit.cost")}</th>
                  <th className="num">{t("profit.forecastMargin")}</th>
                  <th>{t("profit.status")}</th>
                </tr>
              </thead>
              <tbody>
                {p.snapshots.map((s) => (
                  <tr key={s.day}>
                    <td>{s.day}</td>
                    <td className="num">{s.complete_pct}%</td>
                    <td className="num">{money(s.cost)}</td>
                    <td className="num">
                      {money(s.forecast_margin)} {s.margin_pct !== null && `(${s.margin_pct}%)`}
                    </td>
                    <td>
                      <RagTag status={s.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  );
}
