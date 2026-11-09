import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ApiError } from "../api/client";
import {
  getProductionReport,
  productionReportsKey,
  type DailyReport,
  type DowntimeReport,
  type JobsReport,
  type MaterialReport,
  type MouldsDueReport,
  type ParetoRow,
  type RejectsBy,
  type RejectsReport,
  type ReportKind,
} from "../api/productionReports";
import { formatDecimal, formatQuantity } from "../lib/decimal";

const KINDS: ReportKind[] = ["daily", "rejects", "downtime", "jobs", "material", "moulds"];
const pct = (value: string | null | undefined) => (value === null || value === undefined ? "–" : `${value}%`);

function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

function useReport<T>(kind: ReportKind, params: Record<string, string>) {
  return useQuery({ queryKey: [...productionReportsKey, kind, params], queryFn: () => getProductionReport<T>(kind, params) });
}

function Daily({ params }: { params: Record<string, string> }) {
  const { t } = useTranslation();
  const q = useReport<DailyReport>("daily", params);
  const d = q.data;
  return (
    <>
      <ErrorLine error={q.error} />
      {d &&
        (d.rows.length === 0 ? (
          <p className="muted">{t("prodReports.none")}</p>
        ) : (
          <div className="table-wrap">
            <table aria-label={t("prodReports.kinds.daily")}>
              <thead>
                <tr>
                  <th>{t("oee.day")}</th>
                  <th>{t("profit.section")}</th>
                  <th>{t("wip.machine")}</th>
                  <th>{t("oee.shift")}</th>
                  <th className="num">{t("prodReports.good")}</th>
                  <th className="num">{t("prodReports.rejected")}</th>
                  <th className="num">{t("prodReports.rejectPct")}</th>
                  <th className="num">{t("oee.runH")}</th>
                  <th className="num">{t("prodReports.stoppedH")}</th>
                </tr>
              </thead>
              <tbody>
                {d.rows.map((r) => (
                  <tr key={`${r.day}-${r.section}-${r.machine}-${r.shift}`}>
                    <td>{r.day}</td>
                    <td>{r.section}</td>
                    <td>{r.machine}</td>
                    <td>{r.shift}</td>
                    <td className="num">{formatQuantity(r.good)}</td>
                    <td className="num">{formatQuantity(r.rejected)}</td>
                    <td className="num">{pct(r.reject_pct)}</td>
                    <td className="num">{r.run_h}</td>
                    <td className="num">{r.stopped_h}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th colSpan={4}>{t("closeReport.total")}</th>
                  <td className="num">{formatQuantity(d.total.good)}</td>
                  <td className="num">{formatQuantity(d.total.rejected)}</td>
                  <td className="num">{pct(d.total.reject_pct)}</td>
                  <td className="num">{d.total.run_h}</td>
                  <td className="num">{d.total.stopped_h}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        ))}
    </>
  );
}

function Rejects({ params }: { params: Record<string, string> }) {
  const { t } = useTranslation();
  const [by, setBy] = useState<RejectsBy>("reason");
  const q = useReport<RejectsReport>("rejects", { ...params, by });
  const d = q.data;
  return (
    <>
      <label>
        {t("prodReports.groupBy")}
        <select value={by} onChange={(e) => setBy(e.target.value as RejectsBy)}>
          {(["reason", "part", "mould", "machine"] as RejectsBy[]).map((b) => (
            <option key={b} value={b}>
              {t(`prodReports.by.${b}`)}
            </option>
          ))}
        </select>
      </label>
      <ErrorLine error={q.error} />
      {d &&
        (d.rows.length === 0 ? (
          <p className="muted">{t("prodReports.none")}</p>
        ) : (
          <div className="table-wrap">
            <table aria-label={t("prodReports.rejectsBy", { by: t(`prodReports.by.${d.by}`) })}>
              <thead>
                <tr>
                  <th>{t(`prodReports.by.${d.by}`)}</th>
                  <th className="num">{t("prodReports.rejected")}</th>
                  {d.by !== "reason" && <th className="num">{t("prodReports.made")}</th>}
                  {d.by !== "reason" && <th className="num">{t("prodReports.rejectPct")}</th>}
                  <th className="num">{t("prodReports.share")}</th>
                </tr>
              </thead>
              <tbody>
                {d.rows.map((r) => (
                  <tr key={r.key}>
                    <td>
                      {r.key}
                      {r.name && <div className="muted">{r.name}</div>}
                    </td>
                    <td className="num">{formatQuantity(r.rejected)}</td>
                    {d.by !== "reason" && <td className="num">{formatQuantity(r.made ?? "0")}</td>}
                    {d.by !== "reason" && <td className="num">{pct(r.reject_pct)}</td>}
                    <td className="num">{pct(r.share_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </>
  );
}

function Pareto({ rows, label, reasons }: { rows: ParetoRow[]; label: string; reasons?: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="table-wrap">
      <table aria-label={label}>
        <thead>
          <tr>
            <th>{reasons ? t("prodReports.by.reason") : t("wip.machine")}</th>
            <th className="num">{t("prodReports.hours")}</th>
            <th className="num">{t("prodReports.share")}</th>
            <th className="num">{t("prodReports.cumulative")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td>
                {r.key}
                {r.name && (
                  <div className="muted">
                    {r.name}
                    {r.planned && ` · ${t("prodReports.planned")}`}
                    {r.stops !== undefined && ` · ${t("prodReports.stops", { count: r.stops })}`}
                  </div>
                )}
              </td>
              <td className="num">{r.hours}</td>
              <td className="num">
                {pct(r.share_pct)}{" "}
                <span className="oee-bar" aria-hidden="true">
                  <span style={{ width: `${Number(r.share_pct ?? 0)}%` }} />
                </span>
              </td>
              <td className="num">{pct(r.cumulative_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Downtime({ params }: { params: Record<string, string> }) {
  const { t } = useTranslation();
  const q = useReport<DowntimeReport>("downtime", params);
  const d = q.data;
  return (
    <>
      <ErrorLine error={q.error} />
      {d &&
        (d.reasons.length === 0 ? (
          <p className="muted">{t("prodReports.none")}</p>
        ) : (
          <>
            <p className="muted">{t("prodReports.downtimeTotal", { hours: d.total_h })}</p>
            <Pareto rows={d.reasons} label={t("prodReports.downtimeByReason")} reasons />
            <Pareto rows={d.machines} label={t("prodReports.downtimeByMachine")} />
          </>
        ))}
    </>
  );
}

function Jobs({ params }: { params: Record<string, string> }) {
  const { t } = useTranslation();
  const q = useReport<JobsReport>("jobs", params);
  const d = q.data;
  return (
    <>
      <ErrorLine error={q.error} />
      {d && (
        <>
          <p>
            <strong>{t("prodReports.onTime", { pct: pct(d.on_time_pct), onTime: d.on_time, completed: d.completed })}</strong>
            {d.late_open > 0 && ` · ${t("prodReports.lateOpen", { count: d.late_open })}`}
          </p>
          {d.rows.length === 0 ? (
            <p className="muted">{t("prodReports.noJobs")}</p>
          ) : (
            <div className="table-wrap">
              <table aria-label={t("prodReports.kinds.jobs")}>
                <thead>
                  <tr>
                    <th>{t("wip.job")}</th>
                    <th>{t("profit.due")}</th>
                    <th>{t("prodReports.completedOn")}</th>
                    <th className="num">{t("prodReports.estimatedH")}</th>
                    <th className="num">{t("prodReports.actualH")}</th>
                    <th className="num">{t("prodReports.timeVariance")}</th>
                    <th className="num">{t("prodReports.estimatedCost")}</th>
                    <th className="num">{t("prodReports.actualCost")}</th>
                  </tr>
                </thead>
                <tbody>
                  {d.rows.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <Link to={`/job-orders?job=${r.id}`}>{r.number}</Link>
                        <div className="muted">
                          {r.part || r.description} · {formatQuantity(r.quantity)} · {r.status}
                        </div>
                      </td>
                      <td>{r.due_date}</td>
                      <td>
                        {r.completed_on ?? "–"}
                        {r.days_late > 0 && <div className="form-error">{t("prodReports.daysLate", { count: r.days_late })}</div>}
                      </td>
                      <td className="num">{r.estimated_h}</td>
                      <td className="num">{r.actual_h}</td>
                      <td className="num">{pct(r.time_variance_pct)}</td>
                      <td className="num">{r.estimated_cost === null ? "–" : formatDecimal(r.estimated_cost)}</td>
                      <td className="num">{r.actual_cost === null ? "–" : formatDecimal(r.actual_cost)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}

function Material({ params }: { params: Record<string, string> }) {
  const { t } = useTranslation();
  const q = useReport<MaterialReport>("material", params);
  const d = q.data;
  return (
    <>
      <ErrorLine error={q.error} />
      {d &&
        (d.rows.length === 0 ? (
          <p className="muted">{t("prodReports.none")}</p>
        ) : (
          <>
            <p className="muted">{t("prodReports.materialHelp")}</p>
            <div className="table-wrap">
              <table aria-label={t("prodReports.kinds.material")}>
                <thead>
                  <tr>
                    <th>{t("prodReports.item")}</th>
                    <th className="num">{t("prodReports.issued")}</th>
                    <th className="num">{t("prodReports.standard")}</th>
                    <th className="num">{t("prodReports.difference")}</th>
                  </tr>
                </thead>
                <tbody>
                  {d.rows.map((r) => (
                    <tr key={r.item}>
                      <td>
                        {r.item}
                        <div className="muted">{r.name}</div>
                      </td>
                      <td className="num">
                        {formatQuantity(r.issued)} {r.unit}
                      </td>
                      <td className="num">{formatQuantity(r.standard)}</td>
                      <td className="num">
                        {formatQuantity(r.difference)} {r.difference_pct !== null && `(${r.difference_pct}%)`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {d.regrind.length > 0 && (
              <div className="table-wrap">
                <table aria-label={t("prodReports.regrind")}>
                  <thead>
                    <tr>
                      <th>{t("prodReports.regrind")}</th>
                      <th className="num">{t("prodReports.made")}</th>
                      <th className="num">{t("prodReports.issued")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.regrind.map((r) => (
                      <tr key={r.item}>
                        <td>{r.item}</td>
                        <td className="num">
                          {formatQuantity(r.made)} {r.unit}
                        </td>
                        <td className="num">{formatQuantity(r.issued)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ))}
    </>
  );
}

function Moulds() {
  const { t } = useTranslation();
  const q = useReport<MouldsDueReport>("moulds", {});
  const d = q.data;
  return (
    <>
      <ErrorLine error={q.error} />
      {d &&
        (d.rows.length === 0 ? (
          <p className="muted">{t("prodReports.noMoulds")}</p>
        ) : (
          <div className="table-wrap">
            <table aria-label={t("prodReports.kinds.moulds")}>
              <thead>
                <tr>
                  <th>{t("profit.mould")}</th>
                  <th>{t("profit.status")}</th>
                  <th className="num">{t("prodReports.shotsSince")}</th>
                  <th className="num">{t("prodReports.interval")}</th>
                  <th className="num">{t("prodReports.used")}</th>
                </tr>
              </thead>
              <tbody>
                {d.rows.map((r) => (
                  <tr key={r.mould}>
                    <td>
                      {r.mould}
                      <div className="muted">{r.name}</div>
                    </td>
                    <td>
                      <span className={`tag ${r.state === "due" ? "rag-red" : "rag-amber"}`}>{t(`prodReports.state.${r.state}`)}</span>
                    </td>
                    <td className="num">{r.shots_since.toLocaleString("en-US")}</td>
                    <td className="num">{r.interval.toLocaleString("en-US")}</td>
                    <td className="num">{pct(r.used_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </>
  );
}

/** P3-20: production reports from approved shift reports in the user's sections. */
export default function ProductionReportsPage() {
  const { t } = useTranslation();
  const now = new Date();
  const [kind, setKind] = useState<ReportKind>("daily");
  const [start, setStart] = useState(iso(new Date(now.getFullYear(), now.getMonth(), 1)));
  const [end, setEnd] = useState(iso(now));
  const [section, setSection] = useState("");
  const sections = useQuery({
    queryKey: [...productionReportsKey, "sections"],
    queryFn: () => getProductionReport<{ sections: { code: string; name: string }[] }>("sections", {}),
  });
  const params = { start, end, section };
  return (
    <main className="page">
      <h1>{t("prodReports.title")}</h1>
      <div className="row-actions" role="tablist" aria-label={t("prodReports.title")}>
        {KINDS.map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={kind === k}
            className={kind === k ? "small" : "secondary small"}
            onClick={() => setKind(k)}
          >
            {t(`prodReports.kinds.${k}`)}
          </button>
        ))}
      </div>
      {kind !== "moulds" && (
        <div className="toolbar">
          <label>
            {kind === "jobs" ? t("prodReports.dueFrom") : t("profit.from")}
            <input type="date" value={start} onChange={(e) => e.target.value && setStart(e.target.value)} />
          </label>
          <label>
            {t("profit.to")}
            <input type="date" value={end} onChange={(e) => e.target.value && setEnd(e.target.value)} />
          </label>
          {kind !== "jobs" && (
            <label>
              {t("profit.section")}
              <select value={section} onChange={(e) => setSection(e.target.value)}>
                <option value="">{t("profit.all")}</option>
                {(sections.data?.sections ?? []).map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.code} {s.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}
      <section className="panel" role="tabpanel" aria-label={t(`prodReports.kinds.${kind}`)}>
        <p className="muted">{t(`prodReports.help.${kind}`)}</p>
        {kind === "daily" && <Daily params={params} />}
        {kind === "rejects" && <Rejects params={params} />}
        {kind === "downtime" && <Downtime params={params} />}
        {kind === "jobs" && <Jobs params={{ start, end }} />}
        {kind === "material" && <Material params={params} />}
        {kind === "moulds" && <Moulds />}
      </section>
    </main>
  );
}
