import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  checkFiles,
  deleteMigration,
  getMigration,
  migrationAction,
  migrationKey,
  openItems,
  type ItemsReport,
  type MigrationFile,
  type MigrationReport,
  type OpeningDoc,
} from "../api/migration";
import { formatDecimal } from "../lib/decimal";

const FILES: MigrationFile[] = ["trial_balance", "receivables", "payables", "items"];

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

function Report({ report }: { report: MigrationReport }) {
  const { t } = useTranslation();
  return (
    <div aria-label={t("mig.result")} role="region">
      <dl className="details">
        <dt>{t("mig.asAt")}</dt>
        <dd>{report.as_at ?? "—"}</dd>
        <dt>{t("mig.accounts")}</dt>
        <dd>{report.accounts}</dd>
        <dt>{t("mig.totals")}</dt>
        <dd>
          {formatDecimal(report.debits)} / {formatDecimal(report.credits)}
        </dd>
        <dt>{t("mig.debtors")}</dt>
        <dd>{t("mig.withParties", { amount: formatDecimal(report.receivables), count: String(report.customers) })}</dd>
        <dt>{t("mig.creditors")}</dt>
        <dd>{t("mig.withParties", { amount: formatDecimal(report.payables), count: String(report.suppliers) })}</dd>
        <dt>{t("mig.stock")}</dt>
        <dd>
          {formatDecimal(report.stock_in_trial_balance)}
          {report.stock_in_item_list !== null && ` · ${t("mig.itemList", { amount: formatDecimal(report.stock_in_item_list) })}`}
        </dd>
      </dl>
      {report.errors.length === 0 ? (
        <p role="status">✓ {t("mig.allGood")}</p>
      ) : (
        <ul className="form-error" aria-label={t("mig.problems")}>
          {report.errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {report.warnings.map((w) => (
        <p key={w} className="notice">
          ⚠ {w}
        </p>
      ))}
    </div>
  );
}

/** Opening balances from QuickBooks (P2-28): the four QuickBooks exports checked, then one
 * opening entry approved by the Director. */
export default function MigrationPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const data = useQuery({ queryKey: migrationKey, queryFn: getMigration });
  const [files, setFiles] = useState<Partial<Record<MigrationFile, File>>>({});
  const [report, setReport] = useState<MigrationReport | null>(null);
  const run = useMutation({
    mutationFn: (make: boolean) => checkFiles(files, make),
    onSuccess: (got) => {
      setReport(got.report);
      if (got.document) void queryClient.invalidateQueries({ queryKey: migrationKey });
    },
  });
  return (
    <main className="page">
      <h1>{t("mig.title")}</h1>
      <p className="muted">{t("mig.help")}</p>
      {data.data?.can_enter && (
        <section className="panel" aria-label={t("mig.files")}>
          <h2>{t("mig.files")}</h2>
          {FILES.map((f) => (
            <label key={f} className="stacked">
              {t(`mig.file.${f}`)}
              <input type="file" accept=".xlsx" onChange={(e) => setFiles({ ...files, [f]: e.target.files?.[0] })} />
            </label>
          ))}
          <div className="row-actions">
            <button type="button" disabled={!files.trial_balance || run.isPending} onClick={() => run.mutate(false)}>
              {t("mig.check")}
            </button>
            <button type="button" className="secondary" disabled={!report || report.errors.length > 0 || run.isPending} onClick={() => run.mutate(true)}>
              {t("mig.make")}
            </button>
          </div>
          <ErrorLine error={run.error} />
          {report && <Report report={report} />}
        </section>
      )}
      <ErrorLine error={data.error} />
      {data.data?.documents.map((d) => <Document key={d.id} doc={d} />)}
      {data.data?.can_enter && <OpenItems posted={data.data.posted} state={data.data} />}
    </main>
  );
}

function Document({ doc }: { doc: OpeningDoc }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState(false);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: migrationKey });
  const act = useMutation({
    mutationFn: (action: "submit" | "approve" | "return" | "reject") => migrationAction(doc.id, action, reason),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: () => deleteMigration(doc.id), onSuccess: refresh });
  return (
    <section className="panel" aria-label={t("mig.document", { date: doc.as_at })}>
      <h2>
        {t("mig.document", { date: doc.as_at })} · {t(`mig.statuses.${doc.status}`)}
        {doc.journal_entry && ` · ${doc.journal_entry}`}
      </h2>
      <p className="muted">
        {t("mig.linesTotal", { count: String(doc.lines.length), debit: formatDecimal(doc.total_debit), credit: formatDecimal(doc.total_credit) })} ·{" "}
        {doc.created_by}
      </p>
      <button type="button" className="link" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? t("mig.hideLines") : t("mig.showLines")}
      </button>
      {open && (
        <div className="table-wrap">
          <table aria-label={t("mig.lines")}>
            <thead>
              <tr>
                <th>{t("mig.account")}</th>
                <th>{t("mig.party")}</th>
                <th className="num">{t("mig.debit")}</th>
                <th className="num">{t("mig.credit")}</th>
              </tr>
            </thead>
            <tbody>
              {doc.lines.map((l, i) => (
                <tr key={i}>
                  <td>
                    {l.account}
                    <div className="muted">{l.description}</div>
                  </td>
                  <td>{l.party}</td>
                  <td className="num">{l.debit === "0.00" ? "" : formatDecimal(l.debit)}</td>
                  <td className="num">{l.credit === "0.00" ? "" : formatDecimal(l.credit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(doc.can_send || doc.can_approve) && (
        <div className="inline-form">
          <input aria-label={t("mig.comment")} placeholder={t("mig.comment")} value={reason} onChange={(e) => setReason(e.target.value)} />
          {doc.can_send && (
            <>
              <button type="button" disabled={act.isPending} onClick={() => act.mutate("submit")}>
                {t("mig.send")}
              </button>
              {doc.history.length === 0 && (
                <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate()}>
                  {t("mig.delete")}
                </button>
              )}
            </>
          )}
          {doc.can_approve && (
            <>
              <button type="button" disabled={act.isPending} onClick={() => act.mutate("approve")}>
                {t("mig.approve")}
              </button>
              <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("return")}>
                {t("mig.return")}
              </button>
              <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("reject")}>
                {t("mig.reject")}
              </button>
            </>
          )}
        </div>
      )}
      <ErrorLine error={act.error ?? remove.error} />
      {doc.history.length > 0 && (
        <ul>
          {doc.history.map((h, i) => (
            <li key={i}>
              {h.action} · {h.by} · {h.at.slice(0, 16).replace("T", " ")}
              {h.reason && ` · ${h.reason}`}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ItemsLine({ title, report }: { title: string; report: ItemsReport }) {
  const { t } = useTranslation();
  return (
    <div role="region" aria-label={title}>
      <h3>{title}</h3>
      <p>
        {t("mig.documents", { count: String(report.documents), total: formatDecimal(report.total) })}
        {report.loaded && ` · ${t("mig.loaded")}`}
      </p>
      {report.errors.length > 0 && (
        <ul className="form-error" aria-label={`${title}: ${t("mig.problems")}`}>
          {report.errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {report.warnings.map((w) => (
        <p key={w} className="notice">
          ⚠ {w}
        </p>
      ))}
    </div>
  );
}

function OpenItems({ posted, state }: { posted: boolean; state: { open_invoices: { count: number; total: string }; open_bills: { count: number; total: string } } }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [files, setFiles] = useState<{ receivables?: File; payables?: File }>({});
  const [division, setDivision] = useState("HO");
  const run = useMutation({
    mutationFn: (load: boolean) => openItems(files, division, load),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: migrationKey }),
  });
  const result = run.data;
  const clean = result && Object.values(result).every((r) => r && r.errors.length === 0);
  return (
    <section className="panel" aria-label={t("mig.part2")}>
      <h2>{t("mig.part2")}</h2>
      <p className="muted">{t("mig.part2Help")}</p>
      <p>{t("mig.loadedInvoices", { count: String(state.open_invoices.count), total: formatDecimal(state.open_invoices.total) })}</p>
      <p>{t("mig.loadedBills", { count: String(state.open_bills.count), total: formatDecimal(state.open_bills.total) })}</p>
      {!posted ? (
        <p className="notice">{t("mig.postFirst")}</p>
      ) : (
        <>
          <label className="stacked">
            {t("mig.file.receivables")}
            <input type="file" accept=".xlsx" onChange={(e) => setFiles({ ...files, receivables: e.target.files?.[0] })} />
          </label>
          <label className="stacked">
            {t("mig.file.payables")}
            <input type="file" accept=".xlsx" onChange={(e) => setFiles({ ...files, payables: e.target.files?.[0] })} />
          </label>
          <label>
            {t("mig.defaultDivision")}
            <input value={division} maxLength={2} onChange={(e) => setDivision(e.target.value.toUpperCase())} />
          </label>
          <div className="row-actions">
            <button type="button" disabled={!(files.receivables || files.payables) || run.isPending} onClick={() => run.mutate(false)}>
              {t("mig.checkItems")}
            </button>
            <button type="button" className="secondary" disabled={!clean || run.isPending} onClick={() => run.mutate(true)}>
              {t("mig.loadItems")}
            </button>
          </div>
        </>
      )}
      <ErrorLine error={run.error} />
      {result?.receivables && <ItemsLine title={t("mig.file.receivables")} report={result.receivables} />}
      {result?.payables && <ItemsLine title={t("mig.file.payables")} report={result.payables} />}
    </section>
  );
}
