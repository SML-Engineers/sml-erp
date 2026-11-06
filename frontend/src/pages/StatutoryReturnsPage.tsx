import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { getReturn, returnUrl, type ReturnKind } from "../api/payroll";
import { formatDecimal } from "../lib/decimal";

const KINDS: ReturnKind[] = ["epf", "etf", "apit", "etf-half", "apit-year"];

/** The last pay month that has normally been paid: the month before this one. */
function lastMonth(): string {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** EPF, ETF and APIT returns from the approved payrolls (P2B-09). */
export default function StatutoryReturnsPage() {
  const { t } = useTranslation();
  const [kind, setKind] = useState<ReturnKind>("epf");
  const [month, setMonth] = useState(lastMonth);
  const [year, setYear] = useState(() => {
    const [y, m] = lastMonth().split("-").map(Number);
    return String(m >= 4 ? y : y - 1);
  });
  const [half, setHalf] = useState("2");
  const query =
    kind === "etf-half" ? `year=${year}&half=${half}` : kind === "apit-year" ? `year=${year}` : `month=${month}`;
  const found = useQuery({ queryKey: ["payroll-returns", kind, query], queryFn: () => getReturn(kind, query) });
  const r = found.data;
  const show = (v: string | number, i: number, from: number) =>
    i >= from && typeof v === "string" && /^-?\d+\.\d{2}$/.test(v) ? formatDecimal(v) : v;
  return (
    <div className="page">
      <h1>{t("returns.title")}</h1>
      <p className="muted">{t("returns.help")}</p>
      <div className="panel form-grid">
        <label>
          {t("returns.kind")}
          <select value={kind} onChange={(e) => setKind(e.target.value as ReturnKind)}>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`returns.kinds.${k}`)}
              </option>
            ))}
          </select>
        </label>
        {(kind === "epf" || kind === "etf" || kind === "apit") && (
          <label>
            {t("returns.month")}
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
          </label>
        )}
        {(kind === "etf-half" || kind === "apit-year") && (
          <label>
            {kind === "apit-year" ? t("returns.yearOfAssessment") : t("returns.year")}
            <input inputMode="numeric" value={year} onChange={(e) => setYear(e.target.value)} />
          </label>
        )}
        {kind === "etf-half" && (
          <label>
            {t("returns.half")}
            <select value={half} onChange={(e) => setHalf(e.target.value)}>
              <option value="1">{t("returns.half1")}</option>
              <option value="2">{t("returns.half2")}</option>
            </select>
          </label>
        )}
      </div>
      {found.error && (
        <p className="form-error" role="alert">
          {found.error instanceof ApiError && found.error.detail ? found.error.detail : t("common.error")}
        </p>
      )}
      {r && (
        <section className="panel" aria-label={r.title}>
          <h2>{r.title}</h2>
          {r.lines.map((line) => (
            <p key={line} className="muted">
              {line}
            </p>
          ))}
          <div className="row-actions">
            <a className="button secondary" href={returnUrl(kind, query, "xlsx")}>
              {t("returns.excel")}
            </a>
            <a className="button secondary" href={returnUrl(kind, query, "pdf")} target="_blank" rel="noreferrer">
              {t("returns.pdf")}
            </a>
            {kind === "apit-year" && (
              <a className="button secondary" href={returnUrl("apit-certificates", `year=${year}`)} target="_blank" rel="noreferrer">
                {t("returns.certificates")}
              </a>
            )}
          </div>
          <div className="table-wrap">
            <table aria-label={r.title}>
              <thead>
                <tr>
                  {r.columns.map((c, i) => (
                    <th key={c} className={i >= r.money_from ? "num" : undefined}>
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {r.rows.length === 0 && (
                  <tr>
                    <td colSpan={r.columns.length} className="muted">
                      {t("returns.none")}
                    </td>
                  </tr>
                )}
                {r.rows.map((row, n) => (
                  <tr key={n}>
                    {row.map((v, i) => (
                      <td key={i} className={i >= r.money_from ? "num" : undefined}>
                        {show(v, i, r.money_from)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  {r.totals.map((v, i) => (
                    <th key={i} className={i >= r.money_from ? "num" : undefined}>
                      {show(v, i, r.money_from)}
                    </th>
                  ))}
                </tr>
              </tfoot>
            </table>
          </div>
          {r.notes.map((n) => (
            <p key={n} className="muted">
              {n}
            </p>
          ))}
        </section>
      )}
    </div>
  );
}
