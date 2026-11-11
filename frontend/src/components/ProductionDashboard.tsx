import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { getProductionDashboard, productionReportsKey } from "../api/productionReports";
import { formatDecimal } from "../lib/decimal";

/** The Production Manager's tiles on the home page (owner, 11 Nov 2026): what waits for their
 * decision, and what was made today. Each tile opens the page where the work is done. */
export default function ProductionDashboard() {
  const { t } = useTranslation();
  const data = useQuery({ queryKey: [...productionReportsKey, "dashboard"], queryFn: getProductionDashboard });
  const d = data.data;
  if (!d) return null;
  const w = d.waiting;
  const tile = (count: number) => `tile ${count > 0 ? "attention" : ""}`;
  return (
    <section className="dashboard" aria-label={t("pd.title")}>
      <h2>{t("pd.title")}</h2>
      <div className="tiles">
        <Link className={tile(w.shift_reports + w.corrections)} to="/shift-report">
          <span className="tile-label">{t("pd.shiftReports")}</span>
          <strong className="tile-figure">{w.shift_reports}</strong>
          <span className="muted">{t("pd.corrections", { count: w.corrections })}</span>
        </Link>
        <Link className={tile(w.issue_more)} to="/job-orders">
          <span className="tile-label">{t("pd.issueMore")}</span>
          <strong className="tile-figure">{w.issue_more}</strong>
          <span className="muted">{t("pd.issueMoreDetail")}</span>
        </Link>
        <Link className={tile(w.deviations)} to="/job-orders">
          <span className="tile-label">{t("pd.deviations")}</span>
          <strong className="tile-figure">{w.deviations}</strong>
          <span className="muted">{t("pd.deviationsDetail")}</span>
        </Link>
        <Link className={tile(w.boms + w.routings)} to={w.boms === 0 && w.routings > 0 ? "/routings" : "/boms"}>
          <span className="tile-label">{t("pd.engineering")}</span>
          <strong className="tile-figure">{w.boms + w.routings}</strong>
          <span className="muted">{t("pd.engineeringDetail", { boms: w.boms, routings: w.routings })}</span>
        </Link>
        <Link className="tile" to="/production-reports">
          <span className="tile-label">{t("pd.madeToday")}</span>
          <strong className="tile-figure">{formatDecimal(d.made_today.good)}</strong>
          <span className="muted">
            {t("pd.madeDetail", {
              rejected: formatDecimal(d.made_today.rejected),
              pct: d.made_today.reject_pct ?? "0",
              hours: d.made_today.stopped_h ?? "0",
            })}
          </span>
        </Link>
        <Link className={tile(d.moulds_due)} to="/mould-maintenance">
          <span className="tile-label">{t("pd.mouldsDue")}</span>
          <strong className="tile-figure">{d.moulds_due}</strong>
          <span className="muted">{t("pd.mouldsDetail")}</span>
        </Link>
      </div>
    </section>
  );
}
