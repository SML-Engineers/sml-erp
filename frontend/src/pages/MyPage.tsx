import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  applyForLeave,
  decideLeave,
  getMy,
  myCertificateUrl,
  myKey,
  myPayslipUrl,
  withdrawLeave,
  type LeaveApplication,
  type MySummary,
} from "../api/my";
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

/** Self-service on the phone (P2B-11): my payslips, contributions, leave and attendance. */
export default function MyPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const found = useQuery({ queryKey: myKey, queryFn: getMy });
  const done = (d: MySummary) => queryClient.setQueryData(myKey, { ...d, linked: d.linked ?? true });
  const d = found.data;
  return (
    <div className="page">
      <h1>{t("my.title")}</h1>
      <ErrorLine error={found.error} />
      {d && d.to_approve.length > 0 && <ToApprove items={d.to_approve} onDone={done} />}
      {d && !d.linked && <p className="muted">{d.detail}</p>}
      {d?.linked && d.employee && (
        <>
          <p className="muted">
            {d.employee.number} {d.employee.name} · {d.employee.division}
            {d.employee.section && ` · ${d.employee.section}`} · {d.employee.category}
          </p>

          <section className="panel" aria-label={t("my.payslips")}>
            <h2>{t("my.payslips")}</h2>
            {d.payslips!.length === 0 && <p className="muted">{t("my.noPayslips")}</p>}
            <ul className="plain">
              {d.payslips!.map((p) => (
                <li key={p.id}>
                  <a href={myPayslipUrl(p.id)} target="_blank" rel="noreferrer">
                    {p.month}
                  </a>{" "}
                  — {t("my.net", { net: formatDecimal(p.net) })}
                  <div className="muted">
                    {t("my.contributions", {
                      ee: formatDecimal(p.epf_employee),
                      er: formatDecimal(p.epf_employer),
                      etf: formatDecimal(p.etf),
                      apit: formatDecimal(p.apit),
                    })}
                  </div>
                </li>
              ))}
            </ul>
            <p>
              <a href={myCertificateUrl(d.tax_year!)} target="_blank" rel="noreferrer">
                {t("my.certificate", { year: d.tax_year, next: String((d.tax_year ?? 0) + 1).slice(2) })}
              </a>
            </p>
          </section>

          <section className="panel" aria-label={t("my.leave")}>
            <h2>{t("my.leave")}</h2>
            <table aria-label={t("my.balances", { year: d.leave_year })}>
              <thead>
                <tr>
                  <th>{t("my.balances", { year: d.leave_year })}</th>
                  <th className="num">{t("my.left")}</th>
                  <th className="num">{t("my.taken")}</th>
                </tr>
              </thead>
              <tbody>
                {d.balances!.map((b) => (
                  <tr key={b.code}>
                    <td>{b.name}</td>
                    <td className="num">{b.left}</td>
                    <td className="num">{b.taken}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Apply types={d.leave_types!} onDone={done} />
            <ul className="plain">
              {d.leave!.map((x) => (
                <MyLeave key={x.id} item={x} onDone={done} />
              ))}
            </ul>
          </section>

          <section className="panel" aria-label={t("my.attendance")}>
            <h2>{t("my.attendance")}</h2>
            <table aria-label={t("my.attendance")}>
              <tbody>
                {d.attendance!.days.map((a) => (
                  <tr key={a.date}>
                    <td>{a.date}</td>
                    <td>{a.leave || `${a.time_in}–${a.time_out}`}</td>
                    <td className="muted">{a.late > 0 ? t("my.late", { minutes: a.late }) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}

function MyLeave({ item: x, onDone }: { item: NonNullable<MySummary["leave"]>[number]; onDone: (d: MySummary) => void }) {
  const { t } = useTranslation();
  const withdraw = useMutation({ mutationFn: () => withdrawLeave(x.id), onSuccess: onDone });
  return (
    <li>
      {x.type}: {x.start}
      {x.end !== x.start && ` – ${x.end}`} ({x.days}) — {x.status_label}
      {x.note && <span className="muted"> ({x.note})</span>}{" "}
      {x.can_withdraw && (
        <button type="button" className="small secondary" onClick={() => withdraw.mutate()}>
          {t("my.withdraw")}
        </button>
      )}
      <ErrorLine error={withdraw.error} />
    </li>
  );
}

function Apply({ types, onDone }: { types: { code: string; name: string }[]; onDone: (d: MySummary) => void }) {
  const { t } = useTranslation();
  const empty = { leave_type: types[0]?.code ?? "", start: "", end: "", half_day: false, reason: "" };
  const [values, setValues] = useState(empty);
  const save = useMutation({
    mutationFn: () => applyForLeave(values),
    onSuccess: (d) => {
      setValues(empty);
      onDone(d);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form className="form-grid" aria-label={t("my.apply")} onSubmit={submit}>
      <h3 className="wide">{t("my.apply")}</h3>
      <label>
        {t("my.kind")}
        <select value={values.leave_type} onChange={(e) => setValues({ ...values, leave_type: e.target.value })}>
          {types.map((k) => (
            <option key={k.code} value={k.code}>
              {k.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("my.from")}
        <input type="date" value={values.start} onChange={(e) => setValues({ ...values, start: e.target.value })} />
      </label>
      <label>
        {t("my.to")}
        <input type="date" value={values.end} onChange={(e) => setValues({ ...values, end: e.target.value })} />
      </label>
      <label className="check">
        <input type="checkbox" checked={values.half_day} onChange={(e) => setValues({ ...values, half_day: e.target.checked })} />{" "}
        {t("my.halfDay")}
      </label>
      <label className="wide">
        {t("my.reason")}
        <input value={values.reason} onChange={(e) => setValues({ ...values, reason: e.target.value })} />
      </label>
      <div className="wide row-actions">
        <button type="submit" disabled={save.isPending}>
          {t("my.send")}
        </button>
      </div>
      <p className="muted wide">{t("my.applyHelp")}</p>
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function ToApprove({ items, onDone }: { items: LeaveApplication[]; onDone: (d: MySummary) => void }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("my.toApprove")}>
      <h2>{t("my.toApprove")}</h2>
      <ul className="plain">
        {items.map((x) => (
          <Decide key={x.id} item={x} onDone={onDone} />
        ))}
      </ul>
    </section>
  );
}

function Decide({ item: x, onDone }: { item: LeaveApplication; onDone: (d: MySummary) => void }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const act = useMutation({
    mutationFn: (action: "approve" | "reject") => decideLeave(x.id, action, reason),
    onSuccess: onDone,
  });
  return (
    <li>
      <strong>{x.employee}</strong>: {x.type}, {x.start}
      {x.end !== x.start && ` – ${x.end}`} ({x.days}){x.reason && ` — ${x.reason}`}
      <div className="row-actions">
        <input
          aria-label={t("my.rejectReason")}
          placeholder={t("my.rejectReason")}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
        <button type="button" className="small" onClick={() => act.mutate("approve")}>
          {t("my.approve")}
        </button>
        <button type="button" className="small secondary" onClick={() => act.mutate("reject")}>
          {t("my.reject")}
        </button>
      </div>
      <ErrorLine error={act.error} />
    </li>
  );
}
