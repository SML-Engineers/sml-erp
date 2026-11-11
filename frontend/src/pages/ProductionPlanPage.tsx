import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  addEntry,
  copyDay,
  getPlan,
  moveEntry,
  planKey,
  removeEntry,
  type EntryValues,
  type PlanBoard,
  type PlanEntry,
} from "../api/productionPlan";
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

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** P3-07: which order's mould runs on which moulding machine on which shift. */
export default function ProductionPlanPage() {
  const { t } = useTranslation();
  const [start, setStart] = useState(today());
  const [days, setDays] = useState(3);
  const [moving, setMoving] = useState<PlanEntry | null>(null);
  // Owner's testing (T1): a run removed while its Move box is open closes the box with a plain note.
  const [gone, setGone] = useState(false);
  const startMove = (e: PlanEntry) => {
    setGone(false);
    setMoving(e);
  };
  const removed = (id: number) => {
    if (moving?.id === id) setMoving(null);
  };
  const moveFailed = () => {
    setMoving(null);
    setGone(true);
  };
  const found = useQuery({ queryKey: [...planKey, start, days], queryFn: () => getPlan(start, days) });
  const d = found.data;
  return (
    <main className="page">
      <h1>{t("plan.title")}</h1>
      <p className="muted">{t("plan.help")}</p>
      <div className="inline-form">
        <label>
          {t("plan.from")}
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          {t("plan.days")}
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[1, 3, 7, 14].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>
      <ErrorLine error={found.error} />
      {d && (
        <>
          {gone && (
            <p className="notice" role="status">
              {t("plan.runGone")}
            </p>
          )}
          {d.can_plan && (
            <EntryForm key={moving?.id ?? "new"} board={d} moving={moving} onDone={() => setMoving(null)} onGone={moveFailed} />
          )}
          {d.days.map((day) => (
            <Day key={day} day={day} board={d} onMove={startMove} onRemoved={removed} />
          ))}
          {d.can_plan && <Orders board={d} />}
          {d.can_plan && <CopyDay />}
        </>
      )}
    </main>
  );
}

