import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ApiError } from "../api/client";
import { getSscl, getVat, getWht, taxExportUrl, taxReportsKey, type Category } from "../api/taxReports";
import { formatDecimal } from "../lib/decimal";

const CATEGORIES: Category[] = ["standard", "zero", "exempt", "outside"];

function lastMonth(): string {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
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

function Downloads({ report, year, month }: { report: "vat" | "vat/purchases" | "sscl" | "wht"; year: number; month: number }) {
  return (
    <span className="row-actions">
      <a className="button-link secondary small" href={taxExportUrl(report, year, month, "xlsx")}>
        Excel
      </a>
      <a className="button-link secondary small" href={taxExportUrl(report, year, month, "pdf")}>
        PDF
      </a>
    </span>
  );
}

/** Tax reports for filing (P2-20): the VAT return, SSCL and WHT for a month, each line traced
 * to its document. */
export default function TaxReportsPage() {
  const { t } = useTranslation();
  const [period, setPeriod] = useState(lastMonth());
  const [year, month] = period.split("-").map(Number);
  const vat = useQuery({ queryKey: [...taxReportsKey, "vat", period], queryFn: () => getVat(year, month) });
  const sscl = useQuery({ queryKey: [...taxReportsKey, "sscl", period], queryFn: () => getSscl(year, month) });
  const wht = useQuery({ queryKey: [...taxReportsKey, "wht", period], queryFn: () => getWht(year, month) });
  const v = vat.data;
  return (
    <main className="page">
      <h1>{t("tax.title")}</h1>
      <p className="muted">{t("tax.help")}</p>
      <div className="toolbar">
        <label>
          {t("tax.month")}
          <input type="month" value={period} onChange={(e) => e.target.value && setPeriod(e.target.value)} />
        </label>
      </div>
      <ErrorLine error={vat.error ?? sscl.error ?? wht.error} />
      {v && (
        <section className="panel" aria-label={t("tax.vat")}>
          <h2>
            {t("tax.vat")} <Downloads report="vat" year={year} month={month} />
          </h2>
          <dl className="details">
            {CATEGORIES.map((c) => (
              <div key={c}>
                <dt>{t(`tax.categories.${c}`)}</dt>
                <dd>{formatDecimal(v.supplies[c])}</dd>
              </div>
            ))}
            <dt>{t("tax.outputVat")}</dt>
            <dd>{formatDecimal(v.output_vat)}</dd>
            <dt>{t("tax.inputVat")}</dt>
            <dd>{formatDecimal(v.input_vat)}</dd>
            <dt>{t("tax.payable")}</dt>
            <dd>
              <strong>{formatDecimal(v.payable)}</strong>
            </dd>
          </dl>
          {v.output_vat !== v.ledger_output_vat && (
            <p className="notice" role="status">
              {t("tax.ledgerDiffers", { ledger: formatDecimal(v.ledger_output_vat) })}
            </p>
          )}
          <div className="table-wrap">
            <table aria-label={t("tax.sales")}>
              <thead>
                <tr>
                  <th>{t("tax.date")}</th>
                  <th>{t("tax.document")}</th>
                  <th>{t("tax.customer")}</th>
                  {CATEGORIES.map((c) => (
                    <th key={c} className="num">
                      {t(`tax.short.${c}`)}
                    </th>
                  ))}
                  <th className="num">{t("tax.vatShort")}</th>
                </tr>
              </thead>
              <tbody>
                {v.sales.map((r) => (
                  <tr key={r.document}>
                    <td>{r.date}</td>
                    <td>
                      <Link to={r.link}>{r.document}</Link>
                      <div className="muted">{r.kind}</div>
                    </td>
                    <td>
                      {r.customer}
                      {r.tin && <div className="muted">TIN {r.tin}</div>}
                    </td>
                    {CATEGORIES.map((c) => (
                      <td key={c} className="num">
                        {Number(r[c]) ? formatDecimal(r[c]) : ""}
                      </td>
                    ))}
                    <td className="num">{formatDecimal(r.vat)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h3>
            {t("tax.purchases")} <Downloads report="vat/purchases" year={year} month={month} />
          </h3>
          {v.purchases.length === 0 ? (
            <p className="muted">{t("tax.none")}</p>
          ) : (
            <ul className="plain-list">
              {v.purchases.map((r, i) => (
                <li key={i}>
                  {r.date} · {r.document || r.entry} · {r.supplier} {r.tin && `(TIN ${r.tin})`} · {formatDecimal(r.vat)}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {sscl.data && (
        <section className="panel" aria-label={t("tax.sscl")}>
          <h2>
            {t("tax.sscl")} <Downloads report="sscl" year={year} month={month} />
          </h2>
          {sscl.data.rows.length === 0 ? (
            <p className="muted">{t("tax.none")}</p>
          ) : (
            <ul className="plain-list">
              {sscl.data.rows.map((r, i) => (
                <li key={i}>
                  {r.date} · {r.document} · {r.customer} · {r.component} {r.rate}% {t("tax.on")} {formatDecimal(r.base)} = {formatDecimal(r.sscl)}
                </li>
              ))}
            </ul>
          )}
          <p>
            <strong>
              {t("tax.total")}: {formatDecimal(sscl.data.total)}
            </strong>
          </p>
        </section>
      )}
      {wht.data && (
        <section className="panel" aria-label={t("tax.wht")}>
          <h2>
            {t("tax.wht")} <Downloads report="wht" year={year} month={month} />
          </h2>
          {wht.data.rows.length === 0 ? (
            <p className="muted">{t("tax.none")}</p>
          ) : (
            <ul className="plain-list">
              {wht.data.rows.map((r) => (
                <li key={r.certificate}>
                  {r.date} · {r.certificate} · {r.supplier} {r.tin && `(TIN ${r.tin})`} · {r.rate} {t("tax.on")} {formatDecimal(r.gross)} = {formatDecimal(r.wht)}
                </li>
              ))}
            </ul>
          )}
          <p>
            <strong>
              {t("tax.total")}: {formatDecimal(wht.data.total)}
            </strong>
          </p>
        </section>
      )}
    </main>
  );
}
