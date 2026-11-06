import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  compareRun,
  compareTemplateUrl,
  decideOpening,
  getTakeover,
  importOpening,
  importPay,
  openingTemplateUrl,
  payTemplateUrl,
  signOff,
  takeoverKey,
  type CompareResult,
  type ComparedPerson,
  type OpeningBatch,
  type ParallelCheck,
  type Takeover,
  type UploadResult,
} from "../api/takeover";
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

function Errors({ lines }: { lines: string[] }) {
  if (lines.length === 0) return null;
  return (
    <ul className="form-error" role="alert">
      {lines.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}

/** P2B-14: bring the old payroll over, then run one month in both and sign it off. */
export default function PayrollTakeoverPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const found = useQuery({ queryKey: takeoverKey, queryFn: getTakeover });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: takeoverKey });
  const done = (d: Takeover) => queryClient.setQueryData(takeoverKey, d);
  const d = found.data;
  return (
    <main className="page">
      <h1>{t("takeover.title")}</h1>
      <p className="muted">{t("takeover.help")}</p>
      <ErrorLine error={found.error} />
      {d && (
        <>
          {d.can_edit && (
            <FileStep
              label={t("takeover.payTitle")}
              help={t("takeover.payHelp")}
              template={payTemplateUrl}
              run={importPay}
              summary={(r) => t("takeover.payResult", { count: r.rows ?? 0 })}
              onSaved={refresh}
            />
          )}
          {d.can_edit && (
            <FileStep
              label={t("takeover.openingTitle")}
              help={t("takeover.openingHelp")}
              template={openingTemplateUrl}
              run={importOpening}
              summary={(r) =>
                t("takeover.openingResult", {
                  count: r.employees ?? 0,
                  year: r.tax_year,
                  gross: formatDecimal(r.totals?.gross ?? "0"),
                  apit: formatDecimal(r.totals?.apit ?? "0"),
                })
              }
              onSaved={refresh}
            />
          )}
          {d.batches.length > 0 && (
            <section className="panel" aria-label={t("takeover.batches")}>
              <h2>{t("takeover.batches")}</h2>
              <ul className="plain">
                {d.batches.map((b) => (
                  <Batch key={b.id} batch={b} onDone={done} />
                ))}
              </ul>
            </section>
          )}
          {d.can_edit && <Compare runs={d.runs} onSaved={refresh} />}
          {d.checks.length > 0 && (
            <section className="panel" aria-label={t("takeover.checks")}>
              <h2>{t("takeover.checks")}</h2>
              {d.checks.map((c) => (
                <Check key={c.id} check={c} onDone={done} />
              ))}
            </section>
          )}
        </>
      )}
    </main>
  );
}

function FileStep({
  label,
  help,
  template,
  run,
  summary,
  onSaved,
}: {
  label: string;
  help: string;
  template: string;
  run: (file: File, dryRun: boolean) => Promise<UploadResult>;
  summary: (r: UploadResult) => string;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const go = useMutation({
    mutationFn: (dryRun: boolean) => run(file!, dryRun),
    onSuccess: (r) => {
      setResult(r);
      if (r.saved) onSaved();
    },
  });
  return (
    <section className="panel" aria-label={label}>
      <h2>{label}</h2>
      <p className="muted">
        {help} <a href={template}>{t("takeover.template")}</a>
      </p>
      <div className="inline-form">
        <label>
          {t("takeover.file")}
          <input
            type="file"
            accept=".xlsx"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setResult(null);
            }}
          />
        </label>
        <button type="button" className="secondary" disabled={!file || go.isPending} onClick={() => go.mutate(true)}>
          {t("takeover.check")}
        </button>
        <button
          type="button"
          disabled={!file || go.isPending || !result || result.errors.length > 0 || result.saved}
          onClick={() => go.mutate(false)}
        >
          {t("takeover.save")}
        </button>
      </div>
      {result && <Errors lines={result.errors} />}
      {result && result.errors.length === 0 && (
        <p className="notice" role="status">
          {summary(result)} {result.saved ? t("takeover.sent") : t("takeover.checked")}
        </p>
      )}
      <ErrorLine error={go.error} />
    </section>
  );
}

function Batch({ batch: b, onDone }: { batch: OpeningBatch; onDone: (d: Takeover) => void }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const act = useMutation({
    mutationFn: (action: "approve" | "reject") => decideOpening(b.id, action, reason),
    onSuccess: onDone,
  });
  return (
    <li>
      {t("takeover.batch", {
        file: b.file_name,
        year: b.tax_year,
        count: b.employees,
        gross: formatDecimal(b.gross),
        apit: formatDecimal(b.apit),
        gratuity: formatDecimal(b.gratuity),
        by: b.created_by,
      })}{" "}
      — <strong>{b.status_label}</strong>
      {b.can_decide && (
        <div className="row-actions">
          <input aria-label={t("takeover.reason")} placeholder={t("takeover.reason")} value={reason} onChange={(e) => setReason(e.target.value)} />
          <button type="button" className="small" onClick={() => act.mutate("approve")}>
            {t("takeover.approve")}
          </button>
          <button type="button" className="small secondary" onClick={() => act.mutate("reject")}>
            {t("takeover.reject")}
          </button>
        </div>
      )}
      <ErrorLine error={act.error} />
    </li>
  );
}

