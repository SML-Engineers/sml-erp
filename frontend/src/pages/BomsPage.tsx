import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import {
  addBom,
  bomAction,
  bomExportUrl,
  bomsKey,
  changeBom,
  compareBoms,
  deleteBom,
  getBoms,
  importBoms,
  whereUsed,
  type Bom,
  type BomLine,
  type BomList,
  type BomOutput,
  type BomValues,
  type Comparison,
  type WhereUsed,
} from "../api/boms";
import { ApiError } from "../api/client";
import { formatDecimal } from "../lib/decimal";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  const extra = error instanceof ApiError ? (((error.body as { errors?: string[] }) ?? {}).errors ?? []) : [];
  return (
    <div className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
      {extra.map((line) => (
        <div key={line}>{line}</div>
      ))}
    </div>
  );
}

const BLANK_LINE: BomLine = {
  seq: "",
  line_type: "raw",
  component: "",
  description: "",
  supplier: "",
  quantity: "",
  scrap_pct: "",
  pct_of_resin: "",
  operation_seq: "",
  issue_method: "",
  customer_supplied: false,
  unit_cost: "",
  stock_size: "",
  bar_length_mm: "",
  cut_length_mm: "",
  facing_mm: "",
  saw_mm: "",
  notes: "",
};

/** P3-04: bills of materials, their revisions, standard cost and where-used. */
export default function BomsPage() {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<number | "new" | null>(null);
  const found = useQuery({ queryKey: [...bomsKey, q, status], queryFn: () => getBoms(q, status) });
  const d = found.data;
  const shown = d?.results.find((b) => b.id === open);
  return (
    <main className="page">
      <h1>{t("bom.title")}</h1>
      <p className="muted">{t("bom.help")}</p>
      <div className="inline-form">
        <label>
          {t("bom.search")}
          <input value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label>
          {t("bom.status")}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("bom.current")}</option>
            {d?.statuses.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        {d?.can_prepare && (
          <button type="button" onClick={() => setOpen("new")}>
            {t("bom.add")}
          </button>
        )}
        <a href={bomExportUrl}>{t("bom.export")}</a>
      </div>
      <ErrorLine error={found.error} />
      {open === "new" && d && <Editor bom={null} list={d} onClose={() => setOpen(null)} onSaved={(b) => setOpen(b.id)} />}
      {shown && d && <Detail key={shown.id} bom={shown} list={d} onOpen={setOpen} />}
      {d && (
        <div className="table-wrap">
          <table aria-label={t("bom.title")}>
            <thead>
              <tr>
                <th>{t("bom.item")}</th>
                <th className="num">{t("bom.revision")}</th>
                <th>{t("bom.kind")}</th>
                <th>{t("bom.status")}</th>
                <th className="num">{t("bom.lines")}</th>
                <th className="num">{t("bom.perUnit")}</th>
              </tr>
            </thead>
            <tbody>
              {d.results.map((b) => (
                <tr key={b.id}>
                  <td>
                    <button type="button" className="link" onClick={() => setOpen(b.id)}>
                      {b.item}
                    </button>{" "}
                    {b.item_name}
                  </td>
                  <td className="num">{b.revision}</td>
                  <td>{b.kind_label}</td>
                  <td>{b.status_label}</td>
                  <td className="num">{b.lines.length}</td>
                  <td className="num">{formatDecimal(b.cost.per_unit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {d.results.length === 0 && <p className="muted">{t("bom.none")}</p>}
        </div>
      )}
      <WhereUsedPanel />
      {d?.can_prepare && <ImportPanel />}
    </main>
  );
}

function Detail({ bom: b, list, onOpen }: { bom: Bom; list: BomList; onOpen: (id: number | null) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [reason, setReason] = useState("");
  const [copyTo, setCopyTo] = useState("");
  const [diff, setDiff] = useState<Comparison | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: bomsKey });
  const act = useMutation({
    mutationFn: ({ action, body }: { action: "submit" | "approve" | "send_back" | "copy"; body?: Record<string, string> }) =>
      bomAction(b.id, action, body),
    onSuccess: (next) => {
      refresh();
      onOpen(next.id);
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteBom(b.id),
    onSuccess: () => {
      refresh();
      onOpen(null);
    },
  });
  const other = list.results.find((x) => x.item === b.item && x.id !== b.id);
  const compare = useMutation({ mutationFn: () => compareBoms(other!.id, b.id), onSuccess: setDiff });
  if (editing) return <Editor bom={b} list={list} onClose={() => setEditing(false)} onSaved={() => setEditing(false)} />;
  const title = t("bom.of", { item: b.item, revision: b.revision });
  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      <p>
        {b.item_name} · {b.kind_label} · {b.division} · {b.status_label}
        {b.drawing_revision && ` · ${t("bom.drawing", { revision: b.drawing_revision })}`} ·{" "}
        {t("bom.base", { quantity: b.base_quantity, unit: b.resin?.family ? t("bom.shots") : b.item_unit })}
      </p>
      {b.returned_reason && (
        <p className="notice" role="status">
          {t("bom.sentBack", { reason: b.returned_reason })}
        </p>
      )}
      {b.resin && (
        <p>
          {t("bom.resin", {
            mould: b.mould,
            shot: b.resin.shot_g,
            piece: b.resin.per_piece_g,
            pieces: b.resin.pieces_per_shot,
            reject: b.reject_pct,
          })}
          {b.max_regrind_pct && ` ${t("bom.regrind", { pct: b.max_regrind_pct })}`}
          {b.resin.family && ` ${t("bom.family", { parts: b.outputs.map((o) => `${o.item} × ${o.cavities}`).join(", ") })}`}
        </p>
      )}
      <div className="table-wrap">
        <table aria-label={t("bom.lines")}>
          <thead>
            <tr>
              <th className="num">{t("bom.seq")}</th>
              <th>{t("bom.lineType")}</th>
              <th>{t("bom.component")}</th>
              <th className="num">{t("bom.quantity")}</th>
              <th className="num">{t("bom.scrap")}</th>
              <th>{t("bom.issue")}</th>
              <th className="num">{t("bom.standard")}</th>
            </tr>
          </thead>
          <tbody>
            {b.lines.map((x) => (
              <tr key={String(x.seq)}>
                <td className="num">{x.seq}</td>
                <td>{x.line_type_label}</td>
                <td>
                  {x.component ? `${x.component} ${x.component_name}` : `${x.description} (${x.supplier})`}
                  {x.cut_length_mm && (
                    <div className="muted">{t("bom.cut", { stock: x.stock_size, cut: x.cut_length_mm, bar: x.bar_length_mm || "-" })}</div>
                  )}
                  {x.customer_supplied && <div className="muted">{t("bom.customerSupplies")}</div>}
                </td>
                <td className="num">
                  {x.quantity} {x.unit}
                </td>
                <td className="num">{x.scrap_pct !== "0" ? `${x.scrap_pct}%` : ""}</td>
                <td>
                  {x.issue_method === "backflush" ? t("bom.backflush") : t("bom.manual")}
                  {x.operation_seq ? ` · ${t("bom.atOp", { op: x.operation_seq })}` : ""}
                </td>
                <td className="num">{x.standard_value ? formatDecimal(x.standard_value) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        <strong>{t("bom.costPerUnit", { cost: formatDecimal(b.cost.per_unit) })}</strong>{" "}
        <span className="muted">
          {t("bom.costSplit", {
            material: formatDecimal(b.cost.material),
            machine: formatDecimal(b.cost.machine),
            labour: formatDecimal(b.cost.labour),
            overhead: formatDecimal(b.cost.overhead),
            mould: formatDecimal(b.cost.mould),
          })}
        </span>
      </p>
      {b.cost.missing.length > 0 && (
        <ul className="muted" aria-label={t("bom.missing")}>
          {b.cost.missing.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      )}
      <div className="row-actions">
        {b.can_edit && (
          <>
            <button type="button" className="secondary" onClick={() => setEditing(true)}>
              {t("bom.edit")}
            </button>
            <button type="button" onClick={() => act.mutate({ action: "submit" })}>
              {t("bom.submit")}
            </button>
            <button type="button" className="secondary" onClick={() => remove.mutate()}>
              {t("bom.deleteDraft")}
            </button>
          </>
        )}
        {b.can_decide && (
          <>
            <input aria-label={t("bom.reason")} placeholder={t("bom.reason")} value={reason} onChange={(e) => setReason(e.target.value)} />
            <button type="button" onClick={() => act.mutate({ action: "approve", body: { reason } })}>
              {t("bom.approve")}
            </button>
            <button type="button" className="secondary" onClick={() => act.mutate({ action: "send_back", body: { reason } })}>
              {t("bom.sendBack")}
            </button>
          </>
        )}
        {list.can_prepare && (b.status === "approved" || b.status === "obsolete") && (
          <>
            <button type="button" className="secondary" onClick={() => act.mutate({ action: "copy" })}>
              {t("bom.newRevision")}
            </button>
            <input aria-label={t("bom.copyTo")} placeholder={t("bom.copyTo")} value={copyTo} onChange={(e) => setCopyTo(e.target.value)} />
            <button
              type="button"
              className="secondary"
              disabled={!copyTo}
              onClick={() => act.mutate({ action: "copy", body: { item: copyTo } })}
            >
              {t("bom.copy")}
            </button>
          </>
        )}
        {other && (
          <button type="button" className="secondary" onClick={() => compare.mutate()}>
            {t("bom.compareWith", { revision: other.revision })}
          </button>
        )}
      </div>
      {diff && (
        <table aria-label={t("bom.comparison")}>
          <thead>
            <tr>
              <th>{t("bom.component")}</th>
              <th>{diff.a}</th>
              <th>{diff.b}</th>
            </tr>
          </thead>
          <tbody>
            {diff.lines.map((x) => (
              <tr key={x.component} className={x.changed ? "" : "muted"}>
                <td>{x.component}</td>
                <td>{x.a || "-"}</td>
                <td>{x.b || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ErrorLine error={act.error ?? remove.error ?? compare.error} />
    </section>
  );
}

function valuesOf(b: Bom | null): BomValues {
  return {
    kind: b?.kind ?? "machining",
    drawing_revision: b?.drawing_revision ?? "",
    base_quantity: b?.base_quantity ?? "1",
    mould: b?.mould ?? "",
    reject_pct: b?.reject_pct ?? "",
    max_regrind_pct: b?.max_regrind_pct ?? "",
    notes: b?.notes ?? "",
    outputs: b?.outputs.length ? b.outputs : [],
    lines: b?.lines.length ? b.lines : [{ ...BLANK_LINE, seq: "10" }],
  };
}

function Editor({ bom, list, onClose, onSaved }: { bom: Bom | null; list: BomList; onClose: () => void; onSaved: (b: Bom) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [item, setItem] = useState(bom?.item ?? "");
  const [values, setValues] = useState<BomValues>(valuesOf(bom));
  const save = useMutation({
    mutationFn: () => {
      const body = { ...values, outputs: values.kind === "moulding" ? values.outputs : undefined };
      return bom ? changeBom(bom.id, body) : addBom({ ...body, item });
    },
    onSuccess: (b) => {
      void queryClient.invalidateQueries({ queryKey: bomsKey });
      onSaved(b);
    },
  });
  const set = (key: keyof BomValues) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  const setLine = (i: number, key: keyof BomLine, value: string | boolean) =>
    setValues({ ...values, lines: values.lines.map((x, j) => (j === i ? { ...x, [key]: value } : x)) });
  const setOutput = (i: number, key: keyof BomOutput, value: string) =>
    setValues({ ...values, outputs: (values.outputs ?? []).map((x, j) => (j === i ? { ...x, [key]: value } : x)) });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const moulding = values.kind === "moulding";
  const title = bom ? t("bom.editOf", { item: bom.item, revision: bom.revision }) : t("bom.add");
  const cell = (i: number, key: keyof BomLine, label: string, size = 7) => (
    <input
      aria-label={t(`bom.f.${label}`, { n: i + 1 })}
      size={size}
      value={String(values.lines[i][key] ?? "")}
      onChange={(e) => setLine(i, key, e.target.value)}
    />
  );
  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      <form onSubmit={submit}>
        <div className="form-grid">
          <label>
            {t("bom.item")}
            <input value={item} disabled={!!bom} onChange={(e) => setItem(e.target.value)} />
          </label>
          <label>
            {t("bom.kind")}
            <select value={values.kind} onChange={set("kind")}>
              <option value="machining">{t("bom.kinds.machining")}</option>
              <option value="moulding">{t("bom.kinds.moulding")}</option>
              <option value="general">{t("bom.kinds.general")}</option>
            </select>
          </label>
          <label>
            {t("bom.baseQuantity")}
            <input inputMode="decimal" value={values.base_quantity} onChange={set("base_quantity")} />
          </label>
          <label>
            {t("bom.drawingRevision")}
            <input value={values.drawing_revision} onChange={set("drawing_revision")} />
          </label>
          {moulding && (
            <>
              <label>
                {t("bom.mould")}
                <input value={values.mould} onChange={set("mould")} />
              </label>
              <label>
                {t("bom.rejectPct")}
                <input inputMode="decimal" value={values.reject_pct} onChange={set("reject_pct")} />
              </label>
              <label>
                {t("bom.regrindPct")}
                <input inputMode="decimal" value={values.max_regrind_pct} onChange={set("max_regrind_pct")} />
              </label>
            </>
          )}
          <label className="wide">
            {t("bom.notes")}
            <input value={values.notes} onChange={set("notes")} />
          </label>
        </div>
        {moulding && (
          <fieldset>
            <legend>{t("bom.outputs")}</legend>
            <p className="muted">{t("bom.outputsHelp")}</p>
            {(values.outputs ?? []).map((o, i) => (
              <div key={i} className="inline-form">
                <input
                  aria-label={t("bom.f.outputItem", { n: i + 1 })}
                  size={10}
                  value={o.item}
                  onChange={(e) => setOutput(i, "item", e.target.value)}
                />
                <input
                  aria-label={t("bom.f.outputCavities", { n: i + 1 })}
                  size={4}
                  value={String(o.cavities)}
                  onChange={(e) => setOutput(i, "cavities", e.target.value)}
                />
                <input
                  aria-label={t("bom.f.outputWeight", { n: i + 1 })}
                  size={6}
                  value={o.part_weight_g}
                  onChange={(e) => setOutput(i, "part_weight_g", e.target.value)}
                />
              </div>
            ))}
            <button
              type="button"
              className="small secondary"
              onClick={() =>
                setValues({
                  ...values,
                  outputs: [...(values.outputs ?? []), { item: values.outputs?.length ? "" : item, cavities: "", part_weight_g: "" }],
                })
              }
            >
              {t("bom.addOutput")}
            </button>
          </fieldset>
        )}
        <p className="muted">{moulding ? t("bom.linesHelpMoulding") : t("bom.linesHelp")}</p>
        <div className="table-wrap">
          <table aria-label={t("bom.lines")}>
            <thead>
              <tr>
                <th>{t("bom.seq")}</th>
                <th>{t("bom.lineType")}</th>
                <th>{t("bom.componentOrService")}</th>
                <th>{t("bom.quantity")}</th>
                <th>{t("bom.scrap")}</th>
                <th>{t("bom.opNo")}</th>
                <th>{t("bom.customerSuppliesShort")}</th>
                <th>{moulding ? t("bom.pctOfResin") : t("bom.cutLength")}</th>
                {!moulding && <th>{t("bom.barLength")}</th>}
                {!moulding && <th>{t("bom.facingSaw")}</th>}
                <th />
              </tr>
            </thead>
            <tbody>
              {values.lines.map((x, i) => (
                <tr key={i}>
                  <td>{cell(i, "seq", "seq", 4)}</td>
                  <td>
                    <select
                      aria-label={t("bom.f.type", { n: i + 1 })}
                      value={x.line_type}
                      onChange={(e) => setLine(i, "line_type", e.target.value)}
                    >
                      {list.line_types.map((lt) => (
                        <option key={lt.value} value={lt.value}>
                          {lt.label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    {x.line_type === "subcontract" ? (
                      <>
                        {cell(i, "description", "description", 14)} {cell(i, "supplier", "supplier", 7)}{" "}
                        {cell(i, "unit_cost", "unitCost", 6)}
                      </>
                    ) : (
                      cell(i, "component", "component", 10)
                    )}
                  </td>
                  <td>{cell(i, "quantity", "quantity", 8)}</td>
                  <td>{cell(i, "scrap_pct", "scrap", 4)}</td>
                  <td>{cell(i, "operation_seq", "op", 4)}</td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={t("bom.f.customer", { n: i + 1 })}
                      checked={x.customer_supplied}
                      onChange={(e) => setLine(i, "customer_supplied", e.target.checked)}
                    />
                  </td>
                  <td>{moulding ? cell(i, "pct_of_resin", "pctOfResin", 4) : cell(i, "cut_length_mm", "cut", 6)}</td>
                  {!moulding && <td>{cell(i, "bar_length_mm", "bar", 6)}</td>}
                  {!moulding && (
                    <td>
                      {cell(i, "facing_mm", "facing", 3)} {cell(i, "saw_mm", "saw", 3)}
                    </td>
                  )}
                  <td>
                    <button
                      type="button"
                      className="small secondary"
                      onClick={() => setValues({ ...values, lines: values.lines.filter((_, j) => j !== i) })}
                    >
                      {t("bom.remove")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="row-actions">
          <button
            type="button"
            className="secondary"
            onClick={() =>
              setValues({
                ...values,
                lines: [...values.lines, { ...BLANK_LINE, seq: String((Number(values.lines[values.lines.length - 1]?.seq) || 0) + 10) }],
              })
            }
          >
            {t("bom.addLine")}
          </button>
          <button type="submit" disabled={save.isPending}>
            {t("bom.save")}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t("common.cancel")}
          </button>
        </div>
        <ErrorLine error={save.error} />
      </form>
    </section>
  );
}

function WhereUsedPanel() {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [result, setResult] = useState<WhereUsed | null>(null);
  const run = useMutation({ mutationFn: () => whereUsed(code), onSuccess: setResult });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run.mutate();
  };
  return (
    <section className="panel" aria-label={t("bom.whereUsed")}>
      <h2>{t("bom.whereUsed")}</h2>
      <form className="inline-form" onSubmit={submit}>
        <label>
          {t("bom.componentCode")}
          <input value={code} onChange={(e) => setCode(e.target.value)} />
        </label>
        <button type="submit" disabled={!code}>
          {t("bom.find")}
        </button>
      </form>
      {result && (
        <ul className="plain">
          {result.boms.length === 0 && <li className="muted">{t("bom.notUsed", { item: result.item })}</li>}
          {result.boms.map((b) => (
            <li key={`${b.id}`}>
              {t("bom.usedIn", {
                item: b.item,
                name: b.item_name,
                revision: b.revision,
                quantity: b.quantity,
                unit: b.unit,
                status: b.status,
              })}
            </li>
          ))}
        </ul>
      )}
      <ErrorLine error={run.error} />
    </section>
  );
}

function ImportPanel() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<{ drafts: number; saved: boolean } | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) => importBoms(file!, dryRun),
    onSuccess: (r) => {
      setResult(r);
      if (r.saved) void queryClient.invalidateQueries({ queryKey: bomsKey });
    },
  });
  return (
    <section className="panel" aria-label={t("bom.import")}>
      <h2>{t("bom.import")}</h2>
      <p className="muted">{t("bom.importHelp")}</p>
      <div className="inline-form">
        <label>
          {t("bom.file")}
          <input
            type="file"
            accept=".xlsx"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setResult(null);
            }}
          />
        </label>
        <button type="button" className="secondary" disabled={!file || run.isPending} onClick={() => run.mutate(true)}>
          {t("bom.check")}
        </button>
        <button type="button" disabled={!file || run.isPending || !result || result.saved} onClick={() => run.mutate(false)}>
          {t("bom.importNow")}
        </button>
      </div>
      {result && (
        <p className="notice" role="status">
          {t(result.saved ? "bom.imported" : "bom.checked", { count: result.drafts })}
        </p>
      )}
      <ErrorLine error={run.error} />
    </section>
  );
}
