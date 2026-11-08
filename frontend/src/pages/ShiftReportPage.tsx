import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import {
  getReport,
  getReports,
  openReport,
  reportsKey,
  saveReport,
  submitReport,
  type DowntimeValues,
  type ManpowerValues,
  type MaterialValues,
  type ReportValues,
  type RunValues,
  type ShiftReport,
} from "../api/shiftReports";
import ScanButton from "../components/ScanButton";
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

/** P3-08: the supervisor's moulding shift report, made for phones and tablets. */
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
  const found = useQuery({ queryKey: key, queryFn: () => getReport(id) });
  const [values, setValues] = useState<ReportValues | null>(null);
  const r = found.data;
  const v = values ?? (r ? valuesOf(r) : null);
  const done = (d: ShiftReport) => {
    queryClient.setQueryData(key, d);
    queryClient.invalidateQueries({ queryKey: reportsKey });
    setValues(null);
  };
  const save = useMutation({ mutationFn: (x: ReportValues) => saveReport(id, x), onSuccess: done });
  const submit = useMutation({
    mutationFn: async (x: ReportValues) => {
      await saveReport(id, x);
      return submitReport(id);
    },
    onSuccess: done,
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
      {edit && o.plan.length > 0 && (
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
      <section className="panel" aria-label={t("shiftReport.runs")}>
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
      <Materials rows={v.materials} edit={edit} onChange={(materials) => put({ materials })} />
      <Manpower report={r} rows={v.manpower} edit={edit} onChange={(manpower) => put({ manpower })} />
      <section className="panel" aria-label={t("shiftReport.summary")}>
        <h2>{t("shiftReport.summary")}</h2>
        <Totals report={r} />
        <label className="wide">
          {t("shiftReport.notes")}
          <textarea value={v.notes} disabled={!edit} onChange={(e) => put({ notes: e.target.value })} />
        </label>
        {values !== null && <p className="notice">{t("shiftReport.unsaved")}</p>}
        <div className="row-actions">
          {edit && (
            <>
              <button type="button" disabled={save.isPending || submit.isPending} onClick={() => save.mutate(v)}>
                {t("shiftReport.save")}
              </button>
              <button type="button" disabled={save.isPending || submit.isPending} onClick={() => submit.mutate(v)}>
                {t("shiftReport.submit")}
              </button>
            </>
          )}
          <button type="button" className="secondary" onClick={onBack}>
            {t("shiftReport.back")}
          </button>
        </div>
        <ErrorLine error={save.error ?? submit.error} />
      </section>
    </>
  );
}

function Totals({ report }: { report: ShiftReport }) {
  const { t } = useTranslation();
  const s = report.summary;
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
