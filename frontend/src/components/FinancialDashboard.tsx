import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { financialDashboard, reportsKey } from "../api/financialReports";
import { formatDecimal } from "../lib/decimal";

/** The financial tiles on the home page (P2-24), for the company or a division. Each tile
 * opens the report behind it. */
export default function FinancialDashboard() {
  const { t } = useTranslation();
  const [division, setDivision] = useState("");
  const data = useQuery({
    queryKey: [...reportsKey, "dashboard", division],
    queryFn: () => financialDashboard(division),
    placeholderData: (previous) => previous,
  });
  const d = data.data;
  if (!d) return null;
  const shown = d.division ?? "";
  const withDivision = (path: string) => (shown ? `${path}${path.includes("?") ? "&" : "?"}division=${shown}` : path);
  const m = d.this_month;
  const y = d.year_to_date;
  const choices = [...(d.company ? [{ code: "", name: t("dashboard.allDivisions") }] : []), ...d.divisions];

  return (
    <section className="dashboard" aria-label={t("dashboard.finance")}>
      <div className="row-actions">
        <h2>{t("dashboard.finance")}</h2>
        {choices.length > 1 && (
          <div role="group" aria-label={t("dashboard.division")} className="tabs">
            {choices.map((x) => (
              <button
                key={x.code}
                type="button"
                className={`tab ${shown === x.code ? "active" : ""}`}
                aria-pressed={shown === x.code}
                onClick={() => setDivision(x.code)}
              >
                {x.code || x.name}
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="tiles">
        <Link className="tile" to={withDivision(`/reports/financial?tab=pl&from=${m.from}&to=${m.to}`)}>
          <span className="tile-label">{t("dashboard.profitThisMonth")}</span>
          <strong className={`tile-figure ${m.profit.startsWith("-") ? "danger-text" : ""}`}>LKR {formatDecimal(m.profit)}</strong>
          <span className="muted">{t("dashboard.incomeCosts", { income: formatDecimal(m.income), costs: formatDecimal(m.costs) })}</span>
        </Link>
        <Link className="tile" to={withDivision(`/reports/financial?tab=pl&from=${y.from}&to=${y.to}`)}>
          <span className="tile-label">{t("dashboard.profitYear", { label: y.label })}</span>
          <strong className={`tile-figure ${y.profit.startsWith("-") ? "danger-text" : ""}`}>LKR {formatDecimal(y.profit)}</strong>
          <span className="muted">
            {y.budget_profit === null ? t("dashboard.noBudget") : t("dashboard.againstBudget", { budget: formatDecimal(y.budget_profit) })}
          </span>
        </Link>
        <Link className="tile" to={d.company && !shown ? `/reports/financial?tab=cf&from=${m.from}&to=${m.to}` : `/reports/financial?tab=bs`}>
          <span className="tile-label">{t("dashboard.cash")}</span>
          <strong className="tile-figure">LKR {formatDecimal(d.cash.balance)}</strong>
          <span className="muted">{shown ? t("dashboard.cashDivision", { count: String(d.cash.accounts ?? 0) }) : t("dashboard.cashCompany")}</span>
        </Link>
        <Link className={`tile ${d.receivables.overdue !== "0.00" ? "attention" : ""}`} to="/receivables">
          <span className="tile-label">{t("dashboard.receivables")}</span>
          <strong className="tile-figure">LKR {formatDecimal(d.receivables.total)}</strong>
          <span className={d.receivables.overdue !== "0.00" ? "danger-text" : "muted"}>
            {t("dashboard.overdue", { amount: formatDecimal(d.receivables.overdue), count: String(d.receivables.count) })}
          </span>
        </Link>
        <Link className={`tile ${d.payables.overdue !== "0.00" ? "attention" : ""}`} to="/payables">
          <span className="tile-label">{t("dashboard.payables")}</span>
          <strong className="tile-figure">LKR {formatDecimal(d.payables.total)}</strong>
          <span className={d.payables.overdue !== "0.00" ? "danger-text" : "muted"}>
            {t("dashboard.overdue", { amount: formatDecimal(d.payables.overdue), count: String(d.payables.count) })}
          </span>
        </Link>
      </div>
    </section>
  );
}
