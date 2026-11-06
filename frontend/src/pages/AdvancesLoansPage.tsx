import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  actOnStaffCredit,
  listStaffCredits,
  recordStaffCredit,
  staffCreditsKey,
  type CreditAction,
  type CreditValues,
  type StaffCredit,
} from "../api/payroll";
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

/** Salary advances and staff loans (P2B-10): HR records, the Director approves, the payroll
 * recovers them. */
export default function AdvancesLoansPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: staffCreditsKey, queryFn: listStaffCredits });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: staffCreditsKey });
  const d = list.data;
  return (
    <div className="page">
      <h1>{t("credits.title")}</h1>
      <p className="muted">{t("credits.help")}</p>
      <ErrorLine error={list.error} />
      {d?.can_record && <RecordForm employees={d.employees} firstMonth={d.first_month} onDone={refresh} />}
      {d && (
        <div className="table-wrap">
          <table aria-label={t("credits.list")}>
            <thead>
              <tr>
                <th>{t("credits.employee")}</th>
                <th>{t("credits.kind")}</th>
                <th className="num">{t("credits.amount")}</th>
                <th className="num">{t("credits.instalment")}</th>
                <th>{t("credits.from")}</th>
                <th className="num">{t("credits.balance")}</th>
                <th>{t("credits.status")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {d.results.length === 0 && (
                <tr>
                  <td colSpan={8} className="muted">
                    {t("credits.none")}
                  </td>
                </tr>
              )}
              {d.results.map((c) => (
                <Row key={c.id} credit={c} onDone={refresh} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Row({ credit: c, onDone }: { credit: StaffCredit; onDone: () => void }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const act = useMutation({
    mutationFn: (action: CreditAction) => actOnStaffCredit(c.id, action, reason),
    onSuccess: () => {
      setReason("");
      onDone();
    },
  });
  const acts = c.can_submit || c.can_approve || c.can_withdraw;
  return (
    <tr>
      <td>
        {c.employee.number} {c.employee.name}
        <div className="muted">
          {c.number} {c.reason}
        </div>
      </td>
      <td>{c.kind_label}</td>
      <td className="num">
        {formatDecimal(c.amount)}
        {c.interest !== "0.00" && <div className="muted">{t("credits.plusInterest", { interest: formatDecimal(c.interest) })}</div>}
      </td>
      <td className="num">
        {formatDecimal(c.instalment)}
        {c.kind === "loan" && <div className="muted">{t("credits.months", { count: c.months })}</div>}
      </td>
      <td>{c.first_month}</td>
      <td className="num">{c.status === "approved" ? formatDecimal(c.balance) : "—"}</td>
      <td>{c.returned && c.status === "draft" ? t("credits.returned") : c.status_label}</td>
      <td>
        {acts && (
          <div className="row-actions">
            {(c.can_approve || c.can_withdraw) && (
              <input
                aria-label={t("credits.reason")}
                placeholder={t("credits.reason")}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            )}
            {c.can_submit && (
              <button type="button" className="small" onClick={() => act.mutate("submit")}>
                {t("credits.submit")}
              </button>
            )}
            {c.can_approve && (
              <>
                <button type="button" className="small" onClick={() => act.mutate("approve")}>
                  {t("credits.approve")}
                </button>
                <button type="button" className="small secondary" onClick={() => act.mutate("return")}>
                  {t("credits.return")}
                </button>
                <button type="button" className="small danger" onClick={() => act.mutate("reject")}>
                  {t("credits.reject")}
                </button>
              </>
            )}
            {c.can_withdraw && (
              <button type="button" className="small secondary" onClick={() => act.mutate("withdraw")}>
                {t("credits.withdraw")}
              </button>
            )}
          </div>
        )}
        <ErrorLine error={act.error} />
      </td>
    </tr>
  );
}

function RecordForm({
  employees,
  firstMonth,
  onDone,
}: {
  employees: { id: number; number: string; name: string }[];
  firstMonth: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const empty = (): CreditValues => ({
    employee: String(employees[0]?.id ?? ""),
    kind: "advance",
    amount: "",
    interest: "0",
    months: "1",
    first_month: firstMonth,
    reason: "",
  });
  const [values, setValues] = useState<CreditValues>(empty);
  const save = useMutation({
    mutationFn: () => recordStaffCredit(values),
    onSuccess: () => {
      setValues(empty());
      onDone();
    },
  });
  const set = (change: Partial<CreditValues>) => setValues((v) => ({ ...v, ...change }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const isLoan = values.kind === "loan";
  return (
    <form className="panel form-grid" aria-label={t("credits.record")} onSubmit={submit}>
      <h2 className="wide">{t("credits.record")}</h2>
      <label>
        {t("credits.employee")}
        <select value={values.employee} onChange={(e) => set({ employee: e.target.value })}>
          {employees.map((e) => (
            <option key={e.id} value={e.id}>
              {e.number} {e.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("credits.kind")}
        <select value={values.kind} onChange={(e) => set({ kind: e.target.value })}>
          <option value="advance">{t("credits.advance")}</option>
          <option value="loan">{t("credits.loan")}</option>
        </select>
      </label>
      <label>
        {t("credits.amount")}
        <input inputMode="decimal" value={values.amount} onChange={(e) => set({ amount: e.target.value })} />
      </label>
      {isLoan && (
        <>
          <label>
            {t("credits.interest")}
            <input inputMode="decimal" value={values.interest} onChange={(e) => set({ interest: e.target.value })} />
          </label>
          <label>
            {t("credits.monthsLabel")}
            <input inputMode="numeric" value={values.months} onChange={(e) => set({ months: e.target.value })} />
          </label>
        </>
      )}
      <label>
        {t("credits.from")}
        <input type="month" value={values.first_month} onChange={(e) => set({ first_month: e.target.value })} />
      </label>
      <label className="wide">
        {t("credits.reason")}
        <input value={values.reason} onChange={(e) => set({ reason: e.target.value })} />
      </label>
      <p className="muted wide">{t("credits.recordHelp")}</p>
      <div className="wide row-actions">
        <button type="submit" disabled={save.isPending}>
          {t("credits.save")}
        </button>
      </div>
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}
