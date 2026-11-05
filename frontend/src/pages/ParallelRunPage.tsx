import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { compareWithQuickBooks, type CompareRow } from "../api/migration";
import { formatDecimal } from "../lib/decimal";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

function Table({ title, rows, unknown, showAll }: { title: string; rows: CompareRow[]; unknown: string[]; showAll: boolean }) {
  const { t } = useTranslation();
  const shown = showAll ? rows : rows.filter((r) => !r.agrees);
  const differences = rows.filter((r) => !r.agrees).length;
  return (
    <section className="panel" aria-label={title}>
      <h2>
        {title} · {differences === 0 ? <span>✓ {t("par.allAgree")}</span> : <span className="danger-text">{t("par.differences", { count: String(differences) })}</span>}
      </h2>
      {unknown.length > 0 && <p className="notice">⚠ {t("par.unknown", { names: unknown.join("; ") })}</p>}
      {shown.length > 0 && (
        <div className="table-wrap">
          <table aria-label={title}>
            <thead>
              <tr>
                <th />
                <th className="num">QuickBooks</th>
                <th className="num">ERP</th>
                <th className="num">{t("par.difference")}</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.label}>
                  <td>{r.label}</td>
                  <td className="num">{formatDecimal(r.quickbooks)}</td>
                  <td className="num">{formatDecimal(r.erp)}</td>
                  <td className={`num ${r.agrees ? "" : "danger-text"}`}>{r.agrees ? "✓" : formatDecimal(r.difference)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** Parallel run (P2-29): QuickBooks' trial balance and ageing for a month end against the
 * ERP's figures at the same date, every difference listed to explain. */
export default function ParallelRunPage() {
  const { t } = useTranslation();
  const [files, setFiles] = useState<{ trial_balance?: File; receivables?: File; payables?: File }>({});
  const [showAll, setShowAll] = useState(false);
  const run = useMutation({ mutationFn: () => compareWithQuickBooks(files) });
  const data = run.data;
  return (
    <main className="page">
      <h1>{t("par.title")}</h1>
      <p className="muted">{t("par.help")}</p>
      <section className="panel" aria-label={t("par.files")}>
        {(["trial_balance", "receivables", "payables"] as const).map((f) => (
          <label key={f} className="stacked">
            {t(`mig.file.${f}`)}
            <input type="file" accept=".xlsx" onChange={(e) => setFiles({ ...files, [f]: e.target.files?.[0] })} />
          </label>
        ))}
        <div className="row-actions">
          <button type="button" disabled={!files.trial_balance || run.isPending} onClick={() => run.mutate()}>
            {t("par.compare")}
          </button>
          <label>
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> {t("par.showAll")}
          </label>
        </div>
        <ErrorLine error={run.error} />
      </section>
      {data && (
        <>
          <p>
            <strong>{t("par.asAt", { date: data.as_at })}</strong>
          </p>
          <Table title={t("par.accounts")} rows={data.accounts} unknown={data.unknown_accounts} showAll={showAll} />
          {data.customers && <Table title={t("par.customers")} rows={data.customers.rows} unknown={data.customers.unknown} showAll={showAll} />}
          {data.suppliers && <Table title={t("par.suppliers")} rows={data.suppliers.rows} unknown={data.suppliers.unknown} showAll={showAll} />}
        </>
      )}
    </main>
  );
}
