import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import {
  askCorrection,
  decideCorrection,
  decideReport,
  getReport,
  getReports,
  openReport,
  reportsKey,
  saveReport,
  submitReport,
  type DowntimeValues,
  type JobWorkValues,
  type ManpowerValues,
  type MaterialValues,
  type ReportValues,
  type RunValues,
  type ShiftReport,
} from "../api/shiftReports";
import ScanButton from "../components/ScanButton";
import { formatDecimal } from "../lib/decimal";
import {
  clearPending,
  isNetworkError,
  keepCopy,
  readCopy,
  readPending,
  timeOf,
  useOnline,
  writePending,
  type PendingSave,
} from "../lib/offline";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** P3-08: the supervisor's shift report, made for phones and tablets: moulding runs, or job
 * card operations in a machining section (P3-12). */
export default function ShiftReportPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const id = Number(params.get("report")) || null;
  return (
    <main className="page shop-floor">
      <h1>{t("shiftReport.title")}</h1>
      {id ? <Report key={id} id={id} onBack={() => setParams({})} /> : <Start onOpen={(r) => setParams({ report: String(r) })} />}
    </main>
  );
}

function Start({ onOpen }: { onOpen: (id: number) => void }) {
  const { t } = useTranslation();
  const found = useQuery({ queryKey: reportsKey, queryFn: getReports });
  const open = useMutation({ mutationFn: openReport, onSuccess: (r) => onOpen(r.id) });
  const d = found.data;
  return (
    <>
      <p className="muted">{t("shiftReport.help")}</p>
      <ErrorLine error={found.error} />
      {d && d.can_enter && (
        <section className="panel" aria-label={t("shiftReport.openNow")}>
          <h2>{t("shiftReport.openNow")}</h2>
          {d.open.length === 0 && <p className="muted">{t("shiftReport.noneOpen")}</p>}
          {d.open.map((s) => (
            <p key={`${s.section}-${s.day}-${s.shift}`}>
              <button
                type="button"
                disabled={open.isPending}
                onClick={() => (s.report ? onOpen(s.report) : open.mutate({ section: s.section, shift: s.shift, day: s.day }))}
              >
                {t(s.report ? "shiftReport.continue" : "shiftReport.start", { section: s.section, shift: s.shift_name, day: s.day })}
              </button>
              {s.status && <span className="muted small"> {s.status}</span>}
            </p>
          ))}
          <ErrorLine error={open.error} />
        </section>
      )}
      {d && d.recent.length > 0 && (
        <section className="panel" aria-label={t("shiftReport.recent")}>
          <h2>{t("shiftReport.recent")}</h2>
          <div className="table-wrap">
            <table aria-label={t("shiftReport.recent")}>
              <tbody>
                {d.recent.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <button type="button" className="link" onClick={() => onOpen(r.id)}>
                        {r.section} {r.day} {r.shift_name}
                      </button>
                    </td>
                    <td>{r.status_label}</td>
                    <td>{r.created_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}

function valuesOf(r: ShiftReport): ReportValues {
  return {
    runs: r.runs.map((x) => ({
      machine: x.machine,
      order: x.order,
      plan_entry: x.plan_entry,
      material_lot: x.material_lot,
      operator: x.operator,
      start_time: x.start_time,
      end_time: x.end_time,
      start_counter: String(x.start_counter),
      end_counter: String(x.end_counter),
      rejects: x.rejects.map((j) => ({ reason: j.reason, quantity: String(j.quantity) })),
    })),
    operations: r.operations.map((x) => ({
      job: x.job,
      operation: String(x.operation),
      machine: x.machine,
      operator: x.operator,
      start_time: x.start_time,
      end_time: x.end_time,
      completed: x.completed,
      rework: x.rework,
      setup: x.setup,
      notes: x.notes,
      rejects: x.rejects.map((j) => ({ ...j })),
    })),
    downtime: r.downtime.map((x) => ({ ...x })),
    materials: r.materials.map((x) => ({ ...x })),
    manpower: r.manpower.map((x) => ({ machine: x.machine, people: String(x.people), overtime_hours: x.overtime_hours })),
    notes: r.notes,
  };
}

const NEW_RUN: RunValues = {
  machine: "",
  order: "",
  material_lot: "",
  operator: "",
  start_time: "",
  end_time: "",
  start_counter: "",
  end_counter: "",
  rejects: [],
};

function Report({ id, onBack }: { id: number; onBack: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = ["shift-report", id];
  const online = useOnline();
  // P3-21: the copy kept on this phone is shown when the server cannot be reached.
  const [copyAt, setCopyAt] = useState<string | null>(null);
  const found = useQuery({
    queryKey: key,
    queryFn: async () => {
      try {
        const d = await getReport(id);
        keepCopy(d);
        setCopyAt(null);
        return d;
      } catch (error) {
        const copy = isNetworkError(error) ? readCopy(id) : null;
        if (!copy) throw error;
        setCopyAt(copy.at);
        return copy.report;
      }
    },
  });
  const [pending, setPending] = useState<PendingSave | null>(() => readPending(id));
  const [conflict, setConflict] = useState<ShiftReport | null>(null);
  const [values, setValues] = useState<ReportValues | null>(() => readPending(id)?.values ?? null);
  const r = found.data;
  const v = values ?? (r ? valuesOf(r) : null);
  const done = (d: ShiftReport) => {
    queryClient.setQueryData(key, d);
    queryClient.invalidateQueries({ queryKey: reportsKey });
    keepCopy(d);
    clearPending(id);
    setPending(null);
    setConflict(null);
    setCopyAt(null);
    setValues(null);
  };
  /** Keep the save on the phone, made on the version the supervisor's copy came from. */
  const keepOnPhone = (x: ReportValues) => {
    const kept: PendingSave = { values: x, base: pending?.base ?? r?.version ?? "", savedAt: new Date().toISOString() };
    writePending(id, kept);
    setPending(kept);
    setValues(x);
  };
  const conflicted = (error: unknown) => {
    if (error instanceof ApiError && error.status === 409) {
      setConflict((error.body as { current?: ShiftReport } | null)?.current ?? null);
      return true;
    }
    return false;
  };
  const save = useMutation({
    mutationFn: async (x: ReportValues) => {
      if (!navigator.onLine) throw new TypeError("offline");
      return saveReport(id, x, pending?.base ?? r?.version);
    },
    onSuccess: done,
    onError: (error, x) => {
      if (isNetworkError(error)) keepOnPhone(x);
      else if (conflicted(error)) keepOnPhone(x);
    },
  });
  // Sends what is kept on the phone; "force" sends it over a report saved elsewhere meanwhile.
  const send = useMutation({
    mutationFn: (force: boolean) => {
      const kept = readPending(id);
      if (!kept) throw new Error("Nothing kept on this phone.");
      return saveReport(id, kept.values, force ? undefined : kept.base);
    },
    onSuccess: done,
    onError: (error) => void conflicted(error),
  });
  const { mutate: sendKept } = send;
  useEffect(() => {
    // Sent when the report is opened with a connection, and whenever the connection returns.
    const retry = () => {
      if (readPending(id)) sendKept(false);
    };
    if (navigator.onLine) retry();
    window.addEventListener("online", retry);
    return () => window.removeEventListener("online", retry);
  }, [id, sendKept]);
  const submit = useMutation({
    mutationFn: async (x: ReportValues) => {
      await saveReport(id, x, pending?.base ?? r?.version);
      return submitReport(id);
    },
    onSuccess: done,
    onError: (error) => void conflicted(error),
  });
  if (!r || !v) return <ErrorLine error={found.error} />;
  const edit = r.editable;
  const put = (next: Partial<ReportValues>) => setValues({ ...v, ...next });
  const setRun = (i: number, next: Partial<RunValues>) => put({ runs: v.runs.map((x, n) => (n === i ? { ...x, ...next } : x)) });
  const o = r.options;
  return (
    <>
      <p>
        <strong>
          {r.section} {r.section_name} · {r.shift_name} · {r.day}
        </strong>{" "}
        — {r.status_label}
      </p>
      {edit && <p className="muted small">{t("shiftReport.closes", { at: new Date(r.closes_at).toLocaleString() })}</p>}
      {r.return_reason && r.status === "returned" && <p className="notice">{t("shiftReport.returned", { reason: r.return_reason })}</p>}
      {r.approved_by && r.status === "approved" && <p className="notice">{t("shiftReport.approvedBy", { name: r.approved_by })}</p>}
      {r.section_type === "machining" && (
        <JobCards report={r} rows={v.operations} edit={edit} fresh={values === null} onChange={(operations) => put({ operations })} />
      )}
      {r.section_type !== "machining" && edit && o.plan.length > 0 && (
        <section className="panel" aria-label={t("shiftReport.plan")}>
          <h2>{t("shiftReport.plan")}</h2>
          {o.plan.map((p) => (
            <p key={p.id}>
              {t("shiftReport.planLine", {
                machine: p.machine,
                order: p.order_number,
                item: p.item,
                mould: p.mould,
                quantity: formatDecimal(p.quantity),
              })}{" "}
              <button
                type="button"
                className="secondary"
                onClick={() => put({ runs: [...v.runs, { ...NEW_RUN, machine: p.machine, order: p.order, plan_entry: p.id }] })}
              >
                {t("shiftReport.enterRun")}
              </button>
            </p>
          ))}
        </section>
      )}
      <section className="panel" aria-label={t("shiftReport.runs")} hidden={r.section_type === "machining"}>
        <h2>{t("shiftReport.runs")}</h2>
        {v.runs.map((x, i) => {
          const saved = r.runs[i];
          const label = t("shiftReport.run", { n: i + 1 });
          return (
            <fieldset key={i} className="run-card" aria-label={label} disabled={!edit}>
              <legend>{label}</legend>
              <div className="form-grid">
                <label>
                  {t("shiftReport.machine")}
                  <select value={x.machine} onChange={(e) => setRun(i, { machine: e.target.value })}>
                    <option value="">{t("shiftReport.choose")}</option>
                    {o.machines.map((m) => (
                      <option key={m.code} value={m.code}>
                        {m.code} {m.name}
                      </option>
                    ))}
                  </select>
                </label>
                <ScanButton
                  label={t("shiftReport.scanMachine", { n: i + 1 })}
                  onScan={(code) => setRun(i, { machine: code.toUpperCase() })}
                />
                <label>
                  {t("shiftReport.order")}
                  <select value={x.order} onChange={(e) => setRun(i, { order: Number(e.target.value) || "" })}>
                    <option value="">{t("shiftReport.choose")}</option>
                    {o.orders.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.number} {p.item} ({p.mould})
                      </option>
                    ))}
                  </select>
                </label>
                <ScanButton
                  label={t("shiftReport.scanMould", { n: i + 1 })}
                  onScan={(code) => {
                    const match = o.orders.find((p) => p.mould === code.toUpperCase());
                    if (match) setRun(i, { order: match.id });
                  }}
                />
                <label>
                  {t("shiftReport.batch")}
                  <input value={x.material_lot} onChange={(e) => setRun(i, { material_lot: e.target.value })} />
                </label>
                <ScanButton label={t("shiftReport.scanBatch", { n: i + 1 })} onScan={(code) => setRun(i, { material_lot: code })} />
                <label>
                  {t("shiftReport.operator")}
                  <select value={x.operator} onChange={(e) => setRun(i, { operator: e.target.value })}>
                    <option value="">{t("shiftReport.choose")}</option>
                    {o.operators.map((p) => (
                      <option key={p.number} value={p.number}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  {t("shiftReport.startTime")}
                  <input type="time" value={x.start_time} onChange={(e) => setRun(i, { start_time: e.target.value })} />
                </label>
                <label>
                  {t("shiftReport.end")}
                  <input type="time" value={x.end_time} onChange={(e) => setRun(i, { end_time: e.target.value })} />
                </label>
                <label>
                  {t("shiftReport.counterStart")}
                  <input inputMode="numeric" value={x.start_counter} onChange={(e) => setRun(i, { start_counter: e.target.value })} />
                </label>
                <label>
                  {t("shiftReport.counterEnd")}
                  <input inputMode="numeric" value={x.end_counter} onChange={(e) => setRun(i, { end_counter: e.target.value })} />
                </label>
              </div>
              <h3>{t("shiftReport.rejects")}</h3>
              {x.rejects.map((j, k) => (
                <div key={k} className="inline-form">
                  <label>
                    {t("shiftReport.reason")}
                    <select
                      value={j.reason}
                      onChange={(e) => setRun(i, { rejects: x.rejects.map((y, m) => (m === k ? { ...y, reason: e.target.value } : y)) })}
                    >
                      <option value="">{t("shiftReport.choose")}</option>
                      {o.reject_reasons.map((c) => (
                        <option key={c.code} value={c.code}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    {t("shiftReport.pieces")}
                    <input
                      inputMode="numeric"
                      value={j.quantity}
                      onChange={(e) => setRun(i, { rejects: x.rejects.map((y, m) => (m === k ? { ...y, quantity: e.target.value } : y)) })}
                    />
                  </label>
                  {edit && (
                    <button type="button" className="secondary" onClick={() => setRun(i, { rejects: x.rejects.filter((_, m) => m !== k) })}>
                      {t("shiftReport.remove")}
                    </button>
                  )}
                </div>
              ))}
              {edit && (
                <div className="row-actions">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setRun(i, { rejects: [...x.rejects, { reason: "", quantity: "" }] })}
                  >
                    {t("shiftReport.addReject")}
                  </button>
                  <button type="button" className="secondary" onClick={() => put({ runs: v.runs.filter((_, n) => n !== i) })}>
                    {t("shiftReport.removeRun")}
                  </button>
                </div>
              )}
              {saved && values === null && (
                <p className="notice">
                  {t("shiftReport.worked", {
                    shots: formatDecimal(String(saved.shots)),
                    cavities: saved.cavities,
                    good: formatDecimal(saved.good_quantity),
                    cycle: saved.actual_cycle_s || "—",
                    standard: saved.standard_cycle_s,
                  })}
                  {saved.planned_quantity && ` ${t("shiftReport.plannedWas", { planned: formatDecimal(saved.planned_quantity) })}`}
                </p>
              )}
            </fieldset>
          );
        })}
        {edit && (
          <button type="button" className="secondary" onClick={() => put({ runs: [...v.runs, { ...NEW_RUN }] })}>
            {t("shiftReport.addRun")}
          </button>
        )}
      </section>
      <Downtime report={r} rows={v.downtime} edit={edit} onChange={(downtime) => put({ downtime })} />
      {r.section_type !== "machining" && <Materials rows={v.materials} edit={edit} onChange={(materials) => put({ materials })} />}
      <Manpower report={r} rows={v.manpower} edit={edit} onChange={(manpower) => put({ manpower })} />
      <section className="panel" aria-label={t("shiftReport.summary")}>
        <h2>{t("shiftReport.summary")}</h2>
        <Totals report={r} />
        <label className="wide">
          {t("shiftReport.notes")}
          <textarea value={v.notes} disabled={!edit} onChange={(e) => put({ notes: e.target.value })} />
        </label>
        {values !== null && !pending && <p className="notice">{t("shiftReport.unsaved")}</p>}
        <SyncStatus
          online={online}
          pending={pending}
          copyAt={copyAt}
          sending={send.isPending}
          sendError={send.isError && isNetworkError(send.error)}
          onSend={() => send.mutate(false)}
        />
        {conflict && pending && (
          <Conflict
            mine={pending.values}
            theirs={conflict}
            busy={send.isPending}
            onKeepMine={() => send.mutate(true)}
            onKeepTheirs={() => {
              clearPending(id);
              done(conflict);
            }}
          />
        )}
        <div className="row-actions">
          {edit && (
            <>
              <button type="button" disabled={save.isPending || submit.isPending} onClick={() => save.mutate(v)}>
                {t("shiftReport.save")}
              </button>
              <button
                type="button"
                disabled={save.isPending || submit.isPending || !online || pending !== null || copyAt !== null}
                onClick={() => submit.mutate(v)}
              >
                {t("shiftReport.submit")}
              </button>
            </>
          )}
          <button type="button" className="secondary" onClick={onBack}>
            {t("shiftReport.back")}
          </button>
        </div>
        <ErrorLine error={(save.error && !isNetworkError(save.error) && !conflict ? save.error : null) ?? submit.error} />
      </section>
      <Approval report={r} onDone={done} />
    </>
  );
}

/** P3-09: the Production Manager's decision, what approval put into stock, and corrections. */
function Approval({ report, onDone }: { report: ShiftReport; onDone: (r: ShiftReport) => void }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const [ask, setAsk] = useState("");
  const decide = useMutation({
    mutationFn: (action: "approve" | "send_back") => decideReport(report.id, action, reason),
    onSuccess: (r) => {
      setReason("");
      onDone(r);
    },
  });
  const request = useMutation({
    mutationFn: () => askCorrection(report.id, ask),
    onSuccess: (r) => {
      setAsk("");
      onDone(r);
    },
  });
  const fix = useMutation({
    mutationFn: ({ id, action }: { id: number; action: "approve" | "reject" }) => decideCorrection(id, action, reason),
    onSuccess: (r) => {
      setReason("");
      onDone(r);
    },
  });
  const pending = report.corrections.find((c) => c.can_decide);
  return (
    <>
      {report.can_decide && (
        <section className="panel" aria-label={t("shiftReport.decision")}>
          <h2>{t("shiftReport.decision")}</h2>
          <p className="muted">{t("shiftReport.decisionHelp")}</p>
          <label className="wide">
            {t("shiftReport.reasonOrComment")}
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div className="row-actions">
            <button type="button" disabled={decide.isPending} onClick={() => decide.mutate("approve")}>
              {t("shiftReport.approve")}
            </button>
            <button type="button" className="secondary" disabled={decide.isPending} onClick={() => decide.mutate("send_back")}>
              {t("shiftReport.sendBack")}
            </button>
          </div>
          <ErrorLine error={decide.error} />
        </section>
      )}
      {report.receipts.length > 0 && (
        <section className="panel" aria-label={t("shiftReport.intoStock")}>
          <h2>{t("shiftReport.intoStock")}</h2>
          {report.stock_issue && <p className="muted">{t("shiftReport.backflush", { number: report.stock_issue })}</p>}
          <div className="table-wrap">
            <table aria-label={t("shiftReport.intoStock")}>
              <thead>
                <tr>
                  <th>{t("shiftReport.item")}</th>
                  <th className="num">{t("shiftReport.quantity")}</th>
                  <th className="num">{t("shiftReport.materialValue")}</th>
                  <th className="num">{t("shiftReport.regrindCredit")}</th>
                  <th className="num">{t("shiftReport.value")}</th>
                </tr>
              </thead>
              <tbody>
                {report.receipts.map((x, i) => (
                  <tr key={i} className={x.undone ? "muted" : undefined}>
                    <td>
                      {x.item} {x.is_regrind ? t("shiftReport.regrindLabel") : x.order}
                      {x.undone && ` ${t("shiftReport.undone")}`}
                    </td>
                    <td className="num">{formatDecimal(x.quantity)}</td>
                    <td className="num">{formatDecimal(x.material_value)}</td>
                    <td className="num">{formatDecimal(x.regrind_credit)}</td>
                    <td className="num">{formatDecimal(x.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {(report.corrections.length > 0 || report.can_ask) && (
        <section className="panel" aria-label={t("shiftReport.corrections")}>
          <h2>{t("shiftReport.corrections")}</h2>
          {report.corrections.map((c) => (
            <p key={c.id}>{t("shiftReport.correctionLine", { reason: c.reason, by: c.requested_by, status: c.status_label })}</p>
          ))}
          {pending && (
            <>
              <label className="wide">
                {t("shiftReport.reasonOrComment")}
                <input value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
              <div className="row-actions">
                <button type="button" disabled={fix.isPending} onClick={() => fix.mutate({ id: pending.id, action: "approve" })}>
                  {t("shiftReport.approveCorrection")}
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={fix.isPending}
                  onClick={() => fix.mutate({ id: pending.id, action: "reject" })}
                >
                  {t("shiftReport.rejectCorrection")}
                </button>
              </div>
              <p className="muted small">{t("shiftReport.correctionHelp")}</p>
            </>
          )}
          {report.can_ask && (
            <div className="inline-form">
              <label>
                {t("shiftReport.whatToCorrect")}
                <input value={ask} onChange={(e) => setAsk(e.target.value)} />
              </label>
              <button type="button" disabled={request.isPending} onClick={() => request.mutate()}>
                {t("shiftReport.askCorrection")}
              </button>
            </div>
          )}
          <ErrorLine error={request.error ?? fix.error} />
        </section>
      )}
    </>
  );
}

function Totals({ report }: { report: ShiftReport }) {
  const { t } = useTranslation();
  const s = report.summary;
  if (report.section_type === "machining") {
    const m = s.machining;
    return (
      <ul>
        <li>
          {t("shiftReport.jobTotals", {
            completed: formatDecimal(m.completed),
            rejected: formatDecimal(m.rejected),
            rework: formatDecimal(m.rework),
            minutes: m.minutes,
          })}
        </li>
        <li>{t("shiftReport.totalDowntime", { minutes: s.downtime_minutes })}</li>
        <li>{t("shiftReport.totalPeople", { people: s.people, overtime: s.overtime_hours })}</li>
      </ul>
    );
  }
  return (
    <ul>
      <li>
        {t("shiftReport.totalGood", {
          good: formatDecimal(s.good),
          made: formatDecimal(String(s.made)),
          shots: formatDecimal(String(s.shots)),
        })}
      </li>
      <li>{t("shiftReport.totalRejects", { rejects: formatDecimal(String(s.rejects)), pct: s.reject_pct })}</li>
      <li>{t("shiftReport.totalDowntime", { minutes: s.downtime_minutes })}</li>
      {s.material.map((m) => (
        <li key={m.item}>
          {t("shiftReport.materialUsed", { item: m.item, used: formatDecimal(m.used), unit: m.unit, grams: m.grams_per_good || "—" })}
        </li>
      ))}
      <li>{t("shiftReport.totalRegrind", { regrind: formatDecimal(s.regrind) })}</li>
      <li>{t("shiftReport.totalPeople", { people: s.people, overtime: s.overtime_hours })}</li>
    </ul>
  );
}

function Downtime({
  report,
  rows,
  edit,
  onChange,
}: {
  report: ShiftReport;
  rows: DowntimeValues[];
  edit: boolean;
  onChange: (rows: DowntimeValues[]) => void;
}) {
  const { t } = useTranslation();
  const set = (i: number, next: Partial<DowntimeValues>) => onChange(rows.map((x, n) => (n === i ? { ...x, ...next } : x)));
  return (
    <section className="panel" aria-label={t("shiftReport.downtime")}>
      <h2>{t("shiftReport.downtime")}</h2>
      {rows.map((x, i) => (
        <fieldset key={i} className="run-card" disabled={!edit} aria-label={t("shiftReport.stop", { n: i + 1 })}>
          <div className="form-grid">
            <label>
              {t("shiftReport.machine")}
              <select value={x.machine} onChange={(e) => set(i, { machine: e.target.value })}>
                <option value="">{t("shiftReport.choose")}</option>
                {report.options.machines.map((m) => (
                  <option key={m.code} value={m.code}>
                    {m.code}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("shiftReport.reason")}
              <select value={x.reason} onChange={(e) => set(i, { reason: e.target.value })}>
                <option value="">{t("shiftReport.choose")}</option>
                {report.options.downtime_reasons.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("shiftReport.from")}
              <input type="time" value={x.start_time} onChange={(e) => set(i, { start_time: e.target.value })} />
            </label>
            <label>
              {t("shiftReport.to")}
              <input type="time" value={x.end_time} onChange={(e) => set(i, { end_time: e.target.value })} />
            </label>
            <label className="wide">
              {t("shiftReport.remarks")}
              <input value={x.remarks} onChange={(e) => set(i, { remarks: e.target.value })} />
            </label>
          </div>
          {edit && (
            <button type="button" className="secondary" onClick={() => onChange(rows.filter((_, n) => n !== i))}>
              {t("shiftReport.remove")}
            </button>
          )}
        </fieldset>
      ))}
      {edit && (
        <button
          type="button"
          className="secondary"
          onClick={() => onChange([...rows, { machine: "", reason: "", start_time: "", end_time: "", remarks: "" }])}
        >
          {t("shiftReport.addDowntime")}
        </button>
      )}
    </section>
  );
}

function Materials({ rows, edit, onChange }: { rows: MaterialValues[]; edit: boolean; onChange: (rows: MaterialValues[]) => void }) {
  const { t } = useTranslation();
  const set = (i: number, next: Partial<MaterialValues>) => onChange(rows.map((x, n) => (n === i ? { ...x, ...next } : x)));
  return (
    <section className="panel" aria-label={t("shiftReport.materials")}>
      <h2>{t("shiftReport.materials")}</h2>
      {rows.map((x, i) => (
        <fieldset key={i} className="run-card" disabled={!edit} aria-label={t("shiftReport.materialLine", { n: i + 1 })}>
          <div className="form-grid">
            <label>
              {t("shiftReport.kind")}
              <select value={x.kind} onChange={(e) => set(i, { kind: e.target.value as MaterialValues["kind"] })}>
                <option value="issue">{t("shiftReport.kinds.issue")}</option>
                <option value="return">{t("shiftReport.kinds.return")}</option>
                <option value="regrind">{t("shiftReport.kinds.regrind")}</option>
              </select>
            </label>
            {x.kind === "regrind" ? (
              <label>
                {t("shiftReport.material")}
                <input value={x.item} onChange={(e) => set(i, { item: e.target.value })} />
              </label>
            ) : (
              <>
                <label>
                  {t("shiftReport.batch")}
                  <input value={x.lot_no} onChange={(e) => set(i, { lot_no: e.target.value })} />
                </label>
                <ScanButton label={t("shiftReport.scanLine", { n: i + 1 })} onScan={(code) => set(i, { lot_no: code })} />
              </>
            )}
            <label>
              {t("shiftReport.kg")}
              <input inputMode="decimal" value={x.quantity} onChange={(e) => set(i, { quantity: e.target.value })} />
            </label>
          </div>
          {edit && (
            <button type="button" className="secondary" onClick={() => onChange(rows.filter((_, n) => n !== i))}>
              {t("shiftReport.remove")}
            </button>
          )}
        </fieldset>
      ))}
      {edit && (
        <button
          type="button"
          className="secondary"
          onClick={() => onChange([...rows, { kind: "issue", item: "", lot_no: "", quantity: "" }])}
        >
          {t("shiftReport.addMaterial")}
        </button>
      )}
    </section>
  );
}

function Manpower({
  report,
  rows,
  edit,
  onChange,
}: {
  report: ShiftReport;
  rows: ManpowerValues[];
  edit: boolean;
  onChange: (rows: ManpowerValues[]) => void;
}) {
  const { t } = useTranslation();
  const set = (i: number, next: Partial<ManpowerValues>) => onChange(rows.map((x, n) => (n === i ? { ...x, ...next } : x)));
  return (
    <section className="panel" aria-label={t("shiftReport.manpower")}>
      <h2>{t("shiftReport.manpower")}</h2>
      {rows.map((x, i) => (
        <div key={i} className="inline-form" aria-label={t("shiftReport.manpowerLine", { n: i + 1 })}>
          <label>
            {t("shiftReport.machine")}
            <select value={x.machine} disabled={!edit} onChange={(e) => set(i, { machine: e.target.value })}>
              <option value="">{t("shiftReport.wholeSection")}</option>
              {report.options.machines.map((m) => (
                <option key={m.code} value={m.code}>
                  {m.code}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("shiftReport.people")}
            <input inputMode="numeric" value={x.people} disabled={!edit} onChange={(e) => set(i, { people: e.target.value })} />
          </label>
          <label>
            {t("shiftReport.overtime")}
            <input
              inputMode="decimal"
              value={x.overtime_hours}
              disabled={!edit}
              onChange={(e) => set(i, { overtime_hours: e.target.value })}
            />
          </label>
          {edit && (
            <button type="button" className="secondary" onClick={() => onChange(rows.filter((_, n) => n !== i))}>
              {t("shiftReport.remove")}
            </button>
          )}
        </div>
      ))}
      {edit && (
        <button type="button" className="secondary" onClick={() => onChange([...rows, { machine: "", people: "", overtime_hours: "0" }])}>
          {t("shiftReport.addManpower")}
        </button>
      )}
    </section>
  );
}

const NEW_WORK: JobWorkValues = {
  job: "",
  operation: "",
  machine: "",
  operator: "",
  start_time: "",
  end_time: "",
  completed: "",
  rework: "",
  setup: false,
  notes: "",
  rejects: [],
};

/** P3-12: the supervisor scans each job card and enters the work done on it. */
function JobCards({
  report,
  rows,
  edit,
  fresh,
  onChange,
}: {
  report: ShiftReport;
  rows: JobWorkValues[];
  edit: boolean;
  fresh: boolean;
  onChange: (rows: JobWorkValues[]) => void;
}) {
  const { t } = useTranslation();
  const o = report.options;
  const set = (i: number, next: Partial<JobWorkValues>) => onChange(rows.map((x, n) => (n === i ? { ...x, ...next } : x)));
  const scanned = (i: number, code: string) => {
    const [job, op] = code.trim().toUpperCase().split("/");
    const found = o.jobs.find((j) => j.number === job);
    const step = found?.operations.find((x) => String(x.seq) === op);
    set(i, { job: job ?? "", operation: op ?? "", machine: rows[i].machine || step?.machine || "" });
  };
  return (
    <section className="panel" aria-label={t("shiftReport.jobCards")}>
      <h2>{t("shiftReport.jobCards")}</h2>
      <p className="muted small">{t("shiftReport.jobCardsHelp")}</p>
      {rows.map((x, i) => {
        const label = t("shiftReport.work", { n: i + 1 });
        const job = o.jobs.find((j) => j.number === x.job);
        const step = job?.operations.find((s) => String(s.seq) === x.operation);
        const saved = fresh ? report.operations[i] : undefined;
        return (
          <fieldset key={i} className="run-card" aria-label={label} disabled={!edit}>
            <legend>{label}</legend>
            <div className="form-grid">
              <ScanButton label={t("shiftReport.scanCard", { n: i + 1 })} onScan={(code) => scanned(i, code)} />
              <label>
                {t("shiftReport.job")}
                <select value={x.job} onChange={(e) => set(i, { job: e.target.value, operation: "" })}>
                  <option value="">{t("shiftReport.choose")}</option>
                  {o.jobs.map((j) => (
                    <option key={j.id} value={j.number}>
                      {j.number} {j.item} {j.description}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("shiftReport.operation")}
                <select value={x.operation} onChange={(e) => set(i, { operation: e.target.value })}>
                  <option value="">{t("shiftReport.choose")}</option>
                  {job?.operations.map((s) => (
                    <option key={s.seq} value={String(s.seq)}>
                      {t("shiftReport.operationOption", { seq: s.seq, name: s.name, in_hand: formatDecimal(s.in_hand) })}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("shiftReport.machine")}
                <select value={x.machine} onChange={(e) => set(i, { machine: e.target.value })}>
                  <option value="">{t("shiftReport.choose")}</option>
                  {o.machines.map((m) => (
                    <option key={m.code} value={m.code}>
                      {m.code} {m.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("shiftReport.operator")}
                <select value={x.operator} onChange={(e) => set(i, { operator: e.target.value })}>
                  <option value="">{t("shiftReport.choose")}</option>
                  {o.operators.map((p) => (
                    <option key={p.number} value={p.number}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("shiftReport.startTime")}
                <input type="time" value={x.start_time} onChange={(e) => set(i, { start_time: e.target.value })} />
              </label>
              <label>
                {t("shiftReport.end")}
                <input type="time" value={x.end_time} onChange={(e) => set(i, { end_time: e.target.value })} />
              </label>
              <label>
                {t("shiftReport.completed")}
                <input inputMode="decimal" value={x.completed} onChange={(e) => set(i, { completed: e.target.value })} />
              </label>
              <label>
                {t("shiftReport.rework")}
                <input inputMode="decimal" value={x.rework} onChange={(e) => set(i, { rework: e.target.value })} />
              </label>
              <label className="check">
                <input type="checkbox" checked={x.setup} onChange={(e) => set(i, { setup: e.target.checked })} />
                {t("shiftReport.setup")}
              </label>
            </div>
            {step && <p className="muted small">{t("shiftReport.standard", { minutes: formatDecimal(step.run_min) })}</p>}
            <h3>{t("shiftReport.rejects")}</h3>
            {x.rejects.map((j, k) => (
              <div key={k} className="inline-form">
                <label>
                  {t("shiftReport.reason")}
                  <select
                    value={j.reason}
                    onChange={(e) => set(i, { rejects: x.rejects.map((y, m) => (m === k ? { ...y, reason: e.target.value } : y)) })}
                  >
                    <option value="">{t("shiftReport.choose")}</option>
                    {o.reject_reasons.map((c) => (
                      <option key={c.code} value={c.code}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  {t("shiftReport.pieces")}
                  <input
                    inputMode="decimal"
                    value={j.quantity}
                    onChange={(e) => set(i, { rejects: x.rejects.map((y, m) => (m === k ? { ...y, quantity: e.target.value } : y)) })}
                  />
                </label>
                {edit && (
                  <button type="button" className="secondary" onClick={() => set(i, { rejects: x.rejects.filter((_, m) => m !== k) })}>
                    {t("shiftReport.remove")}
                  </button>
                )}
              </div>
            ))}
            {edit && (
              <div className="row-actions">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => set(i, { rejects: [...x.rejects, { reason: "", quantity: "" }] })}
                >
                  {t("shiftReport.addReject")}
                </button>
                <button type="button" className="secondary" onClick={() => onChange(rows.filter((_, n) => n !== i))}>
                  {t("shiftReport.removeWork")}
                </button>
              </div>
            )}
            {saved && (
              <p className="notice">
                {t("shiftReport.workWorked", {
                  minutes: saved.minutes_per_piece ? formatDecimal(saved.minutes_per_piece) : "—",
                  standard: formatDecimal(saved.standard_minutes),
                })}
              </p>
            )}
          </fieldset>
        );
      })}
      {edit && (
        <button type="button" className="secondary" onClick={() => onChange([...rows, { ...NEW_WORK, rejects: [] }])}>
          {t("shiftReport.addWork")}
        </button>
      )}
    </section>
  );
}

/** P3-21: whether what is on the screen has reached the server. */
function SyncStatus(props: {
  online: boolean;
  pending: PendingSave | null;
  copyAt: string | null;
  sending: boolean;
  sendError: boolean;
  onSend: () => void;
}) {
  const { t } = useTranslation();
  const { online, pending, copyAt, sending } = props;
  if (online && !pending && !copyAt) return null;
  return (
    <div className="notice sync-status" role="status">
      {!online && <p>{t("shiftReport.offline")}</p>}
      {copyAt && <p>{t("shiftReport.fromCopy", { at: timeOf(copyAt) })}</p>}
      {pending && <p>{sending ? t("shiftReport.sending") : t("shiftReport.keptOnPhone", { at: timeOf(pending.savedAt) })}</p>}
      {pending && props.sendError && <p>{t("shiftReport.sendFailed")}</p>}
      {pending && online && !sending && (
        <button type="button" className="secondary small" onClick={props.onSend}>
          {t("shiftReport.sendNow")}
        </button>
      )}
    </div>
  );
}

function counts(values: ReportValues) {
  return { runs: values.runs.length, cards: values.operations.length, stops: values.downtime.length, lines: values.materials.length };
}

/** P3-21: the report was saved elsewhere after the copy the phone's save was made on. */
function Conflict(props: { mine: ReportValues; theirs: ShiftReport; busy: boolean; onKeepMine: () => void; onKeepTheirs: () => void }) {
  const { t } = useTranslation();
  const theirs = valuesOf(props.theirs);
  const rows: [string, ReportValues][] = [
    [t("shiftReport.conflictMine"), props.mine],
    [t("shiftReport.conflictTheirs"), theirs],
  ];
  return (
    <section className="panel notice" role="alert" aria-label={t("shiftReport.conflictTitle")}>
      <h3>{t("shiftReport.conflictTitle")}</h3>
      <p>{t("shiftReport.conflictHelp")}</p>
      <div className="table-wrap">
        <table aria-label={t("shiftReport.conflictTitle")}>
          <thead>
            <tr>
              <th />
              <th className="num">{t("shiftReport.runs")}</th>
              <th className="num">{t("shiftReport.jobCards")}</th>
              <th className="num">{t("shiftReport.downtime")}</th>
              <th className="num">{t("shiftReport.materials")}</th>
              <th>{t("shiftReport.notes")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, x]) => {
              const c = counts(x);
              return (
                <tr key={label}>
                  <th>{label}</th>
                  <td className="num">{c.runs}</td>
                  <td className="num">{c.cards}</td>
                  <td className="num">{c.stops}</td>
                  <td className="num">{c.lines}</td>
                  <td>{x.notes || "–"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="row-actions">
        <button type="button" disabled={props.busy} onClick={props.onKeepMine}>
          {t("shiftReport.keepMine")}
        </button>
        <button type="button" className="secondary" disabled={props.busy} onClick={props.onKeepTheirs}>
          {t("shiftReport.keepTheirs")}
        </button>
      </div>
    </section>
  );
}
