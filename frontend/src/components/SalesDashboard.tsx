import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { salesDashboard, salesReportsKey } from "../api/salesReports";
import { formatDecimal } from "../lib/decimal";

/** The sales tiles on the home page (P15-11). Each tile opens the report or list behind it,
 * worked out by the same rules, so the figures agree. */
export default function SalesDashboard() {
  const { t } = useTranslation();
  const [division, setDivision] = useState("");
  const data = useQuery({
    queryKey: [...salesReportsKey, "dashboard", division],
    queryFn: () => salesDashboard(division),
    placeholderData: (previous) => previous,
  });
  const d = data.data;
  if (!d) return null;
  const report = (tab: string) => `/sales/reports?tab=${tab}${division ? `&division=${division}` : ""}`;
  const month = d.this_month;

  return (
    <section className="dashboard" aria-label={t("dashboard.sales")}>
      <div className="row-actions">
        <h2>{t("dashboard.sales")}</h2>
        {d.divisions.length > 1 && (
          <div role="group" aria-label={t("dashboard.division")} className="tabs">
            {[{ code: "", name: t("dashboard.allDivisions") }, ...d.divisions].map((x) => (
              <button
                key={x.code}
                type="button"
                className={`tab ${division === x.code ? "active" : ""}`}
                aria-pressed={division === x.code}
                onClick={() => setDivision(x.code)}
              >
                {x.code || x.name}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="tiles">
        {d.can_approve && (
          <Link className={`tile ${d.waiting_for_me.count > 0 ? "attention" : ""}`} to={d.waiting_for_me.orders > 0 && d.waiting_for_me.quotations === 0 ? "/sales-orders?waiting=me" : "/quotations?waiting=me"}>
            <span className="tile-label">{t("dashboard.waitingForMe")}</span>
            <strong className="tile-figure">{d.waiting_for_me.count}</strong>
            <span className="muted">
              {t("dashboard.salesWaiting", { quotations: String(d.waiting_for_me.quotations), orders: String(d.waiting_for_me.orders) })}
            </span>
          </Link>
        )}
        <Link className={`tile ${d.awaiting_approval + d.expiring > 0 ? "attention" : ""}`} to={report("attention")}>
          <span className="tile-label">{t("dashboard.quotationsAttention")}</span>
          <strong className="tile-figure">{d.awaiting_approval + d.expiring}</strong>
          <span className="muted">
            {t("dashboard.attentionDetail", { approval: String(d.awaiting_approval), expiring: String(d.expiring) })}
          </span>
        </Link>
        <Link className="tile" to={`/quotations?status=approved,sent`}>
          <span className="tile-label">{t("dashboard.liveQuotations")}</span>
          <strong className="tile-figure">LKR {formatDecimal(d.live.total)}</strong>
          <span className="muted">{t("dashboard.quotationCount", { count: String(d.live.count) })}</span>
        </Link>
        <Link className="tile" to={report("winLoss")}>
          <span className="tile-label">{t("dashboard.wonThisMonth")}</span>
          <strong className="tile-figure">LKR {formatDecimal(month.won_lkr)}</strong>
          <span className="muted">
            {t("dashboard.winDetail", { won: String(month.won), lost: String(month.lost), rate: month.win_rate ?? "—" })}
          </span>
        </Link>
        <Link className="tile" to={report("orders")}>
          <span className="tile-label">{t("dashboard.openOrders")}</span>
          <strong className="tile-figure">LKR {formatDecimal(d.open_orders.total)}</strong>
          <span className={d.deliveries.overdue > 0 ? "danger-text" : "muted"}>
            {t("dashboard.deliveriesDetail", {
              count: String(d.open_orders.count),
              overdue: String(d.deliveries.overdue),
              week: String(d.deliveries.this_week),
            })}
          </span>
        </Link>
        {d.advances.count > 0 && (
          <Link className="tile" to={report("advances")}>
            <span className="tile-label">{t("dashboard.advancesOpen")}</span>
            <strong className="tile-figure">LKR {formatDecimal(d.advances.balance)}</strong>
            <span className="muted">{t("dashboard.advanceCount", { count: String(d.advances.count) })}</span>
          </Link>
        )}
      </div>
    </section>
  );
}
