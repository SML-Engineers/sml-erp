import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ApiError } from "../api/client";
import { getWipReport, wipReportKey } from "../api/wipReport";
import { compareDecimal, formatDecimal, formatQuantity } from "../lib/decimal";

function lastMonth(): string {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** P3-16: at month end, the open jobs' work in progress against the Work in progress account,
 * the production costs charged to orders, and machine time charged to no order. */
export default function WipReportPage() {
  const { t } = useTranslation();
  const [month, setMonth] = useState(lastMonth());
  const report = useQuery({ queryKey: [...wipReportKey, month], queryFn: () => getWipReport(month) });
  const r = report.data;
  return (
    <main className="page">
      <h1>{t("wip.title")}</h1>
      <p className="muted">{t("wip.help")}</p>
      <div className="toolbar">
        <label>
          {t("tax.month")}
          <input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} />
        </label>
      </div>
      {report.error && (
        <p className="form-error" role="alert">
          {report.error instanceof ApiError && report.error.detail ? report.error.detail : t("common.error")}
        </p>
      )}
      {r && (
        <>
          <p role="status">
            <strong>{r.reconciled ? t("wip.reconciled", { date: r.month_end }) : t("wip.notReconciled")}</strong>
          </p>
          {r.divisions.length === 0 && <p className="muted">{t("wip.none")}</p>}
          {r.divisions.map((d) => (
            <section key={d.division} className="panel" aria-label={t("wip.division", { code: d.division })}>
              <h2>{t("wip.division", { code: d.division })}</h2>
              <div className="table-wrap">
                <table aria-label={t("wip.jobsOf", { code: d.division })}>
                  <thead>
                    <tr>
                      <th>{t("wip.job")}</th>
                      <th>{t("quotations.description")}</th>
                      <th>{t("wip.status")}</th>
                      <th className="num">{t("wip.amount")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.jobs.map((j) => (
                      <tr key={j.id}>
                        <td>
                          <Link to={`/job-orders?job=${j.id}`}>{j.number}</Link>
                        </td>
                        <td>{j.description}</td>
                        <td>{j.status}</td>
                        <td className="num">{formatDecimal(j.wip)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <th colSpan={3}>{t("wip.openJobs")}</th>
                      <td className="num">{formatDecimal(d.orders)}</td>
                    </tr>
                    <tr>
                      <th colSpan={3}>{t("wip.ledger")}</th>
                      <td className="num">{formatDecimal(d.ledger)}</td>
                    </tr>
                    <tr>
                      <th colSpan={3}>{t("wip.difference")}</th>
                      <td className="num">
                        <strong className={compareDecimal(d.difference, "0") !== 0 ? "form-error" : undefined}>
                          {formatDecimal(d.difference)}
                        </strong>
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </section>
          ))}
          <section className="panel" aria-label={t("wip.absorbed")}>
            <h2>{t("wip.absorbed")}</h2>
            {r.absorbed.length === 0 ? (
              <p className="muted">{t("wip.nothing")}</p>
            ) : (
              <div className="table-wrap">
                <table aria-label={t("wip.absorbed")}>
                  <thead>
                    <tr>
                      <th>{t("wip.divisionCol")}</th>
                      <th>{t("wip.element")}</th>
                      <th className="num">{t("wip.amount")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.absorbed.map((a) => (
                      <tr key={`${a.division}-${a.element}`}>
                        <td>{a.division}</td>
                        <td>{a.element}</td>
                        <td className="num">{formatDecimal(a.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <section className="panel" aria-label={t("wip.unabsorbed")}>
            <h2>{t("wip.unabsorbed")}</h2>
            <p className="muted">{t("wip.unabsorbedHelp")}</p>
            {r.unabsorbed.length === 0 ? (
              <p className="muted">{t("wip.nothing")}</p>
            ) : (
              <div className="table-wrap">
                <table aria-label={t("wip.unabsorbed")}>
                  <thead>
                    <tr>
                      <th>{t("wip.divisionCol")}</th>
                      <th>{t("wip.machine")}</th>
                      <th>{t("wip.reason")}</th>
                      <th className="num">{t("wip.hours")}</th>
                      <th className="num">{t("wip.amount")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.unabsorbed.map((u) => (
                      <tr key={`${u.division}-${u.machine}-${u.reason}`}>
                        <td>{u.division}</td>
                        <td>{u.machine}</td>
                        <td>{u.reason}</td>
                        <td className="num">{formatQuantity(u.hours)}</td>
                        <td className="num">{formatDecimal(u.amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
