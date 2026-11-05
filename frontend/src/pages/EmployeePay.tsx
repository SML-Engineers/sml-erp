import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { addPayAmount, employeePayKey, getEmployeePay, withdrawPayAmount, type EmployeePay as Pay } from "../api/pay";
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

/** An employee's pay (P2B-02): the amounts in force, changes to come, and the history. */
export default function EmployeePay({ employeeId }: { employeeId: number }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = employeePayKey(employeeId);
  const found = useQuery({ queryKey: key, queryFn: () => getEmployeePay(employeeId) });
  const done = (p: Pay) => queryClient.setQueryData(key, p);
  const [withdrawing, setWithdrawing] = useState<number | null>(null);
  const [why, setWhy] = useState("");
  const withdraw = useMutation({
    mutationFn: () => withdrawPayAmount(employeeId, withdrawing!, why),
    onSuccess: (p) => {
      setWithdrawing(null);
      setWhy("");
      done(p);
    },
  });
  const p = found.data;
  return (
    <section className="panel" aria-label={t("pay.title")}>
      <h2>{t("pay.title")}</h2>
      <ErrorLine error={found.error} />
      {p && (
        <>
          <div className="table-wrap">
            <table aria-label={t("pay.current")}>
              <thead>
                <tr>
                  <th>{t("pay.component")}</th>
                  <th>{t("pay.since")}</th>
                  <th>{t("pc.epf")}</th>
                  <th>{t("pc.apit")}</th>
                  <th className="num">{t("pay.amount")}</th>
                </tr>
              </thead>
              <tbody>
                {p.current.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
                      {t("pay.none")}
                    </td>
                  </tr>
                )}
                {p.current.map((x) => (
                  <tr key={x.component}>
                    <td>
                      {x.component_name}
                      {x.kind === "deduction" && <span className="tag"> {t("pc.kinds.deduction")}</span>}
                    </td>
                    <td>{x.since}</td>
                    <td>{x.epf_liable ? t("pc.yes") : "—"}</td>
                    <td>{x.apit_taxable ? t("pc.yes") : "—"}</td>
                    <td className="num">{x.kind === "deduction" ? `(${formatDecimal(x.amount)})` : formatDecimal(x.amount)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th colSpan={4}>{t("pay.net")}</th>
                  <th className="num">{formatDecimal(p.totals.net)}</th>
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="muted">
            {t("pay.totalsHelp", {
              epf: formatDecimal(p.totals.epf_earnings),
              apit: formatDecimal(p.totals.apit_earnings),
            })}
          </p>
          {p.can_edit && <AddAmount employeeId={employeeId} pay={p} onSaved={done} />}
          <h3>{t("pay.history")}</h3>
          <div className="table-wrap">
            <table aria-label={t("pay.history")}>
              <thead>
                <tr>
                  <th>{t("pay.from")}</th>
                  <th>{t("pay.component")}</th>
                  <th className="num">{t("pay.amount")}</th>
                  <th>{t("pay.reasonCol")}</th>
                  <th>{t("pay.by")}</th>
                  {p.can_edit && <th />}
                </tr>
              </thead>
              <tbody>
                {p.history.map((r) => (
                  <tr key={r.id}>
                    <td>{r.effective_from}</td>
                    <td>{r.component_name}</td>
                    <td className="num">{formatDecimal(r.amount)}</td>
                    <td>{r.reason}</td>
                    <td>{r.created_by}</td>
                    {p.can_edit && (
                      <td>
                        {r.can_withdraw && (
                          <button type="button" className="small secondary" onClick={() => setWithdrawing(r.id)}>
                            {t("pay.withdraw")}
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {withdrawing !== null && (
            <div className="inline-form">
              <label>
                {t("pay.withdrawReason")}
                <input value={why} onChange={(e) => setWhy(e.target.value)} />
              </label>
              <button type="button" disabled={withdraw.isPending} onClick={() => withdraw.mutate()}>
                {t("pay.confirmWithdraw")}
              </button>
              <button type="button" className="secondary" onClick={() => setWithdrawing(null)}>
                {t("pc.cancel")}
              </button>
            </div>
          )}
          <ErrorLine error={withdraw.error} />
        </>
      )}
    </section>
  );
}

function AddAmount({ employeeId, pay, onSaved }: { employeeId: number; pay: Pay; onSaved: (p: Pay) => void }) {
  const { t } = useTranslation();
  const [entry, setEntry] = useState({ component: "", month: pay.on.slice(0, 7), amount: "", reason: "" });
  const save = useMutation({
    mutationFn: () => addPayAmount(employeeId, entry),
    onSuccess: (p) => {
      setEntry((e) => ({ ...e, amount: "", reason: "" }));
      onSaved(p);
    },
  });
  const set = (change: Partial<typeof entry>) => setEntry((e) => ({ ...e, ...change }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form className="form-grid" aria-label={t("pay.add")} onSubmit={submit}>
      <h3 className="wide">{t("pay.add")}</h3>
      <label>
        {t("pay.component")}
        <select value={entry.component} onChange={(e) => set({ component: e.target.value })}>
          <option value="">—</option>
          {pay.components.map((c) => (
            <option key={c.code} value={c.code}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("pay.from")}
        <input type="month" value={entry.month} onChange={(e) => set({ month: e.target.value })} />
      </label>
      <label>
        {t("pay.amount")}
        <input inputMode="decimal" value={entry.amount} onChange={(e) => set({ amount: e.target.value })} />
      </label>
      <label>
        {t("pay.reason")}
        <input value={entry.reason} onChange={(e) => set({ reason: e.target.value })} />
      </label>
      <p className="muted wide">{t("pay.addHelp")}</p>
      <div className="wide row-actions">
        <button type="submit" disabled={save.isPending}>
          {t("pay.save")}
        </button>
      </div>
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}
