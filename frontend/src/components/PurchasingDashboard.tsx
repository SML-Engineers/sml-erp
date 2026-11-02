import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { getDashboard, prKey } from "../api/purchasingReports";
import { formatDecimal } from "../lib/decimal";

/** Purchasing and stores tiles on the home page (P16-13); each opens its report or list. */
export default function PurchasingDashboard() {
  const { t } = useTranslation();
  const data = useQuery({ queryKey: [...prKey, "dashboard"], queryFn: () => getDashboard() });
  const d = data.data;
  if (!d) return null;
  return (
    <section className="dashboard" aria-label={t("pr.dashboard")}>
      <h2>{t("pr.dashboard")}</h2>
      <div className="tiles">
        {d.waiting_for_me > 0 && (
          <Link className="tile attention" to="/purchase-orders?waiting=me">
            <span className="tile-label">{t("dashboard.waitingForMe")}</span>
            <strong className="tile-figure">{d.waiting_for_me}</strong>
            <span className="muted">{t("pr.waitingDetail")}</span>
          </Link>
        )}
        <Link className={`tile ${d.overdue > 0 ? "attention" : ""}`} to="/purchasing/reports?tab=open">
          <span className="tile-label">{t("pr.openPos")}</span>
          <strong className="tile-figure">{d.open_orders}</strong>
          <span className={d.overdue > 0 ? "form-error" : "muted"}>{t("pr.overdueDetail", { count: d.overdue })}</span>
        </Link>
        <Link className={`tile ${d.qc_waiting > 0 ? "attention" : ""}`} to="/inspections">
          <span className="tile-label">{t("pr.qcWaiting")}</span>
          <strong className="tile-figure">{d.qc_waiting}</strong>
          <span className="muted">{t("pr.qcDetail")}</span>
        </Link>
        <Link className="tile" to="/purchasing/reports?tab=grni">
          <span className="tile-label">{t("pr.grniTile")}</span>
          <strong className="tile-figure">LKR {formatDecimal(d.grni.total)}</strong>
          <span className="muted">{t("pr.grniDetail", { count: d.grni.count })}</span>
        </Link>
        <Link className={`tile ${d.held_invoices > 0 ? "attention" : ""}`} to="/purchasing/reports?tab=held">
          <span className="tile-label">{t("pr.heldTile")}</span>
          <strong className="tile-figure">{d.held_invoices}</strong>
          <span className="muted">{t("pr.heldDetail")}</span>
        </Link>
        <Link className="tile" to="/stock">
          <span className="tile-label">{t("pr.stockTile")}</span>
          <strong className="tile-figure">LKR {formatDecimal(d.stock_value)}</strong>
          <span className="muted">{t("pr.stockDetail")}</span>
        </Link>
      </div>
    </section>
  );
}
