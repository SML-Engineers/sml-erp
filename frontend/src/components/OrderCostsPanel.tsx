import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { OrderCosts } from "../api/orderCosts";
import { formatDecimal } from "../lib/decimal";

/** P3-16: an order's costs by element, rejects shown separately, and every entry with its
 * source on request. */
export default function OrderCostsPanel({ costs, onRefresh, busy }: { costs: OrderCosts; onRefresh?: () => void; busy?: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <section className="panel" aria-label={t("costs.title")}>
      <h3>{t("costs.title")}</h3>
      <div className="table-wrap">
        <table aria-label={t("costs.byElement")}>
          <tbody>
            {costs.elements.map((e) => (
              <tr key={e.element}>
                <td>{e.label}</td>
                <td className="num">{formatDecimal(e.amount)}</td>
              </tr>
            ))}
            <tr>
              <td>
                <strong>{t("costs.total")}</strong>
              </td>
              <td className="num">
                <strong>{formatDecimal(costs.total)}</strong>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="muted">
        {t("costs.pieces", { good: formatDecimal(costs.good), rejected: formatDecimal(costs.rejected) })}
        {costs.per_good && ` · ${t("costs.perGood", { amount: formatDecimal(costs.per_good) })}`}
        {Number(costs.rejected) > 0 && ` · ${t("costs.onRejects", { amount: formatDecimal(costs.on_rejects) })}`}
      </p>
      {costs.not_costed.length > 0 && <p className="notice">{t("costs.notCosted", { sections: costs.not_costed.join(", ") })}</p>}
      {costs.out_of_date && <p className="notice">{t("costs.outOfDate")}</p>}
      <div className="row-actions">
        <button type="button" className="secondary" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? t("costs.hideEntries") : t("costs.showEntries", { count: costs.entries.length })}
        </button>
        {costs.can_refresh && onRefresh && (
          <button type="button" className="secondary" disabled={busy} onClick={onRefresh}>
            {t("costs.refresh")}
          </button>
        )}
      </div>
      {open && (
        <div className="table-wrap">
          <table aria-label={t("costs.entries")}>
            <thead>
              <tr>
                <th>{t("costs.day")}</th>
                <th>{t("costs.element")}</th>
                <th>{t("costs.source")}</th>
                <th className="num">{t("costs.quantity")}</th>
                <th className="num">{t("costs.rate")}</th>
                <th className="num">{t("costs.amount")}</th>
              </tr>
            </thead>
            <tbody>
              {costs.entries.map((e) => (
                <tr key={e.id} className={e.adjusts ? "muted" : undefined}>
                  <td>{e.day}</td>
                  <td>{costs.elements.find((x) => x.element === e.element)?.label ?? t(`costs.elements.${e.element}`)}</td>
                  <td>{e.description}</td>
                  <td className="num">{e.quantity && `${formatDecimal(e.quantity)} ${e.unit}`}</td>
                  <td className="num">{e.rate && formatDecimal(e.rate)}</td>
                  <td className="num">{formatDecimal(e.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
