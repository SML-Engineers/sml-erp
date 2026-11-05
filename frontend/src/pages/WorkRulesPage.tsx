import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { addWorkRule, listWorkRules, withdrawWorkRule, workRulesKey } from "../api/overtime";
import PayPeriodLine from "../components/PayPeriodLine";
import { addPayPeriod, listPayPeriods, payPeriodsKey, withdrawPayPeriod } from "../api/periods";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

const FIELDS = [
  "normal_day_minutes",
  "grace_minutes",
  "short_leaves_per_month",
  "short_leave_minutes",
  "ot_min_minutes",
  "ot_step_minutes",
  "rate_working_day",
  "rate_sunday",
  "rate_holiday",
  "hourly_divisor",
] as const;

/** Work rules (P2B-05): each division's dated working-time and overtime rules, kept by HR. */
export default function WorkRulesPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: workRulesKey, queryFn: listWorkRules });
  const [values, setValues] = useState<Record<string, string>>({});
  const [withdrawing, setWithdrawing] = useState<number | null>(null);
  const [why, setWhy] = useState("");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: workRulesKey });
  const add = useMutation({
    mutationFn: () => addWorkRule(values),
    onSuccess: () => {
      setValues({});
      refresh();
    },
  });
  const withdraw = useMutation({
    mutationFn: () => withdrawWorkRule(withdrawing!, why),
    onSuccess: () => {
      setWithdrawing(null);
      setWhy("");
      refresh();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  const d = list.data;
  return (
    <main className="page">
      <h1>{t("wr.title")}</h1>
      <p className="muted">{t("wr.help")}</p>
      <PayPeriodPanel />
      <ErrorLine error={list.error} />
      {d && (
        <div className="table-wrap">
          <table aria-label={t("wr.title")}>
            <thead>
              <tr>
                <th>{t("att.division")}</th>
                <th>{t("wr.from")}</th>
                {FIELDS.map((f) => (
                  <th key={f} className="num">
                    {t(`wr.f.${f}`)}
                  </th>
                ))}
                <th>{t("wr.f.short_leave_paid_wb")}</th>
                <th>{t("wr.reason")}</th>
                {d.can_manage && <th />}
              </tr>
            </thead>
            <tbody>
              {d.results.map((r) => (
                <tr key={r.id}>
                  <td>{r.division}</td>
                  <td>{r.effective_from}</td>
                  {FIELDS.map((f) => (
                    <td key={f} className="num">
                      {r[f]}
                    </td>
                  ))}
                  <td>{r.short_leave_paid_wb ? t("wr.yes") : t("wr.no")}</td>
                  <td>{r.reason}</td>
                  {d.can_manage && (
                    <td>
                      {r.can_withdraw && (
                        <button type="button" className="small secondary" onClick={() => setWithdrawing(r.id)}>
                          {t("wr.withdraw")}
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
      {withdrawing !== null && (
        <div className="inline-form">
          <label>
            {t("wr.withdrawReason")}
            <input value={why} onChange={(e) => setWhy(e.target.value)} />
          </label>
          <button type="button" disabled={withdraw.isPending} onClick={() => withdraw.mutate()}>
            {t("wr.confirmWithdraw")}
          </button>
          <ErrorLine error={withdraw.error} />
        </div>
      )}
      {d?.can_manage && (
        <form className="panel form-grid" aria-label={t("wr.add")} onSubmit={submit}>
          <h2 className="wide">{t("wr.add")}</h2>
          <label>
            {t("att.division")}
            <select value={values.division ?? ""} onChange={(e) => setValues({ ...values, division: e.target.value })}>
              <option value="">—</option>
              {d.divisions.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("wr.from")}
            <input
              type="month"
              value={values.effective_from ?? ""}
              onChange={(e) => setValues({ ...values, effective_from: e.target.value })}
            />
          </label>
          {FIELDS.map((f) => (
            <label key={f}>
              {t(`wr.f.${f}`)}
              <input
                inputMode="decimal"
                placeholder={t("wr.same")}
                value={values[f] ?? ""}
                onChange={(e) => setValues({ ...values, [f]: e.target.value })}
              />
            </label>
          ))}
          <label>
            {t("wr.f.short_leave_paid_wb")}
            <select
              value={values.short_leave_paid_wb ?? ""}
              onChange={(e) => setValues({ ...values, short_leave_paid_wb: e.target.value })}
            >
              <option value="">{t("wr.same")}</option>
              <option value="true">{t("wr.yes")}</option>
              <option value="false">{t("wr.no")}</option>
            </select>
          </label>
          <label className="wide">
            {t("wr.reason")}
            <input value={values.reason ?? ""} onChange={(e) => setValues({ ...values, reason: e.target.value })} />
          </label>
          <p className="muted wide">{t("wr.addHelp")}</p>
          <div className="wide row-actions">
            <button type="submit" disabled={add.isPending}>
              {t("wr.save")}
            </button>
          </div>
          <div className="wide">
            <ErrorLine error={add.error} />
          </div>
        </form>
      )}
    </main>
  );
}

/** The pay period (P2B-15): the day each pay month starts, dated, kept by HR. */
function PayPeriodPanel() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: payPeriodsKey, queryFn: listPayPeriods });
  const [values, setValues] = useState<Record<string, string>>({});
  const [withdrawing, setWithdrawing] = useState<number | null>(null);
  const [why, setWhy] = useState("");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: payPeriodsKey });
  const add = useMutation({
    mutationFn: () => addPayPeriod(values),
    onSuccess: () => {
      setValues({});
      refresh();
    },
  });
  const withdraw = useMutation({
    mutationFn: () => withdrawPayPeriod(withdrawing!, why),
    onSuccess: () => {
      setWithdrawing(null);
      setWhy("");
      refresh();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  const d = list.data;
  return (
    <section className="panel" aria-label={t("pp.title")}>
      <h2>{t("pp.title")}</h2>
      <p className="muted">{t("pp.help")}</p>
      <ErrorLine error={list.error} />
      {d && (
        <>
          <PayPeriodLine period={d.current} />
          <div className="table-wrap">
            <table aria-label={t("pp.title")}>
              <thead>
                <tr>
                  <th>{t("pp.from")}</th>
                  <th className="num">{t("pp.startDay")}</th>
                  <th>{t("pp.reason")}</th>
                  {d.can_manage && <th />}
                </tr>
              </thead>
              <tbody>
                {d.results.map((r) => (
                  <tr key={r.id}>
                    <td>{r.effective_from}</td>
                    <td className="num">{r.start_day}</td>
                    <td>{r.reason}</td>
                    {d.can_manage && (
                      <td>
                        {r.can_withdraw && (
                          <button type="button" className="small secondary" onClick={() => setWithdrawing(r.id)}>
                            {t("pp.withdraw")}
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {withdrawing !== null && (
        <div className="inline-form">
          <label>
            {t("pp.withdrawReason")}
            <input value={why} onChange={(e) => setWhy(e.target.value)} />
          </label>
          <button type="button" disabled={withdraw.isPending} onClick={() => withdraw.mutate()}>
            {t("pp.confirmWithdraw")}
          </button>
          <ErrorLine error={withdraw.error} />
        </div>
      )}
      {d?.can_manage && (
        <form className="form-grid" aria-label={t("pp.add")} onSubmit={submit}>
          <h3 className="wide">{t("pp.add")}</h3>
          <label>
            {t("pp.from")}
            <input
              type="month"
              value={values.effective_from ?? ""}
              onChange={(e) => setValues({ ...values, effective_from: e.target.value })}
            />
          </label>
          <label>
            {t("pp.startDay")}
            <input
              inputMode="numeric"
              value={values.start_day ?? ""}
              onChange={(e) => setValues({ ...values, start_day: e.target.value })}
            />
          </label>
          <label className="wide">
            {t("pp.reason")}
            <input value={values.reason ?? ""} onChange={(e) => setValues({ ...values, reason: e.target.value })} />
          </label>
          <p className="muted wide">
            {t("pp.startDayHelp")} {t("pp.addHelp")}
          </p>
          <div className="wide row-actions">
            <button type="submit" disabled={add.isPending}>
              {t("pp.save")}
            </button>
          </div>
          <div className="wide">
            <ErrorLine error={add.error} />
          </div>
        </form>
      )}
    </section>
  );
}
