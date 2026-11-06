import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  decideGratuity,
  getGratuity,
  gratuityKey,
  proposeGratuity,
  type GratuityList,
  type GratuityRow,
  type GratuitySetting,
} from "../api/gratuity";
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

/** P2B-19: gratuity per employee (the Payment of Gratuity Act unless settings are approved). */
export default function GratuityPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const found = useQuery({ queryKey: gratuityKey, queryFn: getGratuity });
  const [editing, setEditing] = useState<GratuityRow | null>(null);
  const done = (d: GratuityList) => {
    queryClient.setQueryData(gratuityKey, d);
    setEditing(null);
  };
  const d = found.data;
  const total = d?.results.reduce((sum, r) => sum + Number(r.liability), 0) ?? 0;
  return (
    <main className="page">
      <h1>{t("gratuity.title")}</h1>
      <p className="muted">{t("gratuity.help")}</p>
      <ErrorLine error={found.error} />
      {d && (
        <>
          <p>{t("gratuity.total", { amount: formatDecimal(total.toFixed(2)) })}</p>
          <div className="table-wrap">
            <table aria-label={t("gratuity.title")}>
              <thead>
                <tr>
                  <th>{t("gratuity.employee")}</th>
                  <th>{t("gratuity.serviceFrom")}</th>
                  <th className="num">{t("gratuity.years")}</th>
                  <th>{t("gratuity.terms")}</th>
                  <th className="num">{t("gratuity.wage")}</th>
                  <th className="num">{t("gratuity.liability")}</th>
                  <th className="num">{t("gratuity.provided")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {d.results.map((r) => (
                  <tr key={r.id}>
                    <td>
                      {r.number} {r.name} <span className="muted">{r.division}</span>
                    </td>
                    <td>{r.service_from}</td>
                    <td className="num">{r.years}</td>
                    <td>
                      {r.by_act ? t("gratuity.act") : t("gratuity.own", { months: r.months_per_year, years: r.after_years })}
                      {r.waiting && <Waiting setting={r.waiting} onDone={done} />}
                    </td>
                    <td className="num">{formatDecimal(r.wage)}</td>
                    <td className="num">{formatDecimal(r.liability)}</td>
                    <td className="num">{formatDecimal(r.provided)}</td>
                    <td>
                      {d.can_enter && !r.waiting && (
                        <button type="button" className="small secondary" onClick={() => setEditing(r)}>
                          {t("gratuity.change")}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {editing && <Propose row={editing} onDone={done} onCancel={() => setEditing(null)} />}
    </main>
  );
}

function Waiting({ setting: s, onDone }: { setting: GratuitySetting; onDone: (d: GratuityList) => void }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const act = useMutation({
    mutationFn: (action: "approve" | "reject" | "withdraw") => decideGratuity(s.id, action, reason),
    onSuccess: onDone,
  });
  return (
    <div className="notice">
      {t("gratuity.waiting", {
        from: s.effective_from,
        months: s.months_per_year,
        years: s.after_years,
        service: s.service_from,
        by: s.created_by,
      })}
      <div className="muted">{s.reason}</div>
      {(s.can_approve || s.can_withdraw) && (
        <div className="row-actions">
          <input aria-label={t("gratuity.reason")} placeholder={t("gratuity.reason")} value={reason} onChange={(e) => setReason(e.target.value)} />
          {s.can_approve && (
            <>
              <button type="button" className="small" onClick={() => act.mutate("approve")}>
                {t("gratuity.approve")}
              </button>
              <button type="button" className="small secondary" onClick={() => act.mutate("reject")}>
                {t("gratuity.reject")}
              </button>
            </>
          )}
          {s.can_withdraw && (
            <button type="button" className="small secondary" onClick={() => act.mutate("withdraw")}>
              {t("gratuity.withdraw")}
            </button>
          )}
        </div>
      )}
      <ErrorLine error={act.error} />
    </div>
  );
}

function Propose({ row, onDone, onCancel }: { row: GratuityRow; onDone: (d: GratuityList) => void; onCancel: () => void }) {
  const { t } = useTranslation();
  const [values, setValues] = useState({
    effective_from: "",
    service_from: row.service_from,
    months_per_year: row.months_per_year,
    after_years: String(row.after_years),
    reason: "",
  });
  const save = useMutation({ mutationFn: () => proposeGratuity({ employee_id: row.id, ...values }), onSuccess: onDone });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const set = (key: keyof typeof values) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  return (
    <section className="panel" aria-label={t("gratuity.form", { name: row.name })}>
      <h2>{t("gratuity.form", { name: `${row.number} ${row.name}` })}</h2>
      <p className="muted">{t("gratuity.formHelp")}</p>
      <form className="form-grid" onSubmit={submit}>
        <label>
          {t("gratuity.from")}
          <input type="month" value={values.effective_from} onChange={set("effective_from")} />
        </label>
        <label>
          {t("gratuity.serviceFrom")}
          <input type="date" value={values.service_from} onChange={set("service_from")} />
        </label>
        <label>
          {t("gratuity.monthsPerYear")}
          <input inputMode="decimal" value={values.months_per_year} onChange={set("months_per_year")} />
        </label>
        <label>
          {t("gratuity.afterYears")}
          <input inputMode="numeric" value={values.after_years} onChange={set("after_years")} />
        </label>
        <label className="wide">
          {t("gratuity.reason")}
          <input value={values.reason} onChange={set("reason")} />
        </label>
        <div className="wide row-actions">
          <button type="submit" disabled={save.isPending}>
            {t("gratuity.send")}
          </button>
          <button type="button" className="secondary" onClick={onCancel}>
            {t("common.cancel")}
          </button>
        </div>
        <div className="wide">
          <ErrorLine error={save.error} />
        </div>
      </form>
    </section>
  );
}