function Day({
  day,
  board,
  onMove,
  onRemoved,
}: {
  day: string;
  board: PlanBoard;
  onMove: (e: PlanEntry) => void;
  onRemoved: (id: number) => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: removeEntry,
    onSuccess: (_, id) => {
      onRemoved(id);
      queryClient.invalidateQueries({ queryKey: planKey });
    },
  });
  const entries = board.entries.filter((e) => e.day === day);
  return (
    <section className="panel" aria-label={t("plan.day", { day })}>
      <h2>{t("plan.day", { day })}</h2>
      <div className="table-wrap">
        <table aria-label={t("plan.day", { day })}>
          <thead>
            <tr>
              <th>{t("plan.machine")}</th>
              {board.shifts.map((s) => (
                <th key={s.code}>{s.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {board.machines.map((m) => (
              <tr key={m.code}>
                <td>
                  {m.code} <span className="muted small">{m.name}</span>
                  {m.status === "maintenance" && <span className="muted small"> {t("plan.maintenance")}</span>}
                  {!m.supervised && <div className="warning-text">{t("plan.noSupervisor", { section: m.section })}</div>}
                </td>
                {board.shifts.map((s) => (
                  <td key={s.code}>
                    {entries
                      .filter((e) => e.machine === m.code && e.shift === s.code)
                      .map((e) => (
                        <div key={e.id} aria-label={t("plan.entry", { order: e.order_number, machine: e.machine, shift: s.name })}>
                          <strong>{e.order_number}</strong> {e.item} · {formatDecimal(e.quantity)} {t("plan.pcs")} ·{" "}
                          {t("plan.minutes", { minutes: e.minutes })}
                          {e.warnings.length > 0 && (
                            <ul className="form-error small">
                              {e.warnings.map((w) => (
                                <li key={w}>{w}</li>
                              ))}
                            </ul>
                          )}
                          {board.can_plan && !e.past && (
                            <div className="row-actions">
                              <button type="button" className="secondary small" onClick={() => onMove(e)}>
                                {t("plan.move")}
                              </button>
                              <button
                                type="button"
                                className="secondary small"
                                disabled={remove.isPending}
                                onClick={() => remove.mutate(e.id)}
                              >
                                {t("plan.remove")}
                              </button>
                            </div>
                          )}
                        </div>
                      ))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {board.machines.length === 0 && <p className="muted">{t("plan.noMachines")}</p>}
      <ErrorLine error={remove.error} />
    </section>
  );
}

function EntryForm({
  board,
  moving,
  onDone,
  onGone,
}: {
  board: PlanBoard;
  moving: PlanEntry | null;
  onDone: () => void;
  onGone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [values, setValues] = useState<EntryValues>(
    moving
      ? { day: moving.day, shift: moving.shift, machine: moving.machine, minutes: String(moving.minutes) }
      : { day: board.days[0], shift: board.shifts[0]?.code ?? "", machine: "", order: undefined, minutes: "", notes: "" },
  );
  const unsupervised = board.machines.find((m) => m.code === values.machine && !m.supervised);
  const save = useMutation({
    mutationFn: () => (moving ? moveEntry(moving.id, values) : addEntry(values)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: planKey });
      if (!moving) setValues({ ...values, minutes: "", notes: "" });
      onDone();
    },
    onError: (error) => {
      // The run was removed (here or by someone else) while it was being moved.
      if (moving && error instanceof ApiError && error.status === 404) {
        queryClient.invalidateQueries({ queryKey: planKey });
        onGone();
      }
    },
  });
  const set = (key: keyof EntryValues) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const title = moving ? t("plan.moveTitle", { order: moving.order_number }) : t("plan.add");
  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      <form className="form-grid" aria-label={title} onSubmit={submit}>
        {!moving && (
          <label className="wide">
            {t("plan.order")}
            <select value={values.order ?? ""} onChange={(e) => setValues({ ...values, order: Number(e.target.value) || undefined })}>
              <option value="">{t("plan.choose")}</option>
              {board.orders.map((o) => (
                <option key={o.id} value={o.id}>
                  {t("plan.orderOption", {
                    number: o.number,
                    item: o.item,
                    mould: o.mould,
                    planned: formatDecimal(o.planned),
                    quantity: formatDecimal(o.quantity),
                  })}
                </option>
              ))}
            </select>
          </label>
        )}
        <label>
          {t("plan.date")}
          <input type="date" value={values.day} onChange={set("day")} />
        </label>
        <label>
          {t("plan.shift")}
          <select value={values.shift} onChange={set("shift")}>
            {board.shifts.map((s) => (
              <option key={s.code} value={s.code}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("plan.machine")}
          <select value={values.machine} onChange={set("machine")}>
            <option value="">{t("plan.choose")}</option>
            {board.machines.map((m) => (
              <option key={m.code} value={m.code}>
                {m.code} {m.name}
              </option>
            ))}
          </select>
        </label>
        {unsupervised && (
          <p className="warning-text wide" role="status">
            {t("plan.noSupervisor", { section: unsupervised.section })}
          </p>
        )}
        <label>
          {t("plan.plannedMinutes")}
          <input inputMode="numeric" value={values.minutes} onChange={set("minutes")} placeholder={t("plan.wholeShift")} />
        </label>
        <div className="wide row-actions">
          <button type="submit" disabled={save.isPending}>
            {moving ? t("plan.saveMove") : t("plan.save")}
          </button>
          {moving && (
            <button type="button" className="secondary" onClick={onDone}>
              {t("plan.cancelMove")}
            </button>
          )}
        </div>
        <div className="wide">
          <ErrorLine error={save.error} />
        </div>
      </form>
    </section>
  );
}

function Orders({ board }: { board: PlanBoard }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("plan.orders")}>
      <h2>{t("plan.orders")}</h2>
      {board.orders.length === 0 ? (
        <p className="muted">{t("plan.noOrders")}</p>
      ) : (
        <div className="table-wrap">
          <table aria-label={t("plan.orders")}>
            <thead>
              <tr>
                <th>{t("plan.order")}</th>
                <th>{t("plan.mould")}</th>
                <th className="num">{t("plan.quantity")}</th>
                <th className="num">{t("plan.planned")}</th>
                <th>{t("plan.firstDue")}</th>
              </tr>
            </thead>
            <tbody>
              {board.orders.map((o) => (
                <tr key={o.id}>
                  <td>
                    {o.number} <span className="muted small">{o.item}</span>
                  </td>
                  <td>{o.mould}</td>
                  <td className="num">{formatDecimal(o.quantity)}</td>
                  <td className="num">{formatDecimal(o.planned)}</td>
                  <td>{o.first_due}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function CopyDay() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const copy = useMutation({
    mutationFn: () => copyDay(source, target),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: planKey }),
  });
  return (
    <section className="panel" aria-label={t("plan.copy")}>
      <h2>{t("plan.copy")}</h2>
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          copy.mutate();
        }}
      >
        <label>
          {t("plan.copyFrom")}
          <input type="date" value={source} onChange={(e) => setSource(e.target.value)} />
        </label>
        <label>
          {t("plan.copyTo")}
          <input type="date" value={target} onChange={(e) => setTarget(e.target.value)} />
        </label>
        <button type="submit" disabled={copy.isPending}>
          {t("plan.copyButton")}
        </button>
      </form>
      {copy.data && <p className="notice">{t("plan.copied", { count: copy.data.copied })}</p>}
      <ErrorLine error={copy.error} />
    </section>
  );
}