function Compare({ runs, onSaved }: { runs: Takeover["runs"]; onSaved: () => void }) {
  const { t } = useTranslation();
  const [run, setRun] = useState<number | null>(runs[0]?.id ?? null);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<CompareResult | null>(null);
  const go = useMutation({
    mutationFn: (save: boolean) => compareRun(run!, file!, save),
    onSuccess: (r) => {
      setResult(r);
      if (r.saved) onSaved();
    },
  });
  return (
    <section className="panel" aria-label={t("takeover.compareTitle")}>
      <h2>{t("takeover.compareTitle")}</h2>
      <p className="muted">{t("takeover.compareHelp")}</p>
      {runs.length === 0 ? (
        <p className="muted">{t("takeover.noRuns")}</p>
      ) : (
        <div className="inline-form">
          <label>
            {t("takeover.payroll")}
            <select
              value={run ?? ""}
              onChange={(e) => {
                setRun(Number(e.target.value));
                setResult(null);
              }}
            >
              {runs.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.title} ({r.status_label})
                </option>
              ))}
            </select>
          </label>
          {run && <a href={compareTemplateUrl(run)}>{t("takeover.template")}</a>}
          <label>
            {t("takeover.file")}
            <input
              type="file"
              accept=".xlsx"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setResult(null);
              }}
            />
          </label>
          <button type="button" className="secondary" disabled={!file || !run || go.isPending} onClick={() => go.mutate(false)}>
            {t("takeover.compare")}
          </button>
          <button
            type="button"
            disabled={!file || !run || go.isPending || !result || result.errors.length > 0 || result.saved}
            onClick={() => go.mutate(true)}
          >
            {t("takeover.keep")}
          </button>
        </div>
      )}
      {result && <Errors lines={result.errors} />}
      {result && result.errors.length === 0 && result.people && (
        <>
          <p className="notice" role="status">
            {t("takeover.compared", { title: result.title, count: result.employees, differences: result.differences })}{" "}
            {result.saved && t("takeover.kept")}
          </p>
          <People people={result.people} />
        </>
      )}
      <ErrorLine error={go.error} />
    </section>
  );
}

function People({ people }: { people: ComparedPerson[] }) {
  const { t } = useTranslation();
  const shown = people.filter((p) => p.differs);
  if (shown.length === 0) return <p>{t("takeover.allSame")}</p>;
  return (
    <div className="table-wrap">
      <table aria-label={t("takeover.differencesTable")}>
        <thead>
          <tr>
            <th>{t("takeover.employee")}</th>
            <th>{t("takeover.figure")}</th>
            <th className="num">{t("takeover.here")}</th>
            <th className="num">{t("takeover.old")}</th>
            <th className="num">{t("takeover.difference")}</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((p) =>
            p.missing ? (
              <tr key={p.number}>
                <td>
                  {p.number} {p.name}
                </td>
                <td colSpan={4}>{p.missing === "here" ? t("takeover.missingHere") : t("takeover.missingOld")}</td>
              </tr>
            ) : (
              p.figures
                .filter((f) => f.difference !== "0.00")
                .map((f) => (
                  <tr key={`${p.number}${f.field}`}>
                    <td>
                      {p.number} {p.name}
                    </td>
                    <td>{f.field}</td>
                    <td className="num">{formatDecimal(f.here)}</td>
                    <td className="num">{formatDecimal(f.old)}</td>
                    <td className="num">{formatDecimal(f.difference)}</td>
                  </tr>
                ))
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}

function Check({ check: c, onDone }: { check: ParallelCheck; onDone: (d: Takeover) => void }) {
  const { t } = useTranslation();
  const [note, setNote] = useState("");
  const sign = useMutation({ mutationFn: () => signOff(c.id, note), onSuccess: onDone });
  return (
    <div className="panel">
      <p>
        <strong>{c.title}</strong>{" "}
        {t("takeover.checkLine", { count: c.employees, differences: c.differences, by: c.created_by, file: c.file_name })}
      </p>
      <People people={c.people} />
      {c.signed_off_at ? (
        <p className="notice">
          {t("takeover.signedOff", { by: c.signed_off_by, at: c.signed_off_at.slice(0, 10) })}
          {c.note && ` ${c.note}`}
        </p>
      ) : c.can_sign_off ? (
        <div className="row-actions">
          <input aria-label={t("takeover.note")} placeholder={t("takeover.note")} value={note} onChange={(e) => setNote(e.target.value)} />
          <button type="button" className="small" onClick={() => sign.mutate()}>
            {t("takeover.signOff")}
          </button>
        </div>
      ) : (
        <p className="muted">{t("takeover.waitingSignOff")}</p>
      )}
      <ErrorLine error={sign.error} />
    </div>
  );
}
