import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  addRouting,
  changeRouting,
  deleteRouting,
  getRoutings,
  importRoutings,
  routingAction,
  routingExportUrl,
  routingsKey,
  type Operation,
  type Routing,
  type RoutingValues,
} from "../api/routings";

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

const BLANK_OP: Operation = {
  seq: "",
  name: "",
  section: "",
  machine: "",
  setup_min: "",
  run_min: "",
  subcontract: false,
  supplier: "",
  subcontract_cost: "",
  notes: "",
};

/** P3-03: the operations that make each machined part, one approved revision at a time. */
export default function RoutingsPage() {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<number | "new" | null>(null);
  const found = useQuery({ queryKey: [...routingsKey, q, status], queryFn: () => getRoutings(q, status) });
  const d = found.data;
  const shown = d?.results.find((r) => r.id === open);
  return (
    <main className="page">
      <h1>{t("routing.title")}</h1>
      <p className="muted">{t("routing.help")}</p>
      <div className="inline-form">
        <label>
          {t("routing.search")}
          <input value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label>
          {t("routing.status")}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("routing.current")}</option>
            {d?.statuses.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        {d?.can_prepare && (
          <button type="button" onClick={() => setOpen("new")}>
            {t("routing.add")}
          </button>
        )}
        <a href={routingExportUrl}>{t("routing.export")}</a>
      </div>
      <ErrorLine error={found.error} />
      {open === "new" && <Editor routing={null} onClose={() => setOpen(null)} onSaved={(r) => setOpen(r.id)} />}
      {shown && <Detail key={shown.id} routing={shown} onOpen={setOpen} />}
      {d && (
        <div className="table-wrap">
          <table aria-label={t("routing.title")}>
            <thead>
              <tr>
                <th>{t("routing.item")}</th>
                <th className="num">{t("routing.revision")}</th>
                <th>{t("routing.status")}</th>
                <th className="num">{t("routing.operations")}</th>
                <th className="num">{t("routing.setup")}</th>
                <th className="num">{t("routing.run")}</th>
              </tr>
            </thead>
            <tbody>
              {d.results.map((r) => (
                <tr key={r.id}>
                  <td>
                    <button type="button" className="link" onClick={() => setOpen(r.id)}>
                      {r.item}
                    </button>{" "}
                    {r.item_name}
                  </td>
                  <td className="num">{r.revision}</td>
                  <td>{r.status_label}</td>
                  <td className="num">{r.operations.length}</td>
                  <td className="num">{r.setup_min}</td>
                  <td className="num">{r.run_min}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {d.results.length === 0 && <p className="muted">{t("routing.none")}</p>}
        </div>
      )}
      {d?.can_prepare && <ImportPanel />}
    </main>
  );
}

function Detail({ routing: r, onOpen }: { routing: Routing; onOpen: (id: number | null) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [reason, setReason] = useState("");
  const [copyTo, setCopyTo] = useState("");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: routingsKey });
  const act = useMutation({
    mutationFn: ({ action, body }: { action: "submit" | "approve" | "send_back" | "copy"; body?: Record<string, string> }) =>
      routingAction(r.id, action, body),
    onSuccess: (next) => {
      refresh();
      onOpen(next.id);
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteRouting(r.id),
    onSuccess: () => {
      refresh();
      onOpen(null);
    },
  });
  if (editing) return <Editor routing={r} onClose={() => setEditing(false)} onSaved={() => setEditing(false)} />;
  return (
    <section className="panel" aria-label={t("routing.of", { item: r.item, revision: r.revision })}>
      <h2>{t("routing.of", { item: r.item, revision: r.revision })}</h2>
      <p>
        {r.item_name} · {r.status_label}
        {r.drawing_revision && ` · ${t("routing.drawing", { revision: r.drawing_revision })}`} · {t("routing.by", { name: r.created_by })}
      </p>
      {r.returned_reason && (
        <p className="notice" role="status">
          {t("routing.sentBack", { reason: r.returned_reason })}
        </p>
      )}
      <Operations operations={r.operations} />
      <p className="muted">{t("routing.totals", { setup: r.setup_min, run: r.run_min, cost: r.subcontract_cost })}</p>
      {r.notes && <p>{r.notes}</p>}
      <div className="row-actions">
        {r.can_edit && (
          <>
            <button type="button" className="secondary" onClick={() => setEditing(true)}>
              {t("routing.edit")}
            </button>
            <button type="button" onClick={() => act.mutate({ action: "submit" })}>
              {t("routing.submit")}
            </button>
            <button type="button" className="secondary" onClick={() => remove.mutate()}>
              {t("routing.deleteDraft")}
            </button>
          </>
        )}
        {r.can_decide && (
          <>
            <input aria-label={t("routing.reason")} placeholder={t("routing.reason")} value={reason} onChange={(e) => setReason(e.target.value)} />
            <button type="button" onClick={() => act.mutate({ action: "approve", body: { reason } })}>
              {t("routing.approve")}
            </button>
            <button type="button" className="secondary" onClick={() => act.mutate({ action: "send_back", body: { reason } })}>
              {t("routing.sendBack")}
            </button>
          </>
        )}
        {(r.status === "approved" || r.status === "obsolete") && (
          <>
            <button type="button" className="secondary" onClick={() => act.mutate({ action: "copy" })}>
              {t("routing.newRevision")}
            </button>
            <input aria-label={t("routing.copyTo")} placeholder={t("routing.copyTo")} value={copyTo} onChange={(e) => setCopyTo(e.target.value)} />
            <button type="button" className="secondary" disabled={!copyTo} onClick={() => act.mutate({ action: "copy", body: { item: copyTo } })}>
              {t("routing.copy")}
            </button>
          </>
        )}
      </div>
      <ErrorLine error={act.error ?? remove.error} />
    </section>
  );
}

function Operations({ operations }: { operations: Operation[] }) {
  const { t } = useTranslation();
  return (
    <div className="table-wrap">
      <table aria-label={t("routing.operations")}>
        <thead>
          <tr>
            <th className="num">{t("routing.seq")}</th>
            <th>{t("routing.operation")}</th>
            <th>{t("routing.where")}</th>
            <th className="num">{t("routing.setup")}</th>
            <th className="num">{t("routing.run")}</th>
          </tr>
        </thead>
        <tbody>
          {operations.map((o) => (
            <tr key={String(o.seq)}>
              <td className="num">{o.seq}</td>
              <td>{o.name}</td>
              <td>
                {o.subcontract
                  ? t("routing.subcontracted", { supplier: o.supplier_name || o.supplier, cost: o.subcontract_cost })
                  : `${o.section_name || o.section}${o.machine ? ` · ${o.machine}` : ""}`}
              </td>
              <td className="num">{o.subcontract ? "" : o.setup_min}</td>
              <td className="num">{o.subcontract ? "" : o.run_min}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Editor({ routing, onClose, onSaved }: { routing: Routing | null; onClose: () => void; onSaved: (r: Routing) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [item, setItem] = useState(routing?.item ?? "");
  const [drawing, setDrawing] = useState(routing?.drawing_revision ?? "");
  const [notes, setNotes] = useState(routing?.notes ?? "");
  const [ops, setOps] = useState<Operation[]>(routing?.operations.length ? routing.operations : [{ ...BLANK_OP, seq: "10" }]);
  const save = useMutation({
    mutationFn: () => {
      const values: RoutingValues = { drawing_revision: drawing, notes, operations: ops };
      return routing ? changeRouting(routing.id, values) : addRouting({ ...values, item });
    },
    onSuccess: (r) => {
      void queryClient.invalidateQueries({ queryKey: routingsKey });
      onSaved(r);
    },
  });
  const setOp = (i: number, key: keyof Operation, value: string | boolean) =>
    setOps(ops.map((o, j) => (j === i ? { ...o, [key]: value } : o)));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const title = routing ? t("routing.editOf", { item: routing.item, revision: routing.revision }) : t("routing.add");
  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      <form onSubmit={submit}>
        <div className="form-grid">
          <label>
            {t("routing.item")}
            <input value={item} disabled={!!routing} onChange={(e) => setItem(e.target.value)} />
          </label>
          <label>
            {t("routing.drawingRevision")}
            <input value={drawing} onChange={(e) => setDrawing(e.target.value)} />
          </label>
          <label className="wide">
            {t("routing.notes")}
            <input value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
        </div>
        <div className="table-wrap">
          <table aria-label={t("routing.operations")}>
            <thead>
              <tr>
                <th>{t("routing.seq")}</th>
                <th>{t("routing.operation")}</th>
                <th>{t("routing.subcontract")}</th>
                <th>{t("routing.sectionOrSupplier")}</th>
                <th>{t("routing.machineOrCost")}</th>
                <th>{t("routing.setup")}</th>
                <th>{t("routing.run")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {ops.map((o, i) => (
                <tr key={i}>
                  <td>
                    <input aria-label={t("routing.seqOf", { n: i + 1 })} size={4} value={String(o.seq)} onChange={(e) => setOp(i, "seq", e.target.value)} />
                  </td>
                  <td>
                    <input aria-label={t("routing.operationOf", { n: i + 1 })} value={o.name} onChange={(e) => setOp(i, "name", e.target.value)} />
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={t("routing.subcontractOf", { n: i + 1 })}
                      checked={o.subcontract}
                      onChange={(e) => setOp(i, "subcontract", e.target.checked)}
                    />
                  </td>
                  <td>
                    {o.subcontract ? (
                      <input aria-label={t("routing.supplierOf", { n: i + 1 })} size={8} value={o.supplier} onChange={(e) => setOp(i, "supplier", e.target.value)} />
                    ) : (
                      <input aria-label={t("routing.sectionOf", { n: i + 1 })} size={8} value={o.section} onChange={(e) => setOp(i, "section", e.target.value)} />
                    )}
                  </td>
                  <td>
                    {o.subcontract ? (
                      <input
                        aria-label={t("routing.costOf", { n: i + 1 })}
                        size={8}
                        inputMode="decimal"
                        value={o.subcontract_cost}
                        onChange={(e) => setOp(i, "subcontract_cost", e.target.value)}
                      />
                    ) : (
                      <input aria-label={t("routing.machineOf", { n: i + 1 })} size={8} value={o.machine} onChange={(e) => setOp(i, "machine", e.target.value)} />
                    )}
                  </td>
                  <td>
                    <input aria-label={t("routing.setupOf", { n: i + 1 })} size={5} inputMode="decimal" value={o.setup_min} onChange={(e) => setOp(i, "setup_min", e.target.value)} />
                  </td>
                  <td>
                    <input aria-label={t("routing.runOf", { n: i + 1 })} size={6} inputMode="decimal" value={o.run_min} onChange={(e) => setOp(i, "run_min", e.target.value)} />
                  </td>
                  <td>
                    <button type="button" className="small secondary" onClick={() => setOps(ops.filter((_, j) => j !== i))}>
                      {t("routing.remove")}
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
            onClick={() => setOps([...ops, { ...BLANK_OP, seq: String((Number(ops[ops.length - 1]?.seq) || 0) + 10) }])}
          >
            {t("routing.addOperation")}
          </button>
          <button type="submit" disabled={save.isPending}>
            {t("routing.save")}
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

function ImportPanel() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<{ drafts: number; saved: boolean } | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) => importRoutings(file!, dryRun),
    onSuccess: (r) => {
      setResult(r);
      if (r.saved) void queryClient.invalidateQueries({ queryKey: routingsKey });
    },
  });
  return (
    <section className="panel" aria-label={t("routing.import")}>
      <h2>{t("routing.import")}</h2>
      <p className="muted">{t("routing.importHelp")}</p>
      <div className="inline-form">
        <label>
          {t("routing.file")}
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
          {t("routing.check")}
        </button>
        <button type="button" disabled={!file || run.isPending || !result || result.saved} onClick={() => run.mutate(false)}>
          {t("routing.importNow")}
        </button>
      </div>
      {result && (
        <p className="notice" role="status">
          {t(result.saved ? "routing.imported" : "routing.checked", { count: result.drafts })}
        </p>
      )}
      <ErrorLine error={run.error} />
    </section>
  );
}
