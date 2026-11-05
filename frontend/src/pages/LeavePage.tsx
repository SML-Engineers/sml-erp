import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import { listEmployees } from "../api/employees";
import {
  grantLeaveYear,
  leaveAction,
  leaveKey,
  listLeave,
  recordLeave,
  type LeaveEntry,
  type LeaveList,
  type LeaveRecord,
} from "../api/leave";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** Leave (P2B-03): HR records leave, approves leave applied for and grants each year's leave. */
export default function LeavePage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const year = Number(params.get("year")) || new Date().getFullYear();
  const query = new URLSearchParams(params);
  query.set("year", String(year));
  const list = useQuery({ queryKey: [...leaveKey, query.toString()], queryFn: () => listLeave(query.toString()) });
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const data = list.data;
  return (
    <main className="page">
      <h1>{t("leave.title")}</h1>
      <p className="muted">{t("leave.help")}</p>
      <div className="toolbar">
        <label>
          {t("leave.year")}
          <input
            inputMode="numeric"
            value={params.get("year") ?? String(year)}
            onChange={(e) => set("year", e.target.value.replace(/\D/g, "").slice(0, 4))}
          />
        </label>
        <label>
          {t("table.search")}
          <input value={params.get("q") ?? ""} onChange={(e) => set("q", e.target.value)} />
        </label>
        <label>
          {t("leave.status")}
          <select value={params.get("status") ?? ""} onChange={(e) => set("status", e.target.value)}>
            <option value="">{t("table.all")}</option>
            {(["applied", "approved", "rejected", "cancelled"] as const).map((s) => (
              <option key={s} value={s}>
                {t(`leave.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {data?.can_record && <GrantYear year={year} />}
      {data?.can_record && <RecordLeave data={data} />}
      <ErrorLine error={list.error} />
      {data && <LeaveTable rows={data.results} />}
    </main>
  );
}

function GrantYear({ year }: { year: number }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const grant = useMutation({
    mutationFn: () => grantLeaveYear(year),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["employees"] }),
  });
  return (
    <section className="panel" aria-label={t("leave.grant")}>
      <h2>{t("leave.grant")}</h2>
      <p className="muted">{t("leave.grantHelp")}</p>
      <button type="button" disabled={grant.isPending} onClick={() => grant.mutate()}>
        {t("leave.grantButton", { year })}
      </button>
      {grant.data && (
        <p className="notice" role="status">
          {t("leave.granted", grant.data)}
        </p>
      )}
      <ErrorLine error={grant.error} />
    </section>
  );
}

function RecordLeave({ data }: { data: LeaveList }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const people = useQuery({ queryKey: ["employees", "status=active"], queryFn: () => listEmployees("status=active") });
  const empty: LeaveEntry = { employee: 0, leave_type: "", start: "", end: "", half_day: false, reason: "" };
  const [entry, setEntry] = useState<LeaveEntry>(empty);
  const save = useMutation({
    mutationFn: () => recordLeave(entry),
    onSuccess: () => {
      setEntry(empty);
      void queryClient.invalidateQueries({ queryKey: leaveKey });
    },
  });
  const set = (change: Partial<LeaveEntry>) => setEntry((e) => ({ ...e, ...change }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form className="panel form-grid" aria-label={t("leave.record")} onSubmit={submit}>
      <h2 className="wide">{t("leave.record")}</h2>
      <label>
        {t("leave.employee")}
        <select value={entry.employee || ""} onChange={(e) => set({ employee: Number(e.target.value) })}>
          <option value="">—</option>
          {people.data?.results.map((p) => (
            <option key={p.id} value={p.id}>
              {p.number} {p.full_name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("leave.type")}
        <select value={entry.leave_type} onChange={(e) => set({ leave_type: e.target.value })}>
          <option value="">—</option>
          {data.types.map((k) => (
            <option key={k.code} value={k.code}>
              {k.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("leave.from")}
        <input type="date" value={entry.start} onChange={(e) => set({ start: e.target.value })} />
      </label>
      {!entry.half_day && (
        <label>
          {t("leave.to")}
          <input type="date" value={entry.end} onChange={(e) => set({ end: e.target.value })} />
        </label>
      )}
      <label className="check">
        <input
          type="checkbox"
          checked={entry.half_day}
          onChange={(e) => set({ half_day: e.target.checked, end: "" })}
        />{" "}
        {t("leave.halfDay")}
      </label>
      <label>
        {t("leave.reason")}
        <input value={entry.reason} onChange={(e) => set({ reason: e.target.value })} />
      </label>
      <p className="muted wide">{t("leave.recordHelp")}</p>
      <div className="wide row-actions">
        <button type="submit" disabled={save.isPending}>
          {t("leave.save")}
        </button>
      </div>
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

export function LeaveTable({ rows, showEmployee = true }: { rows: LeaveRecord[]; showEmployee?: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [acting, setActing] = useState<{ id: number; action: "approve" | "reject" | "cancel" } | null>(null);
  const [note, setNote] = useState("");
  const act = useMutation({
    mutationFn: () => leaveAction(acting!.id, acting!.action, note),
    onSuccess: () => {
      setActing(null);
      setNote("");
      void queryClient.invalidateQueries({ queryKey: leaveKey });
      void queryClient.invalidateQueries({ queryKey: ["employees"] });
    },
  });
  return (
    <>
      <div className="table-wrap">
        <table aria-label={t("leave.list")}>
          <thead>
            <tr>
              {showEmployee && <th>{t("leave.employee")}</th>}
              <th>{t("leave.type")}</th>
              <th>{t("leave.from")}</th>
              <th>{t("leave.to")}</th>
              <th className="num">{t("leave.days")}</th>
              <th>{t("leave.status")}</th>
              <th>{t("leave.reason")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  {t("leave.none")}
                </td>
              </tr>
            )}
            {rows.map((r) => (
              <tr key={r.id}>
                {showEmployee && (
                  <td>
                    <Link to={`/employees/${r.employee.id}`}>
                      {r.employee.number} {r.employee.name}
                    </Link>
                  </td>
                )}
                <td>{r.leave_type_name}</td>
                <td>{r.start}</td>
                <td>{r.half_day ? t("leave.half") : r.end}</td>
                <td className="num">{r.days}</td>
                <td>
                  {t(`leave.statuses.${r.status}`)}
                  {r.decision_note && <div className="muted small">{r.decision_note}</div>}
                </td>
                <td>{r.reason}</td>
                <td className="row-actions">
                  {r.can_decide && (
                    <>
                      <button type="button" className="small" onClick={() => setActing({ id: r.id, action: "approve" })}>
                        {t("leave.approve")}
                      </button>
                      <button
                        type="button"
                        className="small secondary"
                        onClick={() => setActing({ id: r.id, action: "reject" })}
                      >
                        {t("leave.reject")}
                      </button>
                    </>
                  )}
                  {r.can_cancel && (
                    <button type="button" className="small secondary" onClick={() => setActing({ id: r.id, action: "cancel" })}>
                      {t("leave.cancel")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {acting && (
        <div className="inline-form">
          <label>
            {t(acting.action === "approve" ? "leave.note" : "leave.why")}
            <input value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate()}>
            {t(`leave.confirm.${acting.action}`)}
          </button>
          <button type="button" className="secondary" onClick={() => setActing(null)}>
            {t("hol.cancel")}
          </button>
        </div>
      )}
      <ErrorLine error={act.error} />
    </>
  );
}
