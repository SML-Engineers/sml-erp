import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  addHoliday,
  addLeaveType,
  changeLeaveType,
  holidaysKey,
  leaveTypesKey,
  listHolidays,
  listLeaveTypes,
  removeHoliday,
  type LeaveType,
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

/** Holidays and leave types (P2B-03), kept by HR. */
export default function HolidaysPage() {
  const { t } = useTranslation();
  const [year, setYear] = useState(new Date().getFullYear());
  return (
    <main className="page">
      <h1>{t("hol.title")}</h1>
      <p className="muted">{t("hol.help")}</p>
      <div className="toolbar">
        <button type="button" className="secondary" onClick={() => setYear((y) => y - 1)}>
          ← {year - 1}
        </button>
        <strong>{year}</strong>
        <button type="button" className="secondary" onClick={() => setYear((y) => y + 1)}>
          {year + 1} →
        </button>
      </div>
      <Holidays year={year} />
      <LeaveTypes />
    </main>
  );
}

function Holidays({ year }: { year: number }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: [...holidaysKey, year], queryFn: () => listHolidays(year) });
  const [entry, setEntry] = useState({ date: "", name: "", kind: "public" });
  const [removing, setRemoving] = useState<number | null>(null);
  const [why, setWhy] = useState("");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: holidaysKey });
  const add = useMutation({
    mutationFn: () => addHoliday(entry),
    onSuccess: () => {
      setEntry((e) => ({ ...e, date: "", name: "" }));
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: () => removeHoliday(removing!, why),
    onSuccess: () => {
      setRemoving(null);
      setWhy("");
      refresh();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  const data = list.data;
  return (
    <section className="panel" aria-label={t("hol.holidays")}>
      <h2>
        {t("hol.holidays")} {year}
      </h2>
      <ErrorLine error={list.error} />
      {data && (
        <div className="table-wrap">
          <table aria-label={t("hol.holidays")}>
            <thead>
              <tr>
                <th>{t("hol.date")}</th>
                <th>{t("hol.name")}</th>
                <th>{t("hol.kind")}</th>
                {data.can_manage && <th />}
              </tr>
            </thead>
            <tbody>
              {data.results.length === 0 && (
                <tr>
                  <td colSpan={4} className="muted">
                    {t("hol.none")}
                  </td>
                </tr>
              )}
              {data.results.map((h) => (
                <tr key={h.id}>
                  <td>{h.date}</td>
                  <td>{h.name}</td>
                  <td>{h.kind_label}</td>
                  {data.can_manage && (
                    <td>
                      {h.can_remove && (
                        <button type="button" className="small secondary" onClick={() => setRemoving(h.id)}>
                          {t("hol.remove")}
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {removing !== null && (
        <div className="inline-form">
          <label>
            {t("hol.removeReason")}
            <input value={why} onChange={(e) => setWhy(e.target.value)} />
          </label>
          <button type="button" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {t("hol.confirmRemove")}
          </button>
          <button type="button" className="secondary" onClick={() => setRemoving(null)}>
            {t("hol.cancel")}
          </button>
          <ErrorLine error={remove.error} />
        </div>
      )}
      {data?.can_manage && (
        <form className="inline-form" aria-label={t("hol.add")} onSubmit={submit}>
          <label>
            {t("hol.date")}
            <input type="date" value={entry.date} onChange={(e) => setEntry({ ...entry, date: e.target.value })} />
          </label>
          <label>
            {t("hol.name")}
            <input value={entry.name} onChange={(e) => setEntry({ ...entry, name: e.target.value })} />
          </label>
          <label>
            {t("hol.kind")}
            <select value={entry.kind} onChange={(e) => setEntry({ ...entry, kind: e.target.value })}>
              {data.kinds.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={add.isPending}>
            {t("hol.add")}
          </button>
          <ErrorLine error={add.error} />
        </form>
      )}
    </section>
  );
}

function LeaveTypes() {
  const { t } = useTranslation();
  const list = useQuery({ queryKey: leaveTypesKey, queryFn: listLeaveTypes });
  const [editing, setEditing] = useState<LeaveType | "new" | null>(null);
  const data = list.data;
  return (
    <section className="panel" aria-label={t("lt.title")}>
      <h2>{t("lt.title")}</h2>
      <p className="muted">{t("lt.help")}</p>
      <ErrorLine error={list.error} />
      {data && (
        <div className="table-wrap">
          <table aria-label={t("lt.title")}>
            <thead>
              <tr>
                <th>{t("lt.code")}</th>
                <th>{t("lt.name")}</th>
                <th>{t("lt.rule")}</th>
                <th className="num">{t("lt.days")}</th>
                <th>{t("lt.wb")}</th>
                <th className="num">{t("lt.maxDays")}</th>
                <th>{t("lt.paid")}</th>
                <th className="num">{t("lt.carry")}</th>
                {data.can_manage && <th />}
              </tr>
            </thead>
            <tbody>
              {data.results.map((k) => (
                <tr key={k.id}>
                  <td className="mono">{k.code}</td>
                  <td>
                    {k.name}
                    {!k.is_active && <span className="tag"> {t("lt.notUsed")}</span>}
                  </td>
                  <td>{k.rule_label}</td>
                  <td className="num">{k.rule === "unlimited" ? "—" : k.days}</td>
                  <td>
                    {k.rule === "unlimited" || (!k.wb_rule && k.wb_days === null)
                      ? t("lt.same")
                      : `${data.rules.find((r) => r.value === (k.wb_rule || k.rule))?.label ?? ""}, ${k.wb_days ?? k.days}`}
                  </td>
                  <td className="num">{k.max_days ?? "—"}</td>
                  <td>{k.paid ? t("lt.yes") : t("lt.no")}</td>
                  <td className="num">{k.carry_forward_max}</td>
                  {data.can_manage && (
                    <td>
                      <button type="button" className="small secondary" onClick={() => setEditing(k)}>
                        {t("lt.change")} {k.code}
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data?.can_manage && !editing && (
        <button type="button" onClick={() => setEditing("new")}>
          {t("lt.add")}
        </button>
      )}
      {editing && data && (
        <LeaveTypeForm
          key={editing === "new" ? "new" : editing.id}
          current={editing === "new" ? null : editing}
          rules={data.rules}
          onDone={() => setEditing(null)}
        />
      )}
    </section>
  );
}

function LeaveTypeForm({
  current,
  rules,
  onDone,
}: {
  current: LeaveType | null;
  rules: { value: string; label: string }[];
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const start: Partial<LeaveType> = current ?? {
    code: "",
    name: "",
    rule: "fixed",
    days: "",
    wb_rule: "",
    wb_days: null,
    max_days: null,
    paid: true,
    carry_forward_max: "0",
  };
  const [values, setValues] = useState<Partial<LeaveType>>(start);
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => {
      if (!current) return addLeaveType(values);
      const keys = ["name", "rule", "days", "wb_rule", "wb_days", "max_days", "paid", "carry_forward_max", "is_active"] as const;
      const changed: Partial<LeaveType> = {};
      for (const k of keys) if (values[k] !== current[k]) Object.assign(changed, { [k]: values[k] });
      return changeLeaveType(current.id, changed, reason);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: leaveTypesKey });
      onDone();
    },
  });
  const set = (change: Partial<LeaveType>) => setValues((v) => ({ ...v, ...change }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form className="form-grid" aria-label={current ? t("lt.change") : t("lt.add")} onSubmit={submit}>
      <h3 className="wide">{current ? `${t("lt.change")} ${current.code}` : t("lt.add")}</h3>
      <label>
        {t("lt.code")}
        <input value={values.code ?? ""} readOnly={!!current} onChange={(e) => set({ code: e.target.value.toUpperCase() })} />
      </label>
      <label>
        {t("lt.name")}
        <input value={values.name ?? ""} onChange={(e) => set({ name: e.target.value })} />
      </label>
      <label>
        {t("lt.rule")}
        <select value={values.rule} onChange={(e) => set({ rule: e.target.value as LeaveType["rule"] })}>
          {rules.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </label>
      {values.rule !== "unlimited" && (
        <>
          <label>
            {t("lt.days")}
            <input inputMode="decimal" value={values.days ?? ""} onChange={(e) => set({ days: e.target.value })} />
          </label>
          <label>
            {t("lt.carry")}
            <input
              inputMode="decimal"
              value={values.carry_forward_max ?? ""}
              onChange={(e) => set({ carry_forward_max: e.target.value })}
            />
          </label>
        </>
      )}
      {values.rule !== "unlimited" && (
        <>
          <label>
            {t("lt.wbRule")}
            <select value={values.wb_rule ?? ""} onChange={(e) => set({ wb_rule: e.target.value as LeaveType["wb_rule"] })}>
              <option value="">{t("lt.same")}</option>
              {rules
                .filter((r) => r.value !== "unlimited")
                .map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
            </select>
          </label>
          <label>
            {t("lt.wbDays")}
            <input
              inputMode="decimal"
              placeholder={t("lt.same")}
              value={values.wb_days ?? ""}
              onChange={(e) => set({ wb_days: e.target.value || null })}
            />
          </label>
        </>
      )}
      <label>
        {t("lt.maxDays")}
        <input
          inputMode="decimal"
          placeholder={t("lt.noLimit")}
          value={values.max_days ?? ""}
          onChange={(e) => set({ max_days: e.target.value || null })}
        />
      </label>
      <label className="check">
        <input type="checkbox" checked={!!values.paid} onChange={(e) => set({ paid: e.target.checked })} /> {t("lt.paid")}
      </label>
      {current && (
        <label className="check">
          <input type="checkbox" checked={!!values.is_active} onChange={(e) => set({ is_active: e.target.checked })} />{" "}
          {t("lt.inUse")}
        </label>
      )}
      {current && (
        <label className="wide">
          {t("lt.reason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      )}
      <div className="wide row-actions">
        <button type="submit" disabled={save.isPending}>
          {t("lt.save")}
        </button>
        <button type="button" className="secondary" onClick={onDone}>
          {t("hol.cancel")}
        </button>
      </div>
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}
