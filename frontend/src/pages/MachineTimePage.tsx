import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  duration,
  finishJob,
  getBoard,
  getRecent,
  getStartOptions,
  machineJobsKey,
  startJob,
  type BoardMachine,
  type MachineJob,
} from "../api/machineJobs";
import ScanButton from "../components/ScanButton";
import { formatDateTime, formatTime } from "../lib/time";

const REFRESH_MS = 60_000;

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.detail ? error.detail : fallback;
}

/** Minutes from a start to now, counting up while the page is open. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

export function runningMinutes(job: MachineJob, now: number): number {
  return Math.max(job.minutes, Math.floor((now - new Date(job.started_at).getTime()) / 60_000));
}

function what(job: MachineJob): string {
  return job.kind === "job" ? `${job.job}/${job.operation} ${job.operation_name ?? ""}` : `${job.order} · ${job.mould ?? ""}`;
}

/** Machine time (P3-24; owner, 15 Nov 2026): the Production Team Leader starts and finishes
 * jobs at the machine. Made for a phone, in English and Sinhala. The machines of the
 * person's own sections only (the server decides). */
export default function MachineTimePage() {
  const { t } = useTranslation();
  const board = useQuery({ queryKey: [...machineJobsKey, "board"], queryFn: getBoard, refetchInterval: REFRESH_MS });
  const recent = useQuery({ queryKey: [...machineJobsKey, "recent"], queryFn: getRecent });
  const now = useNow();
  const [starting, setStarting] = useState<string | null>(null);
  const [finishing, setFinishing] = useState<MachineJob | null>(null);
  const d = board.data;

  return (
    <div className="page shop-floor">
      <h1>{t("mt.title")}</h1>
      <p className="muted">{t("mt.help")}</p>
      {board.isError && <p className="form-error">{t("common.error")}</p>}
      {d && d.machines.length === 0 && <p className="muted">{t("mt.noMachines")}</p>}
      {d && (
        <div className="tiles machine-tiles">
          {d.machines.map((m) => (
            <MachineTile
              key={m.code}
              machine={m}
              now={now}
              canEnter={d.can_enter}
              canAllowSecond={d.can_allow_second}
              onStart={() => {
                setFinishing(null);
                setStarting(m.code);
              }}
              onFinish={(job) => {
                setStarting(null);
                setFinishing(job);
              }}
            />
          ))}
        </div>
      )}

      {starting && d && (
        <StartForm key={starting} machine={d.machines.find((m) => m.code === starting)!} onDone={() => setStarting(null)} />
      )}
      {finishing && <FinishForm key={finishing.id} job={finishing} onDone={() => setFinishing(null)} />}

      <section className="panel" aria-label={t("mt.recent")}>
        <h2>{t("mt.recent")}</h2>
        {recent.data && recent.data.results.length === 0 && <p className="muted">{t("mt.none")}</p>}
        {recent.data && recent.data.results.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("mt.machine")}</th>
                  <th>{t("mt.job")}</th>
                  <th>{t("mt.started")}</th>
                  <th>{t("mt.finished")}</th>
                  <th>{t("mt.time")}</th>
                  <th>{t("mt.output")}</th>
                </tr>
              </thead>
              <tbody>
                {recent.data.results.map((j) => (
                  <tr key={j.id}>
                    <td>{j.machine}</td>
                    <td>
                      {what(j)}
                      {j.drawing_no && <span className="muted"> · {t("mt.drawingShort", { no: j.drawing_no })}</span>}
                    </td>
                    <td className="nowrap">{formatDateTime(j.started_at)}</td>
                    <td className="nowrap">{j.ended_at ? formatDateTime(j.ended_at) : t("mt.running")}</td>
                    <td className="nowrap">{duration(j.ended_at ? j.minutes : runningMinutes(j, now))}</td>
                    <td>
                      {j.kind === "job" && j.completed !== null && t("mt.pieces", { completed: j.completed, rejected: j.rejected ?? "0" })}
                      {j.kind === "moulding" &&
                        j.end_counter !== null &&
                        t("mt.shots", { n: String(j.end_counter - (j.start_counter ?? 0)) })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function MachineTile({
  machine,
  now,
  canEnter,
  canAllowSecond,
  onStart,
  onFinish,
}: {
  machine: BoardMachine;
  now: number;
  canEnter: boolean;
  canAllowSecond: boolean;
  onStart: () => void;
  onFinish: (job: MachineJob) => void;
}) {
  const { t } = useTranslation();
  const startable = canEnter && machine.status !== "maintenance" && (machine.status === "idle" || canAllowSecond);
  return (
    <article className={`tile machine-tile ${machine.status}`} aria-label={t("mt.machineLabel", { code: machine.code })}>
      <strong>
        {machine.code} <span className="muted">{machine.name}</span>
      </strong>
      <span className={`machine-status ${machine.status}`}>{t(`mt.status.${machine.status}`)}</span>
      {machine.jobs.map((j) => (
        <div key={j.id} className="machine-job">
          <span>{what(j)}</span>
          <span className="muted">{t("mt.since", { time: formatTime(j.started_at), duration: duration(runningMinutes(j, now)) })}</span>
          {j.operator && <span className="muted">{t("mt.operatorIs", { name: j.operator })}</span>}
          {canEnter && (
            <button type="button" onClick={() => onFinish(j)}>
              {t("mt.finish")}
            </button>
          )}
        </div>
      ))}
      {startable && (
        <button type="button" className={machine.status === "running" ? "secondary" : ""} onClick={onStart}>
          {machine.status === "running" ? t("mt.startSecond") : t("mt.start")}
        </button>
      )}
    </article>
  );
}

function useDone(onDone: () => void) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: machineJobsKey });
    onDone();
  };
}

function StartForm({ machine, onDone }: { machine: BoardMachine; onDone: () => void }) {
  const { t } = useTranslation();
  const done = useDone(onDone);
  const options = useQuery({ queryKey: [...machineJobsKey, "options", machine.code], queryFn: () => getStartOptions(machine.code) });
  const [card, setCard] = useState("");
  const [order, setOrder] = useState("");
  const [mould, setMould] = useState("");
  const [counter, setCounter] = useState("");
  const [drawing, setDrawing] = useState<string | null>(null);
  const [description, setDescription] = useState("");
  const [operator, setOperator] = useState("");
  const [notes, setNotes] = useState("");
  const [reason, setReason] = useState("");
  const moulding = machine.section_type === "moulding";
  const jobNo = card.split("/")[0];
  const chosenJob = options.data?.jobs.find((j) => j.number === jobNo);
  const start = useMutation({
    mutationFn: () => {
      const values: Record<string, string> = { machine: machine.code, description, operator, notes };
      if (moulding) Object.assign(values, { order, mould, start_counter: counter });
      else values.job = card;
      if (!moulding && drawing !== null) values.drawing_no = drawing;
      if (machine.status === "running") values.second_reason = reason;
      return startJob(values);
    },
    onSuccess: done,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    start.mutate();
  }

  return (
    <section className="panel" aria-label={t("mt.startTitle", { code: machine.code })}>
      <h2>{t("mt.startTitle", { code: machine.code })}</h2>
      <form className="form-grid" onSubmit={submit}>
        {!moulding && (
          <>
            <label className="wide">
              {t("mt.jobCard")}
              <select value={card} required onChange={(e) => setCard(e.target.value)}>
                <option value="">{t("mt.choose")}</option>
                {options.data?.jobs.map((j) => (
                  <optgroup key={j.number} label={`${j.number} ${j.item} ${j.description}`.trim()}>
                    {j.operations.map((op) => (
                      <option key={op.card} value={op.card}>
                        {op.card} {op.name}
                        {op.here ? ` ★` : ""}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </label>
            <ScanButton label={t("mt.scanCard")} onScan={(code) => setCard(code.trim().toUpperCase())} />
            <label>
              {t("mt.drawing")}
              <input value={drawing ?? chosenJob?.drawing_no ?? ""} onChange={(e) => setDrawing(e.target.value)} />
            </label>
          </>
        )}
        {moulding && (
          <>
            <label className="wide">
              {t("mt.order")}
              <select
                value={order}
                required
                onChange={(e) => {
                  setOrder(e.target.value);
                  setMould(options.data?.orders.find((o) => o.number === e.target.value)?.mould ?? "");
                }}
              >
                <option value="">{t("mt.choose")}</option>
                {options.data?.orders.map((o) => (
                  <option key={o.number} value={o.number}>
                    {o.number} {o.item}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("mt.mould")}
              <input value={mould} onChange={(e) => setMould(e.target.value.toUpperCase())} />
            </label>
            <label>
              {t("mt.startCounter")}
              <input inputMode="numeric" value={counter} required onChange={(e) => setCounter(e.target.value)} />
            </label>
          </>
        )}
        <label className="wide">
          {t("mt.description")}
          <input value={description} placeholder={t("mt.descriptionHint")} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label>
          {t("mt.operator")}
          <input value={operator} placeholder={t("mt.operatorHint")} onChange={(e) => setOperator(e.target.value)} />
        </label>
        <label className="wide">
          {t("mt.notes")}
          <input value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        {machine.status === "running" && (
          <label className="wide">
            {t("mt.secondReason")}
            <input value={reason} required onChange={(e) => setReason(e.target.value)} />
          </label>
        )}
        {start.isError && (
          <p className="form-error wide" role="alert">
            {errorText(start.error, t("common.error"))}
          </p>
        )}
        <div className="row-actions wide">
          <button type="submit" disabled={start.isPending}>
            {t("mt.start")}
          </button>
          <button type="button" className="secondary" onClick={onDone}>
            {t("common.cancel")}
          </button>
        </div>
      </form>
    </section>
  );
}

function FinishForm({ job, onDone }: { job: MachineJob; onDone: () => void }) {
  const { t } = useTranslation();
  const done = useDone(onDone);
  const [completed, setCompleted] = useState("");
  const [rejected, setRejected] = useState("");
  const [counter, setCounter] = useState("");
  const [notes, setNotes] = useState("");
  const finish = useMutation({
    mutationFn: () => finishJob(job.id, job.kind === "job" ? { completed, rejected, notes } : { end_counter: counter, notes }),
    onSuccess: done,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    finish.mutate();
  }

  return (
    <section className="panel" aria-label={t("mt.finishTitle", { code: job.machine })}>
      <h2>{t("mt.finishTitle", { code: job.machine })}</h2>
      <p>{what(job)}</p>
      <form className="form-grid" onSubmit={submit}>
        {job.kind === "job" ? (
          <>
            <label>
              {t("mt.completed")}
              <input inputMode="decimal" value={completed} required onChange={(e) => setCompleted(e.target.value)} />
            </label>
            <label>
              {t("mt.rejected")}
              <input inputMode="decimal" value={rejected} onChange={(e) => setRejected(e.target.value)} />
            </label>
          </>
        ) : (
          <label>
            {t("mt.endCounter")}
            <input inputMode="numeric" value={counter} required onChange={(e) => setCounter(e.target.value)} />
          </label>
        )}
        <label className="wide">
          {t("mt.notes")}
          <input value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        {finish.isError && (
          <p className="form-error wide" role="alert">
            {errorText(finish.error, t("common.error"))}
          </p>
        )}
        <div className="row-actions wide">
          <button type="submit" disabled={finish.isPending}>
            {t("mt.finish")}
          </button>
          <button type="button" className="secondary" onClick={onDone}>
            {t("common.cancel")}
          </button>
        </div>
      </form>
    </section>
  );
}
