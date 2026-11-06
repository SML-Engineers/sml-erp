import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { ApiError } from "../api/client";
import {
  BANK_FIELDS,
  changeEmployee,
  checkEmployeeBank,
  EMPLOYEE_FIELDS,
  employeesKey,
  getEmployee,
  recordLeaving,
  type Employee,
  type EmployeeValues,
} from "../api/employees";
import EmployeeLeave from "./EmployeeLeave";
import EmployeePay from "./EmployeePay";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

const DATES = new Set(["date_of_birth", "join_date", "confirmation_date"]);

function valuesOf(e: Employee): EmployeeValues {
  const out: EmployeeValues = {};
  for (const key of [...EMPLOYEE_FIELDS, ...BANK_FIELDS])
    out[key] = key === "user_email" ? (e.user?.email ?? "") : String(e[key] ?? "");
  return out;
}

/** One employee (P2B-01): HR keeps the details; the Director checks a new bank account. */
export default function EmployeePage() {
  const { t } = useTranslation();
  const id = Number(useParams().id);
  const queryClient = useQueryClient();
  const key = [...employeesKey, id];
  const found = useQuery({ queryKey: key, queryFn: () => getEmployee(id) });
  const done = (e: Employee) => {
    queryClient.setQueryData(key, e);
    void queryClient.invalidateQueries({ queryKey: employeesKey });
  };
  const check = useMutation({ mutationFn: () => checkEmployeeBank(id), onSuccess: done });
  const e = found.data;
  return (
    <main className="page">
      <p>
        <Link to="/employees">{t("emp.back")}</Link>
      </p>
      <ErrorLine error={found.error} />
      {e && (
        <>
          <h1>
            {e.number} {e.full_name}
          </h1>
          {!e.is_active && (
            <p className="notice">
              {t("emp.leftOn", { date: e.leaving_date, reason: e.leaving_reason })}
            </p>
          )}
          {e.bank_check_pending && (
            <section className="panel" aria-label={t("emp.bankCheck")}>
              <h2>{t("emp.bankCheck")}</h2>
              <p>
                {t("emp.bankChangedBy", { name: e.bank_changed_by, at: e.bank_changed_at?.slice(0, 16).replace("T", " ") })}
              </p>
              <p className="mono">
                {e.bank_name} {e.bank_branch} — {e.account_name} {e.account_number}
              </p>
              {e.can_check_bank ? (
                <button type="button" disabled={check.isPending} onClick={() => check.mutate()}>
                  {t("emp.confirmBank")}
                </button>
              ) : (
                <p className="muted">{t("emp.bankWaiting")}</p>
              )}
              <ErrorLine error={check.error} />
            </section>
          )}
          <Details key={`${e.id}-${e.bank_changed_at}-${e.leaving_date}`} employee={e} onSaved={done} />
          <EmployeePay employeeId={e.id} />
          <EmployeeLeave employeeId={e.id} />
          {e.can_edit && <Leaving employee={e} onSaved={done} />}
          <p className="muted">
            {t("emp.created", { name: e.created_by, at: e.created_at.slice(0, 10) })}
            {e.bank_checked_by && ` ${t("emp.bankCheckedBy", { name: e.bank_checked_by, at: e.bank_checked_at?.slice(0, 10) })}`}
          </p>
        </>
      )}
    </main>
  );
}

function Details({ employee, onSaved }: { employee: Employee; onSaved: (e: Employee) => void }) {
  const { t } = useTranslation();
  const original = valuesOf(employee);
  const [values, setValues] = useState<EmployeeValues>(original);
  const [reason, setReason] = useState("");
  const changed = Object.fromEntries(
    Object.entries(values).filter(([k, v]) => v !== original[k as keyof EmployeeValues]),
  ) as EmployeeValues;
  const bankChanged = BANK_FIELDS.some((k) => k in changed);
  const save = useMutation({
    mutationFn: () => changeEmployee(employee.id, changed, reason),
    onSuccess: (e) => {
      setReason("");
      onSaved(e);
    },
  });
  const editable = employee.can_edit;
  const field = (key: keyof EmployeeValues) => (
    <label key={key}>
      {t(`emp.f.${key}`)}
      <input
        type={DATES.has(key) ? "date" : "text"}
        value={values[key] ?? ""}
        readOnly={!editable || key === "number"}
        onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
      />
    </label>
  );
  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    save.mutate();
  };
  return (
    <form className="panel form-grid" aria-label={t("emp.details")} onSubmit={submit}>
      <h2 className="wide">{t("emp.details")}</h2>
      {EMPLOYEE_FIELDS.filter((k) => k !== "employment_type" && k !== "category").map(field)}
      <label>
        {t("emp.f.employment_type")}
        <select
          value={values.employment_type ?? ""}
          disabled={!editable}
          onChange={(e) => setValues((v) => ({ ...v, employment_type: e.target.value }))}
        >
          {(["permanent", "probation", "contract", "casual", "trainee"] as const).map((k) => (
            <option key={k} value={k}>
              {t(`emp.types.${k}`)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("emp.f.category")}
        <select
          value={values.category ?? ""}
          disabled={!editable}
          onChange={(e) => setValues((v) => ({ ...v, category: e.target.value }))}
        >
          {(["shop_office", "wages_board"] as const).map((k) => (
            <option key={k} value={k}>
              {t(`emp.categories.${k}`)}
            </option>
          ))}
        </select>
      </label>
      <h3 className="wide">{t("emp.bank")}</h3>
      {BANK_FIELDS.map(field)}
      {editable && bankChanged && (
        <label className="wide">
          {t("emp.bankReason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      )}
      {editable && (
        <div className="wide row-actions">
          <button type="submit" disabled={save.isPending || Object.keys(changed).length === 0}>
            {t("emp.save")}
          </button>
        </div>
      )}
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function Leaving({ employee, onSaved }: { employee: Employee; onSaved: (e: Employee) => void }) {
  const { t } = useTranslation();
  const [day, setDay] = useState("");
  const [reason, setReason] = useState("");
  const save = useMutation({ mutationFn: () => recordLeaving(employee.id, day, reason), onSuccess: onSaved });
  return (
    <section className="panel form-grid" aria-label={t("emp.leave")}>
      <h2 className="wide">{t("emp.leave")}</h2>
      <label>
        {t("emp.leavingDate")}
        <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
      </label>
      <label>
        {t("emp.leavingReason")}
        <input value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <p className="muted wide">{t("emp.leaveHelp")}</p>
      <div className="wide row-actions">
        <button type="button" className="secondary" disabled={save.isPending} onClick={() => save.mutate()}>
          {t("emp.recordLeaving")}
        </button>
      </div>
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </section>
  );
}
