import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import {
  addJob,
  changeJob,
  decideExcess,
  getJob,
  getJobLots,
  getJobs,
  getJobSalesLines,
  getWaitingExcess,
  inspectionAction,
  jobAction,
  dispatchNoteUrl,
  jobCardsUrl,
  jobsKey,
  type Dispatch,
  type Transfer,
  type JobAction,
  type JobInspectionRow,
  type JobIssueDoc,
  type JobOrder,
  type JobPurpose,
  type JobValues,
} from "../api/jobOrders";
import OrderCostsPanel from "../components/OrderCostsPanel";
import OrderProfitPanel from "../components/OrderProfitPanel";
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

const today = () => new Date().toISOString().slice(0, 10);

/** P3-11: machining job orders, their operations and materials, material issue and returns. */
export default function JobOrdersPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("open");
  const [purpose, setPurpose] = useState("");
  const [adding, setAdding] = useState(false);
  const open = Number(params.get("job")) || null;
  const show = (id: number | null) => setParams(id ? { job: String(id) } : {});
  const found = useQuery({ queryKey: [...jobsKey, q, status, purpose], queryFn: () => getJobs(q, status, purpose) });
  const d = found.data;
  return (
    <main className="page">
      <h1>{t("job.title")}</h1>
      <p className="muted">{t("job.help")}</p>
      <Waiting onOpen={show} />
      <div className="inline-form">
        <label>
          {t("job.search")}
          <input value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label>
          {t("job.status")}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="open">{t("job.open")}</option>
            <option value="">{t("job.all")}</option>
            {d?.statuses.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("job.for")}
          <select value={purpose} onChange={(e) => setPurpose(e.target.value)}>
            <option value="">{t("job.all")}</option>
            {d?.purposes.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        {d?.can_plan && (
          <button type="button" onClick={() => setAdding(true)}>
            {t("job.add")}
          </button>
        )}
      </div>
      <ErrorLine error={found.error} />
      {adding && d && (
        <NewJob
          divisions={d.divisions}
          purposes={d.purposes}
          onClose={() => setAdding(false)}
          onSaved={(j) => {
            setAdding(false);
            show(j.id);
          }}
        />
      )}
      {open && <Detail key={open} id={open} onClose={() => show(null)} />}
      {d && (
        <div className="table-wrap">
          <table aria-label={t("job.title")}>
            <thead>
              <tr>
                <th>{t("job.number")}</th>
                <th>{t("job.what")}</th>
                <th className="num">{t("job.quantity")}</th>
                <th>{t("job.for")}</th>
                <th>{t("job.dueDate")}</th>
                <th>{t("job.status")}</th>
              </tr>
            </thead>
            <tbody>
              {d.results.map((j) => (
                <tr key={j.id}>
                  <td>
                    <button type="button" className="link" onClick={() => show(j.id)}>
                      {j.number}
                    </button>
                  </td>
                  <td>
                    {j.item} <span className="muted small">{j.description}</span>
                  </td>
                  <td className="num">
                    {formatDecimal(j.quantity)} {j.unit}
                  </td>
                  <td>{j.purpose === "sales" ? `${j.sales_order} ${j.customer}` : `${j.purpose_label}${j.mould ? ` ${j.mould}` : ""}`}</td>
                  <td>{j.due_date}</td>
                  <td>{j.status_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {d.results.length === 0 && <p className="muted">{t("job.none")}</p>}
        </div>
      )}
    </main>
  );
}

/** Requests to issue more that the Production Manager may decide. */
function Waiting({ onOpen }: { onOpen: (id: number) => void }) {
  const { t } = useTranslation();
  const found = useQuery({ queryKey: [...jobsKey, "waiting"], queryFn: getWaitingExcess });
  const rows = found.data?.results ?? [];
  if (rows.length === 0) return null;
  return (
    <section className="panel" aria-label={t("job.waiting")}>
      <h2>{t("job.waiting")}</h2>
      {rows.map((w) => (
        <p key={w.id}>
          <button type="button" className="link" onClick={() => onOpen(w.job_id)}>
            {w.job}
          </button>
          : {formatDecimal(w.quantity)} {w.unit} {w.item} — {w.reason} <span className="muted small">{w.by}</span>
        </p>
      ))}
    </section>
  );
}

const MOULD: JobPurpose[] = ["new_mould", "mould_repair"];

function NewJob({
  divisions,
  purposes,
  onClose,
  onSaved,
}: {
  divisions: string[];
  purposes: { value: JobPurpose; label: string }[];
  onClose: () => void;
  onSaved: (j: JobOrder) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [values, setValues] = useState<Record<string, string>>({ purpose: "sales", division: divisions[0] ?? "", due_date: "" });
  const [find, setFind] = useState("");
  const lines = useQuery({
    queryKey: [...jobsKey, "sales-lines", find],
    queryFn: () => getJobSalesLines(find),
    enabled: values.purpose === "sales",
  });
  const save = useMutation({
    mutationFn: () => addJob(values),
    onSuccess: (j) => {
      void queryClient.invalidateQueries({ queryKey: jobsKey });
      onSaved(j);
    },
  });
  const set = (key: string) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  const field = (key: string, label: string, extra: Record<string, string> = {}) => (
    <label>
      {label}
      <input value={values[key] ?? ""} onChange={set(key)} {...extra} />
    </label>
  );
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const purpose = values.purpose as JobPurpose;
  return (
    <section className="panel" aria-label={t("job.add")}>
      <h2>{t("job.add")}</h2>
      <form className="form-grid" aria-label={t("job.add")} onSubmit={submit}>
        <label>
          {t("job.for")}
          <select value={purpose} onChange={set("purpose")}>
            {purposes.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        {purpose === "sales" ? (
          <>
            <label>
              {t("job.findLine")}
              <input value={find} onChange={(e) => setFind(e.target.value)} />
            </label>
            <label className="wide">
              {t("job.salesLine")}
              <select value={values.sales_line ?? ""} onChange={set("sales_line")}>
                <option value="">{t("job.choose")}</option>
                {lines.data?.results.map((l) => (
                  <option key={l.id} value={l.id}>
                    {t("prodOrder.lineOption", {
                      order: l.order,
                      line: l.line_no,
                      customer: l.customer,
                      description: l.description,
                      left: formatDecimal(l.left),
                      unit: l.unit,
                    })}
                  </option>
                ))}
              </select>
            </label>
          </>
        ) : (
          <label>
            {t("job.division")}
            <select value={values.division} onChange={set("division")}>
              {divisions.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
        )}
        {MOULD.includes(purpose) && field("mould", t("job.mould"))}
        {field("item", purpose === "sales" ? t("job.part") : t("job.partOptional"))}
        {field("description", t("job.description"))}
        {field("drawing_no", t("job.drawingNo"))}
        {field("drawing_revision", t("job.drawingRev"))}
        {field("quantity", t("job.quantity"), { inputMode: "decimal" })}
        {field("due_date", t("job.dueDate"), { type: "date" })}
        <p className="muted wide">{t("job.copyHelp")}</p>
        <div className="wide row-actions">
          <button type="submit" disabled={save.isPending}>
            {t("job.save")}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t("job.close")}
          </button>
        </div>
        <div className="wide">
          <ErrorLine error={save.error} />
        </div>
      </form>
    </section>
  );
}

function Detail({ id, onClose }: { id: number; onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = ["job-order", id];
  const found = useQuery({ queryKey: key, queryFn: () => getJob(id) });
  const [reason, setReason] = useState("");
  const [done, setDone] = useState("");
  const saved = (j: JobOrder) => {
    if (j.stock_issue) setDone(j.stock_issue);
    queryClient.setQueryData(key, j);
    void queryClient.invalidateQueries({ queryKey: jobsKey });
  };
  const act = useMutation({
    mutationFn: ({ action, body }: { action: JobAction; body?: JobValues }) => jobAction(id, action, body),
    onSuccess: saved,
  });
  const j = found.data;
  if (!j) return <ErrorLine error={found.error} />;
  return (
    <section className="panel" aria-label={t("job.panel", { number: j.number })}>
      <h2>
        {j.number} — {j.status_label}
      </h2>
      <p>
        <strong>
          {j.item} {j.description}
        </strong>{" "}
        × {formatDecimal(j.quantity)} {j.unit} · {t("job.due", { date: j.due_date })}
        {j.drawing_no && <> · {t("job.drawing", { no: j.drawing_no, rev: j.drawing_revision || "—" })}</>}
      </p>
      <p className="muted">
        {j.sales_line
          ? t("prodOrder.forLine", { order: j.sales_line.order, line: j.sales_line.line_no, customer: j.sales_line.customer })
          : `${j.purpose_label}${j.mould ? ` ${j.mould}` : ""}`}
        {" · "}
        {j.routing ? t("job.routingRev", { revision: j.routing.revision }) : t("job.noRouting")}
        {j.bom && <> · {t("job.bomRev", { revision: j.bom.revision })}</>}
      </p>
      {j.end_reason && <p className="notice">{t("prodOrder.cancelled", { reason: j.end_reason })}</p>}
      {j.on_hold && (
        <p className="notice form-error" role="status">
          {t("job.onHold")}
        </p>
      )}
      {done && <p className="notice">{t("job.posted", { number: done })}</p>}
      {j.can_edit ? (
        <EditLines job={j} onSaved={saved} />
      ) : (
        <>
          {j.progress.length > 0 ? <Progress job={j} /> : <Operations job={j} />}
          <Materials job={j} />
        </>
      )}
      {j.can_print_cards && (
        <p>
          <a href={jobCardsUrl(j.id)} target="_blank" rel="noreferrer">
            {t("job.printCards")}
          </a>
        </p>
      )}
      <div className="row-actions">
        {j.can_release && (
          <button type="button" disabled={act.isPending} onClick={() => act.mutate({ action: "release" })}>
            {t("job.release")}
          </button>
        )}
        {j.can_complete && (
          <button type="button" disabled={act.isPending} onClick={() => act.mutate({ action: "complete" })}>
            {t("job.complete")}
          </button>
        )}
        {j.can_close && (
          <button type="button" disabled={act.isPending} onClick={() => act.mutate({ action: "close" })}>
            {t("job.closeJob")}
          </button>
        )}
        <button type="button" className="secondary" onClick={onClose}>
          {t("job.close")}
        </button>
      </div>
      {j.can_cancel && (
        <div className="inline-form">
          <label>
            {t("job.cancelReason")}
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button
            type="button"
            className="secondary"
            disabled={act.isPending}
            onClick={() => act.mutate({ action: "cancel", body: { reason } })}
          >
            {t("job.cancel")}
          </button>
        </div>
      )}
      <ErrorLine error={act.error} />
      {(j.can_inspect || j.inspections.length > 0) && <Inspections job={j} onSaved={saved} />}
      {j.transfer && <TransferPanel job={j} transfer={j.transfer} onSaved={saved} />}
      {j.profit && <OrderProfitPanel profit={j.profit} />}
      {j.costs && <OrderCostsPanel costs={j.costs} busy={act.isPending} onRefresh={() => act.mutate({ action: "refresh-costs" })} />}
      {(j.can_subcontract || j.subcontract.length > 0) && <Subcontract job={j} onSaved={saved} />}
      {j.bills.length > 0 && <Bills job={j} />}
      {j.can_issue && <Issue job={j} onSaved={saved} />}
      {j.can_ask_more && <AskMore job={j} onSaved={saved} />}
      <Excess job={j} onDecided={() => void queryClient.invalidateQueries({ queryKey: key })} />
      {j.issues.length > 0 && <Issues job={j} onSaved={saved} />}
    </section>
  );
}

function Operations({ job }: { job: JobOrder }) {
  const { t } = useTranslation();
  return (
    <div className="table-wrap">
      <table aria-label={t("job.operations")}>
        <thead>
          <tr>
            <th>{t("job.seq")}</th>
            <th>{t("job.operation")}</th>
            <th>{t("job.where")}</th>
            <th className="num">{t("job.setupMin")}</th>
            <th className="num">{t("job.runMin")}</th>
          </tr>
        </thead>
        <tbody>
          {job.operations.map((o) => (
            <tr key={o.seq}>
              <td>{o.seq}</td>
              <td>{o.name}</td>
              <td>{o.subcontract ? t("job.sentTo", { supplier: o.supplier }) : `${o.section} ${o.machine}`}</td>
              <td className="num">{formatDecimal(o.setup_min)}</td>
              <td className="num">{formatDecimal(o.run_min)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** P3-12: what each operation received, completed, rejected and passed on. */
function Progress({ job }: { job: JobOrder }) {
  const { t } = useTranslation();
  return (
    <div className="table-wrap">
      <table aria-label={t("job.progress")}>
        <thead>
          <tr>
            <th>{t("job.operation")}</th>
            <th className="num">{t("job.received")}</th>
            <th className="num">{t("job.completed")}</th>
            <th className="num">{t("job.rejected")}</th>
            <th className="num">{t("job.rework")}</th>
            <th className="num">{t("job.inHand")}</th>
            <th className="num">{t("job.atSupplier")}</th>
            <th className="num">{t("job.available")}</th>
          </tr>
        </thead>
        <tbody>
          {job.progress.map((s) => (
            <tr key={s.seq}>
              <td>
                {s.seq} {s.name}
                {s.subcontract && <span className="muted small"> ({t("job.atSupplier").toLowerCase()})</span>}
              </td>
              <td className="num">{formatDecimal(s.received)}</td>
              <td className="num">{formatDecimal(s.completed)}</td>
              <td className="num">{formatDecimal(s.rejected)}</td>
              <td className="num">{formatDecimal(s.rework)}</td>
              <td className="num">{formatDecimal(s.in_hand)}</td>
              <td className="num">{s.subcontract ? formatDecimal(s.at_supplier) : ""}</td>
              <td className="num">
                {s.finished !== "0" ? `${t("job.finished")} ${formatDecimal(s.finished)}` : formatDecimal(s.available)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Materials({ job }: { job: JobOrder }) {
  const { t } = useTranslation();
  return (
    <div className="table-wrap">
      <table aria-label={t("job.materials")}>
        <thead>
          <tr>
            <th>{t("job.material")}</th>
            <th className="num">{t("job.perPiece")}</th>
            <th className="num">{t("job.allowed")}</th>
            <th className="num">{t("job.issued")}</th>
            <th className="num">{t("job.left")}</th>
            <th className="num">{t("job.onHand")}</th>
          </tr>
        </thead>
        <tbody>
          {job.materials.map((m, i) => (
            <tr key={`${m.seq}-${i}`}>
              <td>
                {m.component || m.supplier} <span className="muted small">{m.name}</span>
                {m.extra && <span className="muted small"> {t("job.extra")}</span>}
              </td>
              <td className="num">{m.per_piece ? `${formatDecimal(m.per_piece)} ${m.unit}` : ""}</td>
              <td className="num">{m.allowed ? formatDecimal(m.allowed) : ""}</td>
              <td className="num">{m.issued ? formatDecimal(m.issued) : ""}</td>
              <td className="num">{m.left ? formatDecimal(m.left) : ""}</td>
              <td className="num">{m.on_hand ? formatDecimal(m.on_hand) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {job.materials.length === 0 && <p className="muted">{t("job.noMaterials")}</p>}
    </div>
  );
}

type Row = Record<string, string>;
const OP_FIELDS = ["seq", "name", "section", "machine", "setup_min", "run_min", "supplier"] as const;
const MAT_FIELDS = ["seq", "line_type", "component", "per_piece", "operation_seq"] as const;

/** The Planner changes this job's operations and materials while it is a draft. */
function EditLines({ job, onSaved }: { job: JobOrder; onSaved: (j: JobOrder) => void }) {
  const { t } = useTranslation();
  const asRows = <T extends object>(rows: T[], fields: readonly string[]): Row[] =>
    rows.map((r) => Object.fromEntries(fields.map((f) => [f, String((r as Record<string, unknown>)[f] ?? "")])));
  const [ops, setOps] = useState<Row[]>(asRows(job.operations, OP_FIELDS));
  const [mats, setMats] = useState<Row[]>(
    asRows(
      job.materials.filter((m) => !m.extra),
      MAT_FIELDS,
    ),
  );
  const [quantity, setQuantity] = useState(job.quantity);
  const [due, setDue] = useState(job.due_date);
  const save = useMutation({
    mutationFn: (body: JobValues) => changeJob(job.id, body),
    onSuccess: (j) => {
      setOps(asRows(j.operations, OP_FIELDS));
      setMats(
        asRows(
          j.materials.filter((m) => !m.extra),
          MAT_FIELDS,
        ),
      );
      onSaved(j);
    },
  });
  const edit = (rows: Row[], set: (r: Row[]) => void, i: number, f: string, v: string) =>
    set(rows.map((r, n) => (n === i ? { ...r, [f]: v } : r)));
  const send = () =>
    save.mutate({
      quantity,
      due_date: due,
      operations: ops.filter((o) => o.name).map((o) => ({ ...o, subcontract: Boolean(o.supplier) })),
      materials: mats.filter((m) => m.component),
    });
  const table = (label: string, rows: Row[], set: (r: Row[]) => void, fields: readonly string[], blank: Row) => (
    <>
      <h3>{label}</h3>
      <div className="table-wrap">
        <table aria-label={label}>
          <thead>
            <tr>
              {fields.map((f) => (
                <th key={f}>{t(`job.fields.${f}`)}</th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {fields.map((f) => (
                  <td key={f}>
                    <input
                      aria-label={`${t(`job.fields.${f}`)} ${i + 1}`}
                      value={r[f] ?? ""}
                      onChange={(e) => edit(rows, set, i, f, e.target.value)}
                    />
                  </td>
                ))}
                <td>
                  <button type="button" className="secondary small" onClick={() => set(rows.filter((_, n) => n !== i))}>
                    {t("job.remove")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button type="button" className="secondary small" onClick={() => set([...rows, { ...blank }])}>
        {t("job.addLine")}
      </button>
    </>
  );
  return (
    <div aria-label={t("job.change")}>
      <div className="inline-form">
        <label>
          {t("job.quantity")}
          <input inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </label>
        <label>
          {t("job.dueDate")}
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </label>
      </div>
      {table(t("job.operations"), ops, setOps, OP_FIELDS, {
        seq: "",
        name: "",
        section: "",
        machine: "",
        setup_min: "0",
        run_min: "0",
        supplier: "",
      })}
      {table(t("job.materials"), mats, setMats, MAT_FIELDS, { seq: "", line_type: "raw", component: "", per_piece: "", operation_seq: "" })}
      <p className="muted">{t("job.typesHelp")}</p>
      <div className="row-actions">
        <button type="button" disabled={save.isPending} onClick={send}>
          {t("job.saveChanges")}
        </button>
        {job.item && (
          <button type="button" className="secondary" disabled={save.isPending} onClick={() => save.mutate({ copy_again: true })}>
            {t("job.copyAgain")}
          </button>
        )}
      </div>
      <ErrorLine error={save.error} />
    </div>
  );
}

/** The stores person issues material to a released job, by lot. */
function Issue({ job, onSaved }: { job: JobOrder; onSaved: (j: JobOrder) => void }) {
  const { t } = useTranslation();
  const [store, setStore] = useState(job.stores[0]?.id ?? 0);
  const [lines, setLines] = useState<Row[]>([{ item: "", quantity: "", lot_no: "" }]);
  const save = useMutation({
    mutationFn: () => jobAction(job.id, "issue", { store, issue_date: today(), lines: lines.filter((l) => l.item && l.quantity) }),
    onSuccess: (j) => {
      setLines([{ item: "", quantity: "", lot_no: "" }]);
      onSaved(j);
    },
  });
  const codes = job.materials.filter((m) => m.component && m.left !== undefined);
  const set = (i: number, f: string, v: string) => setLines(lines.map((l, n) => (n === i ? { ...l, [f]: v } : l)));
  return (
    <section className="panel" aria-label={t("job.issue")}>
      <h3>{t("job.issue")}</h3>
      <label>
        {t("job.store")}
        <select value={store} onChange={(e) => setStore(Number(e.target.value))}>
          {job.stores.map((s) => (
            <option key={s.id} value={s.id}>
              {s.code} {s.name}
            </option>
          ))}
        </select>
      </label>
      {lines.map((l, i) => (
        <div className="inline-form" key={i}>
          <label>
            {t("job.material")}
            <select aria-label={`${t("job.material")} ${i + 1}`} value={l.item} onChange={(e) => set(i, "item", e.target.value)}>
              <option value="">{t("job.choose")}</option>
              {codes.map((m) => (
                <option key={m.component} value={m.component}>
                  {t("job.materialOption", { code: m.component, name: m.name, left: formatDecimal(m.left ?? "0"), unit: m.unit })}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("job.quantity")}
            <input
              aria-label={`${t("job.quantity")} ${i + 1}`}
              inputMode="decimal"
              value={l.quantity}
              onChange={(e) => set(i, "quantity", e.target.value)}
            />
          </label>
          <Lots job={job} store={store} item={l.item} value={l.lot_no} onChange={(v) => set(i, "lot_no", v)} n={i + 1} />
        </div>
      ))}
      <div className="row-actions">
        <button type="button" className="secondary small" onClick={() => setLines([...lines, { item: "", quantity: "", lot_no: "" }])}>
          {t("job.addLine")}
        </button>
        <button type="button" disabled={save.isPending || !store} onClick={() => save.mutate()}>
          {t("job.issueIt")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </section>
  );
}

function Lots(props: { job: JobOrder; store: number; item: string; value: string; onChange: (v: string) => void; n: number }) {
  const { t } = useTranslation();
  const { job, store, item } = props;
  const found = useQuery({
    queryKey: ["job-lots", job.id, store, item],
    queryFn: () => getJobLots(job.id, store, item),
    enabled: Boolean(store && item),
  });
  return (
    <label>
      {t("job.lot")}
      <select aria-label={`${t("job.lot")} ${props.n}`} value={props.value} onChange={(e) => props.onChange(e.target.value)}>
        <option value="">{t("job.oldestFirst")}</option>
        {found.data?.results.map((l) => (
          <option key={l.lot_no} value={l.lot_no}>
            {l.lot_no || t("job.noLot")} ({formatDecimal(l.quantity)})
          </option>
        ))}
      </select>
    </label>
  );
}

function AskMore({ job, onSaved }: { job: JobOrder; onSaved: (j: JobOrder) => void }) {
  const { t } = useTranslation();
  const [values, setValues] = useState({ item: "", quantity: "", reason: "" });
  const save = useMutation({
    mutationFn: () => jobAction(job.id, "ask-more", values),
    onSuccess: (j) => {
      setValues({ item: "", quantity: "", reason: "" });
      onSaved(j);
    },
  });
  const set = (key: keyof typeof values) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  return (
    <section className="panel" aria-label={t("job.askMore")}>
      <h3>{t("job.askMore")}</h3>
      <p className="muted">{t("job.askMoreHelp")}</p>
      <div className="inline-form">
        <label>
          {t("job.itemCode")}
          <input value={values.item} onChange={set("item")} />
        </label>
        <label>
          {t("job.extraQuantity")}
          <input inputMode="decimal" value={values.quantity} onChange={set("quantity")} />
        </label>
        <label className="wide">
          {t("job.reason")}
          <input value={values.reason} onChange={set("reason")} />
        </label>
        <button type="button" disabled={save.isPending} onClick={() => save.mutate()}>
          {t("job.sendRequest")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </section>
  );
}

function Excess({ job, onDecided }: { job: JobOrder; onDecided: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const decide = useMutation({
    mutationFn: ({ id, action }: { id: number; action: "approve" | "reject" }) => decideExcess(id, action, reason),
    onSuccess: () => {
      setReason("");
      void queryClient.invalidateQueries({ queryKey: jobsKey });
      onDecided();
    },
  });
  if (job.excess.length === 0) return null;
  const decider = job.excess.some((x) => x.can_decide);
  return (
    <section className="panel" aria-label={t("job.requests")}>
      <h3>{t("job.requests")}</h3>
      {decider && (
        <label>
          {t("job.decisionReason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      )}
      {job.excess.map((x) => (
        <p key={x.id}>
          {formatDecimal(x.quantity)} {x.unit} {x.item} — {x.reason} <span className="muted small">{x.by}</span> ·{" "}
          {t(`job.excessStatus.${x.status}`)}{" "}
          {x.can_decide && (
            <>
              <button
                type="button"
                className="small"
                aria-label={t("job.approveOf", { item: x.item })}
                disabled={decide.isPending}
                onClick={() => decide.mutate({ id: x.id, action: "approve" })}
              >
                {t("job.approve")}
              </button>{" "}
              <button
                type="button"
                className="secondary small"
                aria-label={t("job.rejectOf", { item: x.item })}
                disabled={decide.isPending}
                onClick={() => decide.mutate({ id: x.id, action: "reject" })}
              >
                {t("job.reject")}
              </button>
            </>
          )}
        </p>
      ))}
      <ErrorLine error={decide.error} />
    </section>
  );
}

/** The issues and returns of the job; the stores person takes back material not used. */
function Issues({ job, onSaved }: { job: JobOrder; onSaved: (j: JobOrder) => void }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("job.issues")}>
      <h3>{t("job.issues")}</h3>
      {job.issues.map((d) => (
        <IssueDoc key={d.id} job={job} doc={d} onSaved={onSaved} />
      ))}
    </section>
  );
}

function IssueDoc({ job, doc, onSaved }: { job: JobOrder; doc: JobIssueDoc; onSaved: (j: JobOrder) => void }) {
  const { t } = useTranslation();
  const [back, setBack] = useState<Record<number, string>>({});
  const save = useMutation({
    mutationFn: () =>
      jobAction(job.id, "return", {
        issue: doc.id,
        return_date: today(),
        lines: Object.entries(back)
          .filter(([, q]) => q)
          .map(([line, quantity]) => ({ line: Number(line), quantity })),
      }),
    onSuccess: (j) => {
      setBack({});
      onSaved(j);
    },
  });
  const returnable = job.can_return && doc.kind === "issue" && doc.lines.some((l) => Number(l.returnable) > 0);
  return (
    <div>
      <p>
        <strong>{doc.number}</strong> {doc.kind === "issue" ? t("job.issued") : t("job.returned")} {doc.date} · {doc.store} ·{" "}
        {formatDecimal(doc.value)}
      </p>
      <ul>
        {doc.lines.map((l) => (
          <li key={l.id}>
            {l.item} {l.lot_no && t("job.lotNo", { lot: l.lot_no })} {formatDecimal(l.quantity)} {l.unit}
            {returnable && Number(l.returnable) > 0 && (
              <input
                aria-label={t("job.returnOf", { item: l.item, lot: l.lot_no, number: doc.number })}
                className="small"
                inputMode="decimal"
                placeholder={t("job.backPlaceholder", { most: formatDecimal(l.returnable) })}
                value={back[l.id] ?? ""}
                onChange={(e) => setBack({ ...back, [l.id]: e.target.value })}
              />
            )}
          </li>
        ))}
      </ul>
      {returnable && (
        <button type="button" className="secondary small" disabled={save.isPending} onClick={() => save.mutate()}>
          {t("job.takeBack")}
        </button>
      )}
      <ErrorLine error={save.error} />
    </div>
  );
}

/** P3-13: parts sent out to a supplier for an operation, and counted back. */
function Subcontract({ job, onSaved }: { job: JobOrder; onSaved: (j: JobOrder) => void }) {
  const { t } = useTranslation();
  const ops = job.operations.filter((o) => o.subcontract);
  const [values, setValues] = useState({ operation: String(ops[0]?.seq ?? ""), quantity: "", expected_on: "", supplier: "", notes: "" });
  const send = useMutation({
    mutationFn: () => jobAction(job.id, "send-out", { ...values, sent_on: today() }),
    onSuccess: (j) => {
      setValues({ ...values, quantity: "", notes: "" });
      onSaved(j);
    },
  });
  const set = (key: keyof typeof values) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  return (
    <section className="panel" aria-label={t("job.subcontract")}>
      <h3>{t("job.subcontract")}</h3>
      <p className="muted">{t("job.subcontractHelp")}</p>
      {job.subcontract.map((d) => (
        <Sent key={d.id} job={job} dispatch={d} onSaved={onSaved} />
      ))}
      {job.can_subcontract && ops.length > 0 && (
        <div className="form-grid" role="group" aria-label={t("job.sendOut")}>
          <label>
            {t("job.operationSent")}
            <select value={values.operation} onChange={set("operation")}>
              {ops.map((o) => (
                <option key={o.seq} value={o.seq}>
                  {o.seq} {o.name} ({o.supplier})
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("job.quantitySent")}
            <input inputMode="decimal" value={values.quantity} onChange={set("quantity")} />
          </label>
          <label>
            {t("job.expectedOn")}
            <input type="date" value={values.expected_on} onChange={set("expected_on")} />
          </label>
          <label>
            {t("job.supplierCode")}
            <input value={values.supplier} onChange={set("supplier")} />
          </label>
          <label className="wide">
            {t("job.reason")}
            <input value={values.notes} onChange={set("notes")} />
          </label>
          <div className="wide row-actions">
            <button type="button" disabled={send.isPending} onClick={() => send.mutate()}>
              {t("job.sendIt")}
            </button>
          </div>
          <div className="wide">
            <ErrorLine error={send.error} />
          </div>
        </div>
      )}
    </section>
  );
}

function Sent({ job, dispatch, onSaved }: { job: JobOrder; dispatch: Dispatch; onSaved: (j: JobOrder) => void }) {
  const { t } = useTranslation();
  const [values, setValues] = useState({ good: "", rejected: "", reason: "" });
  const receive = useMutation({
    mutationFn: () => jobAction(job.id, "receive-back", { ...values, dispatch: dispatch.id, received_on: today() }),
    onSuccess: (j) => {
      setValues({ good: "", rejected: "", reason: "" });
      onSaved(j);
    },
  });
  const set = (key: keyof typeof values) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  const label = t("job.receiveBack", { number: dispatch.number });
  return (
    <div className="run-card">
      <p>
        <strong>
          {t("job.sentLine", {
            number: dispatch.number,
            quantity: formatDecimal(dispatch.quantity),
            supplier: dispatch.supplier_name,
            op: dispatch.operation,
            date: dispatch.sent_on,
            out: formatDecimal(dispatch.out),
          })}
        </strong>{" "}
        <a href={dispatchNoteUrl(dispatch.id)} target="_blank" rel="noreferrer">
          {t("job.note")}
        </a>
      </p>
      {dispatch.returns.map((r, i) => (
        <p key={i} className="muted small">
          {t("job.backLine", { date: r.received_on, good: formatDecimal(r.good), rejected: formatDecimal(r.rejected), reason: r.reason })}
        </p>
      ))}
      {job.can_subcontract && Number(dispatch.out) > 0 && (
        <div className="inline-form" role="group" aria-label={label}>
          <label>
            {t("job.good")}
            <input inputMode="decimal" value={values.good} onChange={set("good")} />
          </label>
          <label>
            {t("job.rejectedBack")}
            <input inputMode="decimal" value={values.rejected} onChange={set("rejected")} />
          </label>
          <label>
            {t("job.rejectReason")}
            <input value={values.reason} onChange={set("reason")} />
          </label>
          <button type="button" disabled={receive.isPending} onClick={() => receive.mutate()}>
            {t("job.receiveIt")}
          </button>
          <ErrorLine error={receive.error} />
        </div>
      )}
    </div>
  );
}

function Bills({ job }: { job: JobOrder }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("job.bills")}>
      <h3>{t("job.bills")}</h3>
      {job.bills.map((b) => (
        <p key={`${b.kind}-${b.number}-${b.line_no}`}>
          {t("job.billLine", {
            kind: t(`job.kinds.${b.kind}`),
            number: b.number,
            line: b.line_no,
            supplier: b.supplier,
            amount: formatDecimal(b.amount),
            status: b.status,
          })}
        </p>
      ))}
    </section>
  );
}

/** P3-14: QC inspects the job; a failed inspection holds it until the Production Manager decides. */
function Inspections({ job, onSaved }: { job: JobOrder; onSaved: (j: JobOrder) => void }) {
  const { t } = useTranslation();
  const [values, setValues] = useState({ stage: "first_article", operation: String(job.operations[0]?.seq ?? ""), pieces: "1" });
  const [check, setCheck] = useState({ name: "", minimum: "", maximum: "", unit: "" });
  const start = useMutation({
    mutationFn: () => jobAction(job.id, "inspect", { ...values, checks: check.name ? [{ ...check, kind: "number" }] : [] }),
    onSuccess: (j) => {
      setCheck({ name: "", minimum: "", maximum: "", unit: "" });
      onSaved(j);
    },
  });
  const set = (key: keyof typeof values) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  const setC = (key: keyof typeof check) => (e: { target: { value: string } }) => setCheck({ ...check, [key]: e.target.value });
  const drafting = job.inspections.some((i) => i.status === "draft");
  return (
    <section className="panel" aria-label={t("job.inspections")}>
      <h3>{t("job.inspections")}</h3>
      <p className="muted">{t("job.inspectionsHelp")}</p>
      {job.inspections.map((i) => (
        <Inspection key={i.id} inspection={i} onSaved={onSaved} />
      ))}
      {job.can_inspect && !drafting && (
        <div className="form-grid" role="group" aria-label={t("job.startInspection")}>
          <label>
            {t("job.stage")}
            <select value={values.stage} onChange={set("stage")}>
              {(["first_article", "in_process", "final"] as const).map((s) => (
                <option key={s} value={s}>
                  {t(`job.stages.${s}`)}
                </option>
              ))}
            </select>
          </label>
          {values.stage !== "final" && (
            <label>
              {t("job.afterOperation")}
              <select value={values.operation} onChange={set("operation")}>
                {job.operations.map((o) => (
                  <option key={o.seq} value={o.seq}>
                    {o.seq} {o.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label>
            {t("job.piecesChecked")}
            <input inputMode="numeric" value={values.pieces} onChange={set("pieces")} />
          </label>
          <fieldset className="wide inline-form">
            <legend>{t("job.extraCheck")}</legend>
            <label>
              {t("job.checkName")}
              <input value={check.name} onChange={setC("name")} />
            </label>
            <label>
              {t("job.minimum")}
              <input inputMode="decimal" value={check.minimum} onChange={setC("minimum")} />
            </label>
            <label>
              {t("job.maximum")}
              <input inputMode="decimal" value={check.maximum} onChange={setC("maximum")} />
            </label>
            <label>
              {t("job.unit")}
              <input value={check.unit} onChange={setC("unit")} />
            </label>
          </fieldset>
          <div className="wide row-actions">
            <button type="button" disabled={start.isPending} onClick={() => start.mutate()}>
              {t("job.start")}
            </button>
          </div>
          <div className="wide">
            <ErrorLine error={start.error} />
          </div>
        </div>
      )}
    </section>
  );
}

function Inspection({ inspection: i, onSaved }: { inspection: JobInspectionRow; onSaved: (j: JobOrder) => void }) {
  const { t } = useTranslation();
  const key = (position: number, piece: number) => `${position}-${piece}`;
  const [entered, setEntered] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      i.checks.flatMap((c) =>
        c.pieces.map((p) => [
          key(c.position, p.piece),
          c.kind === "number" ? p.value : p.passed === null ? "" : p.passed ? "pass" : "fail",
        ]),
      ),
    ),
  );
  const [decision, setDecision] = useState({ decision: "rework", quantity: "", reason: "" });
  const [comment, setComment] = useState("");
  const body = () => ({
    results: i.checks.flatMap((c) =>
      c.pieces.map((p) => {
        const v = entered[key(c.position, p.piece)] ?? "";
        return c.kind === "number"
          ? { position: c.position, piece: p.piece, value: v }
          : { position: c.position, piece: p.piece, passed: v === "" ? "" : v === "pass" };
      }),
    ),
  });
  const act = useMutation({
    mutationFn: ({ action, payload }: { action: "save" | "finish" | "decide" | "director"; payload: JobValues }) =>
      inspectionAction(i.id, action, payload),
    onSuccess: onSaved,
  });
  const pieces = i.checks[0]?.pieces.map((p) => p.piece) ?? [];
  return (
    <div
      className="run-card"
      role="group"
      aria-label={t("job.inspectionTitle", { stage: i.stage_label, op: i.operation, status: i.status_label })}
    >
      <p>
        <strong>{t("job.inspectionTitle", { stage: i.stage_label, op: i.operation, status: i.status_label })}</strong>{" "}
        <span className="muted small">{t("job.inspectedBy", { name: i.inspector })}</span>
      </p>
      <div className="table-wrap">
        <table aria-label={t("job.inspectionTitle", { stage: i.stage_label, op: i.operation, status: i.status_label })}>
          <thead>
            <tr>
              <th>{t("job.checkName")}</th>
              {pieces.map((n) => (
                <th key={n}>{t("job.piece", { n })}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {i.checks.map((c) => (
              <tr key={c.position}>
                <td>
                  {c.name}
                  {c.critical && <strong className="small"> ({t("job.critical")})</strong>}
                  {c.kind === "number" && (
                    <div className="muted small">{t("job.limits", { min: c.minimum || "—", max: c.maximum || "—", unit: c.unit })}</div>
                  )}
                </td>
                {c.pieces.map((p) => {
                  const k = key(c.position, p.piece);
                  const label = t("job.resultOf", { check: c.name, n: p.piece });
                  const bad = p.within_limits === false;
                  return (
                    <td key={p.piece} className={bad ? "form-error" : undefined}>
                      {i.can_enter ? (
                        c.kind === "number" ? (
                          <input
                            aria-label={label}
                            inputMode="decimal"
                            value={entered[k] ?? ""}
                            onChange={(e) => setEntered({ ...entered, [k]: e.target.value })}
                          />
                        ) : (
                          <select
                            aria-label={label}
                            value={entered[k] ?? ""}
                            onChange={(e) => setEntered({ ...entered, [k]: e.target.value })}
                          >
                            <option value="">—</option>
                            <option value="pass">{t("job.pass")}</option>
                            <option value="fail">{t("job.fail")}</option>
                          </select>
                        )
                      ) : c.kind === "number" ? (
                        p.value || "—"
                      ) : p.passed === null ? (
                        "—"
                      ) : p.passed ? (
                        t("job.pass")
                      ) : (
                        t("job.fail")
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {i.failed.length > 0 && i.status !== "draft" && (
        <p className="form-error">{t("job.failedChecks", { checks: i.failed.join(", ") })}</p>
      )}
      {i.can_enter && (
        <div className="row-actions">
          <button
            type="button"
            className="secondary"
            disabled={act.isPending}
            onClick={() => act.mutate({ action: "save", payload: body() })}
          >
            {t("job.saveResults")}
          </button>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate({ action: "finish", payload: body() })}>
            {t("job.finish")}
          </button>
        </div>
      )}
      {i.decision && (
        <p className="muted">
          {t("job.decidedLine", {
            decision: i.decision_label,
            quantity: i.decision === "deviation" ? "" : formatDecimal(i.decision_quantity),
            reason: i.decision_reason,
            by: i.decided_by,
          })}
        </p>
      )}
      {!i.decision && i.decision_reason && <p className="muted">{i.decision_reason}</p>}
      {i.can_decide && (
        <div className="inline-form" role="group" aria-label={t("job.decide")}>
          <label>
            {t("job.decision")}
            <select value={decision.decision} onChange={(e) => setDecision({ ...decision, decision: e.target.value })}>
              {(["rework", "scrap", "deviation"] as const).map((d) => (
                <option key={d} value={d}>
                  {t(`job.decisions.${d}`)}
                </option>
              ))}
            </select>
          </label>
          {decision.decision !== "deviation" && (
            <label>
              {t("job.piecesAffected")}
              <input
                inputMode="decimal"
                value={decision.quantity}
                onChange={(e) => setDecision({ ...decision, quantity: e.target.value })}
              />
            </label>
          )}
          <label>
            {t("job.decisionReasonInput")}
            <input value={decision.reason} onChange={(e) => setDecision({ ...decision, reason: e.target.value })} />
          </label>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate({ action: "decide", payload: decision })}>
            {t("job.decideIt")}
          </button>
          {decision.decision === "deviation" && <p className="muted small">{t("job.deviationHelp")}</p>}
        </div>
      )}
      {i.can_approve && (
        <div className="inline-form">
          <label>
            {t("job.decisionReason")}
            <input value={comment} onChange={(e) => setComment(e.target.value)} />
          </label>
          <button
            type="button"
            disabled={act.isPending}
            onClick={() => act.mutate({ action: "director", payload: { action: "approve", reason: comment } })}
          >
            {t("job.directorApprove")}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={act.isPending}
            onClick={() => act.mutate({ action: "director", payload: { action: "reject", reason: comment } })}
          >
            {t("job.directorReturn")}
          </button>
        </div>
      )}
      <ErrorLine error={act.error} />
    </div>
  );
}

/** P3-15: a mould job transferred at cost: capitalised (new mould) or charged (repair). */
function TransferPanel({ job, transfer: x, onSaved }: { job: JobOrder; transfer: Transfer; onSaved: (j: JobOrder) => void }) {
  const { t } = useTranslation();
  const [notes, setNotes] = useState("");
  const post = useMutation({ mutationFn: () => jobAction(job.id, "transfer", { notes }), onSuccess: onSaved });
  const rows: [string, string][] = [
    [t("job.costMaterial"), x.material],
    [t("job.costBills"), x.bills],
    [t("job.costLabour", { hours: x.hours ?? "" }), x.labour],
    [t("job.costOverhead"), x.overhead],
  ];
  return (
    <section className="panel" aria-label={t("job.transfer")}>
      <h3>{t("job.transfer")}</h3>
      <p className="muted">{t("job.transferHelp")}</p>
      <p>
        <strong>{t("job.transferRoute", { kind: x.kind_label, from: x.from, to: x.to || "—" })}</strong>
      </p>
      <table aria-label={t("job.costTotal")}>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td>{label}</td>
              <td className="num">{formatDecimal(value)}</td>
            </tr>
          ))}
          <tr>
            <td>
              <strong>{t("job.costTotal")}</strong>
            </td>
            <td className="num">
              <strong>{formatDecimal(x.amount)}</strong>
            </td>
          </tr>
        </tbody>
      </table>
      {x.bill_lines && x.bill_lines.length > 0 && <p className="muted small">{x.bill_lines.join("; ")}</p>}
      {x.done ? (
        <>
          <p className="notice">{t("job.transferred", { date: x.date, journal: x.journal })}</p>
          {x.asset && <p className="notice">{t("job.assetMade", { asset: x.asset })}</p>}
        </>
      ) : (
        <>
          {x.why_not && <p className="muted">{x.why_not}</p>}
          {x.can_post && (
            <div className="inline-form">
              <label>
                {t("job.transferNotes")}
                <input value={notes} onChange={(e) => setNotes(e.target.value)} />
              </label>
              <button type="button" disabled={post.isPending} onClick={() => post.mutate()}>
                {t("job.transferIt")}
              </button>
            </div>
          )}
          <ErrorLine error={post.error} />
        </>
      )}
    </section>
  );
}
