import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ApiError } from "../api/client";
import { getMachineHours, machineJobsKey } from "../api/machineJobs";
import { formatDecimal } from "../lib/decimal";
import { factoryToday, formatDateTime } from "../lib/time";

/** Machine hours (P3-24 e; owner, 15 Nov 2026): hours run per machine by day, week or month
 * with downtime and utilisation; each job's actual time against the estimate; for people who
 * may see costs, the machine cost against the estimate. Each job and order opens its page,
 * where order profitability shows its profit or loss. */
export default function MachineHoursPage() {
  const { t } = useTranslation();
  const today = factoryToday();
  const [start, setStart] = useState(`${today.slice(0, 8)}01`);
  const [end, setEnd] = useState(today);
  const [by, setBy] = useState("day");
  const report = useQuery({
    queryKey: [...machineJobsKey, "hours", start, end, by],
    queryFn: () => getMachineHours(start, end, by),
    enabled: Boolean(start && end),
  });
  const d = report.data;

  return (
    <div className="page">
      <h1>{t("mh.title")}</h1>
      <p className="muted">{t("mh.help")}</p>
      <div className="form-grid filters">
        <label>
          {t("mh.from")}
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          {t("mh.to")}
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <label>
          {t("mh.by")}
          <select value={by} onChange={(e) => setBy(e.target.value)}>
            <option value="day">{t("mh.day")}</option>
            <option value="week">{t("mh.week")}</option>
            <option value="month">{t("mh.month")}</option>
          </select>
        </label>
      </div>
      {report.isError && (
        <p className="form-error" role="alert">
          {report.error instanceof ApiError && report.error.detail ? report.error.detail : t("common.error")}
        </p>
      )}
      {d && (
        <>
          <section className="panel" aria-label={t("mh.machines")}>
            <h2>{t("mh.machines")}</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t("mt.machine")}</th>
                    {d.periods.map((p) => (
                      <th key={p} className="num">
                        {p}
                      </th>
                    ))}
                    <th className="num">{t("mh.hours")}</th>
                    <th className="num">{t("mh.downtime")}</th>
                    <th className="num">{t("mh.utilisation")}</th>
                    {d.show_cost && <th className="num">{t("mh.costVsEstimate")}</th>}
                  </tr>
                </thead>
                <tbody>
                  {d.machines.map((m) => (
                    <tr key={m.machine}>
                      <td>
                        {m.machine} <span className="muted">{m.name}</span>
                      </td>
                      {m.periods.map((p) => (
                        <td key={p.period} className="num" title={t("mh.cellTitle", { down: p.downtime_hours, pct: p.utilisation })}>
                          {p.hours}
                        </td>
                      ))}
                      <td className="num">
                        <strong>{m.hours}</strong>
                      </td>
                      <td className="num">{m.downtime_hours}</td>
                      <td className="num">{m.utilisation}%</td>
                      {d.show_cost && m.cost_vs_estimate && (
                        <td className={`num ${m.cost_vs_estimate.over ? "warning-text" : ""}`}>
                          {formatDecimal(m.cost_vs_estimate.actual)} / {formatDecimal(m.cost_vs_estimate.estimate)}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel" aria-label={t("mh.jobs")}>
            <h2>{t("mh.jobs")}</h2>
            {d.jobs.length === 0 && <p className="muted">{t("mt.none")}</p>}
            {d.jobs.length > 0 && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>{t("mt.machine")}</th>
                      <th>{t("mt.job")}</th>
                      <th>{t("mt.started")}</th>
                      <th className="num">{t("mh.actual")}</th>
                      <th className="num">{t("mh.estimate")}</th>
                      {d.show_cost && <th className="num">{t("mh.cost")}</th>}
                      {d.show_cost && <th className="num">{t("mh.estimateCost")}</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {d.jobs.map((j) => (
                      <tr key={j.id}>
                        <td>{j.machine}</td>
                        <td>
                          {j.job_id ? (
                            <Link to={`/job-orders?job=${j.job_id}`}>
                              {j.job}/{j.operation}
                            </Link>
                          ) : (
                            <Link to={`/production-orders?order=${j.order_id}`}>{j.order}</Link>
                          )}{" "}
                          <span className="muted">{j.operation_name ?? ""}</span>
                        </td>
                        <td className="nowrap">{formatDateTime(j.started_at)}</td>
                        <td className={`num ${j.over ? "warning-text" : ""}`}>
                          {j.hours}
                          {!j.ended_at && <span className="muted"> {t("mt.running")}</span>}
                        </td>
                        <td className="num">
                          {j.estimate_hours ?? "—"}
                          {j.over && j.over_pct && <span className="warning-text"> {t("mh.over", { pct: j.over_pct })}</span>}
                        </td>
                        {d.show_cost && <td className="num">{j.cost ? formatDecimal(j.cost) : ""}</td>}
                        {d.show_cost && <td className="num">{j.estimate_cost ? formatDecimal(j.estimate_cost) : "—"}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {d.show_cost && (
              <p className="muted">
                {t("mh.profitHint")} <Link to="/order-profits">{t("profit.pageTitle")}</Link>
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
