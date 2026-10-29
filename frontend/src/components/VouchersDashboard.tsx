import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { voucherDashboard, vouchersKey } from "../api/vouchers";
import { formatDecimal } from "../lib/decimal";

/** Width of a bar, in %, for a share of the largest value (whole cents, no floating point
 * in any figure shown; the bar is only a picture). */
function share(value: string, largest: string): number {
  const cents = (s: string) => Number(s.replace(".", ""));
  const top = cents(largest);
  return top > 0 ? Math.max(2, Math.round((cents(value) * 100) / top)) : 0;
}

/**
 * The vouchers dashboard on the home page (spec 7A, P1-08b). Every figure opens the list
 * behind it, filtered the same way, so the totals agree; each row opens its voucher.
 */
export default function VouchersDashboard({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [division, setDivision] = useState("");
  const data = useQuery({ queryKey: [...vouchersKey, "dashboard", division], queryFn: () => voucherDashboard(division) });
  const all = useQuery({ queryKey: [...vouchersKey, "dashboard", ""], queryFn: () => voucherDashboard("") });
  const d = data.data;
  if (!d) return null;
  const seesPayments = can(me.access, "payments", "view");
  const inDivision = (params: string) => (division ? `${params}${params ? "&" : ""}division=${division}` : params);
  const largest = d.by_division.reduce(
    (top, row) => [row.pending_total, row.unpaid.remaining, top].reduce((a, b) => (Number(b) > Number(a) ? b : a)),
    "0.00",
  );

  return (
    <section className="dashboard" aria-label={t("dashboard.vouchers")}>
      <div className="row-actions">
        <h2>{t("dashboard.vouchers")}</h2>
        {(all.data?.by_division.length ?? 0) > 1 && (
          <div role="group" aria-label={t("dashboard.division")} className="tabs">
            {[{ code: "", name: t("dashboard.allDivisions") }, ...(all.data?.by_division ?? [])].map((x) => (
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
          <Link className="tile" to="/vouchers/review">
            <span className="tile-label">{t("dashboard.waitingForMe")}</span>
            <strong className="tile-figure">{d.waiting_for_me.count}</strong>
            <span className="muted">LKR {formatDecimal(d.waiting_for_me.total)}</span>
          </Link>
        )}
        {d.can_enter && d.my_vouchers.returned && d.my_vouchers.returned.count > 0 && (
          <Link className="tile attention" to={`/vouchers?${inDivision("status=returned")}`}>
            <span className="tile-label">{t("dashboard.returnedToMe")}</span>
            <strong className="tile-figure">{d.my_vouchers.returned.count}</strong>
            <span className="muted">LKR {formatDecimal(d.my_vouchers.returned.total)}</span>
          </Link>
        )}
        {d.can_enter && d.my_vouchers.draft && (
          <Link className="tile" to={`/vouchers?${inDivision("status=draft")}`}>
            <span className="tile-label">{t("dashboard.myDrafts")}</span>
            <strong className="tile-figure">{d.my_vouchers.draft.count}</strong>
            <span className="muted">LKR {formatDecimal(d.my_vouchers.draft.total)}</span>
          </Link>
        )}
        <Link className="tile" to={`/vouchers/reports?${inDivision("tab=pending")}`}>
          <span className="tile-label">{t("dashboard.pending")}</span>
          <strong className="tile-figure">{d.pending_count}</strong>
          <span className="muted">{t("dashboard.allLevels")}</span>
        </Link>
        <Link
          className="tile"
          to={seesPayments ? `/payments${division ? `?division=${division}` : ""}` : `/vouchers?${inDivision("status=director_approved,partly_paid")}`}
        >
          <span className="tile-label">{t("dashboard.unpaid")}</span>
          <strong className="tile-figure">LKR {formatDecimal(d.unpaid.remaining)}</strong>
          <span className="muted">
            {t("dashboard.unpaidDetail", { count: String(d.unpaid.count), total: formatDecimal(d.unpaid.total) })}
          </span>
        </Link>
        {d.paid_this_month && (
          <Link className="tile" to={`/payments?from=${d.paid_this_month.from}&to=${d.paid_this_month.to}${division ? `&division=${division}` : ""}`}>
            <span className="tile-label">{t("dashboard.paidThisMonth")}</span>
            <strong className="tile-figure">LKR {formatDecimal(d.paid_this_month.total)}</strong>
            <span className="muted">{t("dashboard.payments", { count: String(d.paid_this_month.count) })}</span>
          </Link>
        )}
      </div>

      {d.by_level.length > 0 && (
        <div className="panel">
          <h3>{t("dashboard.byLevel")}</h3>
          <table aria-label={t("dashboard.byLevel")}>
            <thead>
              <tr>
                <th>{t("voucherReports.waitingFor")}</th>
                <th className="num">{t("voucherReports.count")}</th>
                <th className="num">{t("vouchers.total")}</th>
                {Object.keys(d.by_level[0].bands).map((band) => (
                  <th key={band} className="num">
                    {band}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.by_level.map((row) => (
                <tr key={row.level}>
                  <td>
                    <Link to={`/vouchers/reports?${inDivision(`tab=pending&level=${row.level}`)}`}>{row.waiting_for}</Link>
                  </td>
                  <td className="num">{row.count}</td>
                  <td className="num">{formatDecimal(row.total)}</td>
                  {Object.entries(row.bands).map(([band, n]) => (
                    <td key={band} className={`num ${n > 0 && band.startsWith("15") ? "danger-text" : ""}`}>
                      {n}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!division && d.by_division.length > 1 && (
        <div className="panel">
          <h3>{t("dashboard.byDivision")}</h3>
          <table aria-label={t("dashboard.byDivision")} className="bars">
            <thead>
              <tr>
                <th>{t("vouchers.division")}</th>
                <th>{t("dashboard.pendingAmount")}</th>
                <th>{t("dashboard.unpaidAmount")}</th>
                {seesPayments && <th className="num">{t("dashboard.paidThisMonth")}</th>}
              </tr>
            </thead>
            <tbody>
              {d.by_division.map((row) => (
                <tr key={row.code}>
                  <td>
                    <button type="button" className="link-button" onClick={() => setDivision(row.code)}>
                      {row.code} {row.name}
                    </button>
                  </td>
                  <td>
                    <Link to={`/vouchers/reports?tab=pending&division=${row.code}`} className="bar-cell">
                      <span className="bar pending" style={{ width: `${share(row.pending_total, largest)}%` }} />
                      {row.pending} · {formatDecimal(row.pending_total)}
                    </Link>
                  </td>
                  <td>
                    <Link
                      to={seesPayments ? `/payments?division=${row.code}` : `/vouchers?status=director_approved,partly_paid&division=${row.code}`}
                      className="bar-cell"
                    >
                      <span className="bar unpaid" style={{ width: `${share(row.unpaid.remaining, largest)}%` }} />
                      {row.unpaid.count} · {formatDecimal(row.unpaid.remaining)}
                    </Link>
                  </td>
                  {seesPayments && <td className="num">{formatDecimal(row.paid_this_month ?? "0.00")}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {d.oldest.length > 0 && (
        <div className="panel">
          <h3>{t("dashboard.oldest")}</h3>
          <ul className="changes" aria-label={t("dashboard.oldest")}>
            {d.oldest.map((row) => (
              <li key={row.id}>
                <Link to={`/vouchers/${row.id}`} className="mono">
                  {row.number}
                </Link>{" "}
                · {row.payee} · {row.waiting_for} · {t("dashboard.days", { count: String(row.days) })} · LKR{" "}
                {formatDecimal(row.total_amount)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
