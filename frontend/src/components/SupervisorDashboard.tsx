import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { getSupervisorDashboard, productionReportsKey, type SupervisorDashboardData } from "../api/productionReports";
import { formatDecimal } from "../lib/decimal";

/** The shop-floor supervisor's home page (owner, 12 Nov 2026), made for a phone and in
 * Sinhala too: today's shifts and how far each report has got, reports still to finish, the
 * plan on their machines, what was made, and the moulds due for maintenance. Their own
 * sections only (the server decides). */
export default function SupervisorDashboard() {
  const { t } = useTranslation();
  const data = useQuery({ queryKey: [...productionReportsKey, "supervisor"], queryFn: getSupervisorDashboard });
  const d = data.data;
  if (!d) return null;
  const made = (m: SupervisorDashboardData["made_today"]) =>
    t("sup.made", {
      good: formatDecimal(m.good),
      rejected: formatDecimal(m.rejected),
      pct: m.reject_pct ?? "0",
      hours: m.stopped_h ?? "0",
    });
  return (
    <section className="dashboard shop-floor" aria-label={t("sup.title")}>
      <h2>{t("sup.title")}</h2>

      <h3>{t("sup.shifts")}</h3>
      {d.shifts.length === 0 ? (
        <p className="muted">{t("sup.noShifts")}</p>
      ) : (
        <ul className="plain-list">
          {d.shifts.map((s) => (
            <li key={`${s.section}-${s.day}-${s.shift}`}>
              <Link className="button-link" to={s.report ? `/shift-report?report=${s.report}` : "/shift-report"}>
                {s.section} · {s.shift_name} · {s.day}
              </Link>{" "}
              <span className={s.status === "returned" ? "warning-text" : "muted"}>{t(`sup.status.${s.status || "none"}`)}</span>
            </li>
          ))}
        </ul>
      )}

      {d.to_finish.length > 0 && (
        <>
          <h3>{t("sup.toFinish")}</h3>
          <ul className="plain-list">
            {d.to_finish.map((r) => (
              <li key={r.id}>
                <Link to={`/shift-report?report=${r.id}`}>
                  {r.section} · {r.day} · {r.shift}
                </Link>{" "}
                <span className={r.status === "returned" ? "warning-text" : "muted"}>{t(`sup.status.${r.status}`)}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      <h3>{t("sup.plan")}</h3>
      {d.plan.length === 0 ? (
        <p className="muted">{t("sup.noPlan")}</p>
      ) : (
        <ul className="plain-list">
          {d.plan.map((e) => (
            <li key={e.id}>
              <strong>{e.machine}</strong> · {e.day} · {e.shift} · {e.item} ({e.mould}) ·{" "}
              {t("sup.pieces", { count: formatDecimal(e.quantity) })}
            </li>
          ))}
        </ul>
      )}

      <div className="tiles">
        <Link className="tile" to="/production-reports">
          <span className="tile-label">{t("sup.yesterday")}</span>
          <strong className="tile-figure">{formatDecimal(d.made_yesterday.good)}</strong>
          <span className="muted">{made(d.made_yesterday)}</span>
        </Link>
        <Link className="tile" to="/production-reports">
          <span className="tile-label">{t("sup.today")}</span>
          <strong className="tile-figure">{formatDecimal(d.made_today.good)}</strong>
          <span className="muted">{made(d.made_today)}</span>
        </Link>
        <Link className={`tile ${d.moulds_due.length > 0 ? "attention" : ""}`} to="/mould-maintenance">
          <span className="tile-label">{t("sup.mouldsDue")}</span>
          <strong className="tile-figure">{d.moulds_due.length}</strong>
          <span className="muted">{d.moulds_due.map((m) => m.mould).join(", ") || t("sup.noneDue")}</span>
        </Link>
      </div>
    </section>
  );
}
