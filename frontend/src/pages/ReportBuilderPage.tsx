import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  builderKey,
  deleteReport,
  emailReport,
  getBuilder,
  reportEmailDraft,
  reportExportUrl,
  runReport,
  saveReport,
  type Builder,
  type Definition,
  type ReportResult,
} from "../api/reportBuilder";
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

const blank = (source: string): Definition => ({ source, columns: [], filters: [], group_by: null, sort: [], period: "", measure: null });

/** Custom report builder (P2-26): a data source or a ready-made report, its columns (dragged
 * into order), filters, grouping with subtotals, sort and period columns; saved, shared with
 * a role, exported and emailed. Each person sees only what their access allows. */
export default function ReportBuilderPage() {
  const { t } = useTranslation();
  const builder = useQuery({ queryKey: builderKey, queryFn: getBuilder });
  const [def, setDef] = useState<Definition | null>(null);
  const [name, setName] = useState("");
  const [savedId, setSavedId] = useState<number | undefined>(undefined);
  const [role, setRole] = useState("");
  const [result, setResult] = useState<ReportResult | null>(null);
  const run = useMutation({ mutationFn: (d: Definition) => runReport(d), onSuccess: setResult });
  const data = builder.data;

  const open = (d: Definition, title = "", id?: number, shared = "") => {
    setDef({ ...blank(d.source), ...d });
    setName(title);
    setSavedId(id);
    setRole(shared);
    setResult(null);
  };

  return (
    <main className="page">
      <h1>{t("rb.title")}</h1>
      <p className="muted">{t("rb.help")}</p>
      <ErrorLine error={builder.error} />
      {data && (
        <section className="panel" aria-label={t("rb.start")}>
          <h2>{t("rb.start")}</h2>
          <div className="inline-form">
            <label>
              {t("rb.source")}
              <select value="" onChange={(e) => e.target.value && open(blank(e.target.value))}>
                <option value="">{t("rb.chooseSource")}</option>
                {data.sources.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("rb.readyMade")}
              <select
                value=""
                onChange={(e) => {
                  const p = data.presets[Number(e.target.value)];
                  if (p) open(p.definition, p.name);
                }}
              >
                <option value="">{t("rb.chooseReport")}</option>
                {data.presets.map((p, i) => (
                  <option key={p.name} value={i}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {data.saved.length > 0 && (
            <ul className="changes" aria-label={t("rb.saved")}>
              {data.saved.map((s) => (
                <li key={s.id}>
                  <button type="button" className="link" onClick={() => open(s.definition, s.name, s.mine ? s.id : undefined, s.shared_role ?? "")}>
                    {s.name}
                  </button>{" "}
                  <span className="muted">
                    {s.mine ? (s.shared_role_name ? t("rb.sharedWith", { role: s.shared_role_name }) : t("rb.private")) : t("rb.sharedBy", { name: s.owner })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {data && def && (
        <Designer
          builder={data}
          def={def}
          setDef={setDef}
          name={name}
          setName={setName}
          role={role}
          setRole={setRole}
          savedId={savedId}
          onSaved={(id) => setSavedId(id)}
          onRun={() => run.mutate(def)}
          running={run.isPending}
        />
      )}
      <ErrorLine error={run.error} />
      {def && result && <Result result={result} def={def} name={name} />}
    </main>
  );
}

function Designer(props: {
  builder: Builder;
  def: Definition;
  setDef: (d: Definition) => void;
  name: string;
  setName: (n: string) => void;
  role: string;
  setRole: (r: string) => void;
  savedId: number | undefined;
  onSaved: (id: number | undefined) => void;
  onRun: () => void;
  running: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { builder, def, setDef } = props;
  const source = builder.sources.find((s) => s.key === def.source);
  const [dragged, setDragged] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => saveReport({ name: props.name, definition: def, shared_role: props.role }, props.savedId),
    onSuccess: (saved) => {
      props.onSaved(saved.id);
      void queryClient.invalidateQueries({ queryKey: builderKey });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteReport(props.savedId!),
    onSuccess: () => {
      props.onSaved(undefined);
      void queryClient.invalidateQueries({ queryKey: builderKey });
    },
  });
  if (!source) return null;
  const fields = source.fields;
  const label = (key: string) => fields.find((f) => f.key === key)?.label ?? key;
  const kindOf = (key: string) => fields.find((f) => f.key === key)?.kind ?? "text";
  const set = (change: Partial<Definition>) => setDef({ ...def, ...change });
  const move = (from: number, to: number) => {
    if (to < 0 || to >= def.columns.length) return;
    const next = [...def.columns];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    set({ columns: next });
  };
  const filters = def.filters ?? [];
  const amounts = fields.filter((f) => f.kind === "money" || f.kind === "number");

  return (
    <section className="panel" aria-label={t("rb.design")}>
      <h2>
        {t("rb.design")} · {source.label}
      </h2>

      <h3>{t("rb.columns")}</h3>
      <div className="picture-row">
        {fields.map((f) => (
          <label key={f.key}>
            <input
              type="checkbox"
              checked={def.columns.includes(f.key)}
              onChange={(e) => set({ columns: e.target.checked ? [...def.columns, f.key] : def.columns.filter((c) => c !== f.key) })}
            />{" "}
            {f.label}
          </label>
        ))}
      </div>
      {def.columns.length > 0 && (
        <>
          <p className="muted">{t("rb.dragHelp")}</p>
          <ol aria-label={t("rb.order")}>
            {def.columns.map((c, i) => (
              <li
                key={c}
                draggable
                onDragStart={() => setDragged(c)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => {
                  if (dragged) move(def.columns.indexOf(dragged), i);
                  setDragged(null);
                }}
                style={{ cursor: "grab" }}
              >
                ⠿ {label(c)}{" "}
                <button type="button" className="small secondary" aria-label={t("rb.up", { column: label(c) })} onClick={() => move(i, i - 1)}>
                  ↑
                </button>{" "}
                <button type="button" className="small secondary" aria-label={t("rb.down", { column: label(c) })} onClick={() => move(i, i + 1)}>
                  ↓
                </button>
              </li>
            ))}
          </ol>
        </>
      )}

      <h3>{t("rb.filters")}</h3>
      {filters.map((f, i) => (
        <div key={i} className="inline-form">
          <select aria-label={t("rb.filterField")} value={f.field} onChange={(e) => set({ filters: filters.map((x, j) => (j === i ? { ...x, field: e.target.value, op: Object.keys(builder.ops[kindOf(e.target.value)])[0] } : x)) })}>
            {fields.map((x) => (
              <option key={x.key} value={x.key}>
                {x.label}
              </option>
            ))}
          </select>
          <select aria-label={t("rb.filterOp")} value={f.op} onChange={(e) => set({ filters: filters.map((x, j) => (j === i ? { ...x, op: e.target.value } : x)) })}>
            {Object.keys(builder.ops[kindOf(f.field)]).map((op) => (
              <option key={op} value={op}>
                {t(`rb.ops.${op}`)}
              </option>
            ))}
          </select>
          <input
            aria-label={t("rb.filterValue")}
            type={kindOf(f.field) === "date" ? "date" : "text"}
            value={f.value}
            onChange={(e) => set({ filters: filters.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)) })}
          />
          <button type="button" className="small secondary" onClick={() => set({ filters: filters.filter((_, j) => j !== i) })}>
            {t("rb.remove")}
          </button>
        </div>
      ))}
      <button type="button" className="small secondary" onClick={() => set({ filters: [...filters, { field: fields[0].key, op: Object.keys(builder.ops[fields[0].kind])[0], value: "" }] })}>
        {t("rb.addFilter")}
      </button>

      <div className="form-grid">
        <label>
          {t("rb.groupBy")}
          <select value={def.group_by ?? ""} onChange={(e) => set({ group_by: e.target.value || null })}>
            <option value="">{t("rb.noGrouping")}</option>
            {fields
              .filter((f) => f.kind === "text" || f.kind === "date")
              .map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
          </select>
        </label>
        <label>
          {t("rb.sortBy")}
          <select value={def.sort?.[0]?.field ?? ""} onChange={(e) => set({ sort: e.target.value ? [{ field: e.target.value, desc: def.sort?.[0]?.desc ?? false }] : [] })}>
            <option value="">{t("rb.noSort")}</option>
            {fields.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input type="checkbox" checked={def.sort?.[0]?.desc ?? false} disabled={!def.sort?.length} onChange={(e) => set({ sort: def.sort?.length ? [{ ...def.sort[0], desc: e.target.checked }] : [] })} />{" "}
          {t("rb.descending")}
        </label>
        <label>
          {t("rb.period")}
          <select value={def.period ?? ""} onChange={(e) => set({ period: e.target.value as Definition["period"], measure: e.target.value ? (def.measure ?? amounts[0]?.key ?? null) : null })}>
            <option value="">{t("rb.noPeriod")}</option>
            <option value="month">{t("rb.byMonth")}</option>
            <option value="division">{t("rb.byDivision")}</option>
          </select>
        </label>
        {def.period && (
          <label>
            {t("rb.measure")}
            <select value={def.measure ?? ""} onChange={(e) => set({ measure: e.target.value })}>
              {amounts.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className="row-actions">
        <button type="button" disabled={props.running || def.columns.length === 0} onClick={props.onRun}>
          {t("rb.run")}
        </button>
      </div>

      <h3>{t("rb.saveTitle")}</h3>
      <div className="inline-form">
        <input aria-label={t("rb.name")} placeholder={t("rb.name")} value={props.name} onChange={(e) => props.setName(e.target.value)} />
        <select aria-label={t("rb.share")} value={props.role} onChange={(e) => props.setRole(e.target.value)}>
          <option value="">{t("rb.private")}</option>
          {builder.roles.map((r) => (
            <option key={r.code} value={r.code}>
              {t("rb.sharedWith", { role: r.name })}
            </option>
          ))}
        </select>
        <button type="button" disabled={save.isPending} onClick={() => save.mutate()}>
          {props.savedId ? t("rb.update") : t("rb.save")}
        </button>
        {props.savedId && (
          <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {t("rb.delete")}
          </button>
        )}
      </div>
      {save.isSuccess && <p role="status">{t("rb.savedOk")}</p>}
      <ErrorLine error={save.error ?? remove.error} />
    </section>
  );
}

function Result({ result, def, name }: { result: ReportResult; def: Definition; name: string }) {
  const { t } = useTranslation();
  const [mailOpen, setMailOpen] = useState(false);
  const [message, setMessage] = useState({ to: "", subject: "", body: "" });
  const draft = useMutation({
    mutationFn: () => reportEmailDraft(name || "Report"),
    onSuccess: (got) => {
      setMessage({ to: "", subject: got.subject, body: got.body });
      setMailOpen(true);
    },
  });
  const send = useMutation({
    mutationFn: () =>
      emailReport({
        definition: def,
        name: name || "Report",
        to: message.to.split(/[,;]/).map((a) => a.trim()).filter(Boolean),
        cc: [],
        subject: message.subject,
        body: message.body,
      }),
    onSuccess: () => setMailOpen(false),
  });
  const show = (kind: string, value: string | undefined) => (kind === "money" ? formatDecimal(value) : (value ?? ""));
  return (
    <section className="panel" aria-label={t("rb.result")}>
      <h2>
        {name || t("rb.result")}{" "}
        <a className="button-link secondary small" href={reportExportUrl(def, "xlsx", name)}>
          Excel
        </a>{" "}
        <a className="button-link secondary small" href={reportExportUrl(def, "pdf", name)}>
          PDF
        </a>{" "}
        <button type="button" className="small secondary" onClick={() => draft.mutate()}>
          {t("rb.email")}
        </button>
      </h2>
      {result.truncated && <p className="notice">{t("rb.truncated", { count: String(result.count) })}</p>}
      {mailOpen && (
        <div className="form-grid">
          <label className="wide">
            {t("rb.emailTo")}
            <input value={message.to} onChange={(e) => setMessage({ ...message, to: e.target.value })} />
          </label>
          <label className="wide">
            {t("rb.emailSubject")}
            <input value={message.subject} onChange={(e) => setMessage({ ...message, subject: e.target.value })} />
          </label>
          <label className="wide">
            {t("rb.emailBody")}
            <textarea rows={5} value={message.body} onChange={(e) => setMessage({ ...message, body: e.target.value })} />
          </label>
          <div className="wide">
            <button type="button" disabled={send.isPending} onClick={() => send.mutate()}>
              {t("rb.send")}
            </button>
          </div>
        </div>
      )}
      {send.isSuccess && <p role="status">{t("rb.sent")}</p>}
      <ErrorLine error={draft.error ?? send.error} />
      <div className="table-wrap">
        <table aria-label={t("rb.result")}>
          <thead>
            <tr>
              {result.columns.map((c) => (
                <th key={c.key} className={c.kind === "money" || c.kind === "number" ? "num" : undefined}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.rows.map((r, i) => (
              <tr key={i} className={r.kind !== "line" ? "total" : undefined}>
                {result.columns.map((c) => (
                  <td key={c.key} className={c.kind === "money" || c.kind === "number" ? "num" : undefined}>
                    {r.kind === "line" ? show(c.kind, r.cells[c.key]) : <strong>{show(c.kind, r.cells[c.key])}</strong>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
