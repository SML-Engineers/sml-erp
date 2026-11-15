import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { duration, getMachinesToday, machineJobsKey, type MachineJob } from "../api/machineJobs";
import { formatTime } from "../lib/time";
import { runningMinutes, useNow } from "../lib/machineClock";

const REFRESH_MS = 60_000;

function what(job: MachineJob): string {
  return job.kind === "job" ? `${job.job}/${job.operation} ${job.operation_name ?? ""}`.trim() : `${job.order} · ${job.item ?? ""}`;
}

/** Machines now (P3-24 d; owner, 15 Nov 2026), on the Dashboard of everyone who may see
 * machine time: running, idle and under maintenance; what each running machine is doing,
 * since when and for how long, the operator and the team leader; jobs finished today; the
 * hours each machine ran today. The server keeps a team leader to their own sections. */
export default function MachinesPanel() {
  const { t } = useTranslation();
  const data = useQuery({ queryKey: [...machineJobsKey, "today"], queryFn: getMachinesToday, refetchInterval: REFRESH_MS });
  const now = useNow();
  const d = data.data;
  if (!d || d.hours.length === 0) return null;
  return (
    <section className="dashboard machines-panel" aria-label={t("mt.dashTitle")}>
      <h2>
        <Link to="/machine-time">{t("mt.dashTitle")}</Link>
      </h2>
      <div className="tiles">
        <div className="tile">
          <span className="tile-label">{t("mt.status.running")}</span>
          <span className="tile-figure machine-status running">{d.counts.running}</span>
        </div>
        <div className="tile">
          <span className="tile-label">{t("mt.status.idle")}</span>
          <span className="tile-figure">{d.counts.idle}</span>
          {d.idle.length > 0 && <span className="muted">{d.idle.join(", ")}</span>}
        </div>
        <div className="tile">
          <span className="tile-label">{t("mt.status.maintenance")}</span>
          <span className="tile-figure machine-status maintenance">{d.counts.maintenance}</span>
          {d.maintenance.length > 0 && <span className="muted">{d.maintenance.join(", ")}</span>}
        </div>
      </div>

      {d.running.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("mt.runningNow")}>
            <caption>{t("mt.runningNow")}</caption>
            <thead>
              <tr>
                <th>{t("mt.machine")}</th>
                <th>{t("mt.job")}</th>
                <th>{t("mt.started")}</th>
                <th>{t("mt.runningFor")}</th>
                <th>{t("mt.operatorCol")}</th>
                <th>{t("mt.teamLeader")}</th>
              </tr>
            </thead>
            <tbody>
              {d.running.flatMap((m) =>
                m.jobs.map((j) => (
                  <tr key={j.id}>
                    <td>{m.code}</td>
                    <td>{what(j)}</td>
                    <td className="nowrap">{formatTime(j.started_at)}</td>
                    <td className="nowrap">{duration(runningMinutes(j, now))}</td>
                    <td>{j.operator ?? ""}</td>
                    <td>{j.started_by}</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      )}

      {d.finished.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("mt.finishedToday")}>
            <caption>{t("mt.finishedToday")}</caption>
            <thead>
              <tr>
                <th>{t("mt.machine")}</th>
                <th>{t("mt.job")}</th>
                <th>{t("mt.started")}</th>
                <th>{t("mt.finished")}</th>
                <th>{t("mt.time")}</th>
              </tr>
            </thead>
            <tbody>
              {d.finished.map((j) => (
                <tr key={j.id}>
                  <td>{j.machine}</td>
                  <td>{what(j)}</td>
                  <td className="nowrap">{formatTime(j.started_at)}</td>
                  <td className="nowrap">{formatTime(j.ended_at)}</td>
                  <td className="nowrap">{duration(j.minutes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="table-wrap">
        <table aria-label={t("mt.hoursToday")}>
          <caption>{t("mt.hoursToday")}</caption>
          <thead>
            <tr>
              <th>{t("mt.machine")}</th>
              <th>{t("mt.time")}</th>
              <th>{t("mt.ofTheDay")}</th>
            </tr>
          </thead>
          <tbody>
            {d.hours.map((h) => (
              <tr key={h.machine}>
                <td>
                  {h.machine} <span className="muted">{h.name}</span>
                </td>
                <td className="nowrap">{duration(h.minutes)}</td>
                <td className="nowrap">{h.pct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
