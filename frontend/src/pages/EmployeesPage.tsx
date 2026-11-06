import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { canDo } from "../api/access";
import { listDivisions } from "../api/admin";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import {
  addEmployee,
  decideDetailChange,
  detailChangesKey,
  employeeExportUrl,
  employeesKey,
  employeeTemplateUrl,
  getDetailChanges,
  importEmployees,
  listEmployees,
  type EmployeeImportResult,
  type EmployeeList,
  type EmployeeValues,
} from "../api/employees";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** Employees (P2B-01): HR's list of everyone employed, with Excel import; the Director sees it. */
export default function EmployeesPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const query = params.toString();
  const list = useQuery({ queryKey: [...employeesKey, query], queryFn: () => listEmployees(query) });
  const [adding, setAdding] = useState(false);
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const data = list.data;
  return (
    <main className="page">
      <h1>{t("emp.title")}</h1>
      <p className="muted">{t("emp.help")}</p>
      <div className="toolbar">
        <label>
          {t("table.search")}
          <input value={params.get("q") ?? ""} onChange={(e) => set("q", e.target.value)} />
        </label>
        <label>
          {t("emp.show")}
          <select value={params.get("status") ?? "active"} onChange={(e) => set("status", e.target.value)}>
            <option value="active">{t("emp.active")}</option>
            <option value="left">{t("emp.left")}</option>
            <option value="all">{t("table.all")}</option>
          </select>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={params.get("bank_check") === "pending"}
            onChange={(e) => set("bank_check", e.target.checked ? "pending" : "")}
          />{" "}
          {t("emp.bankPendingOnly")}
        </label>
        {data?.can_add && (
          <button type="button" onClick={() => setAdding((v) => !v)}>
            {t("emp.add")}
          </button>
        )}
        {canDo(me.access, "export_personal_data") && (
          <a className="button-link secondary" href={employeeExportUrl}>
            {t("emp.export")}
          </a>
        )}
      </div>
      {adding && data && <AddEmployee data={data} />}
      {data?.can_add && <ImportEmployees />}
      {data?.can_add && <DetailRequests />}
      <ErrorLine error={list.error} />
      {data && (
        <div className="table-wrap">
          <table aria-label={t("emp.list")}>
            <thead>
              <tr>
                <th>{t("emp.f.number")}</th>
                <th>{t("emp.f.full_name")}</th>
                <th>{t("emp.f.designation")}</th>
                <th>{t("emp.f.division")}</th>
                <th>{t("emp.f.employment_type")}</th>
                <th>{t("emp.f.category")}</th>
                <th>{t("emp.f.join_date")}</th>
                <th>{t("emp.bank")}</th>
              </tr>
            </thead>
            <tbody>
              {data.results.length === 0 && (
                <tr>
                  <td colSpan={8} className="muted">
                    {t("emp.none")}
                  </td>
                </tr>
              )}
              {data.results.map((e) => (
                <tr key={e.id}>
                  <td>
                    <Link to={`/employees/${e.id}`} className="mono">
                      {e.number}
                    </Link>
                  </td>
                  <td>
                    {e.full_name}
                    {!e.is_active && <span className="tag"> {t("emp.leftTag")}</span>}
                  </td>
                  <td>{e.designation}</td>
                  <td>
                    {e.division}
                    {e.section && ` / ${e.section}`}
                  </td>
                  <td>{e.employment_type_label}</td>
                  <td>{e.category_label}</td>
                  <td>{e.join_date}</td>
                  <td>{e.bank_check_pending ? t("emp.bankPending") : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}

function AddEmployee({ data }: { data: EmployeeList }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions });
  const [values, setValues] = useState<EmployeeValues>({ employment_type: "permanent", category: "shop_office" });
  const save = useMutation({
    mutationFn: () => addEmployee(values),
    onSuccess: (made) => {
      void queryClient.invalidateQueries({ queryKey: employeesKey });
      void navigate(`/employees/${made.id}`);
    },
  });
  const set = (key: keyof EmployeeValues, value: string) => setValues((v) => ({ ...v, [key]: value }));
  const field = (key: keyof EmployeeValues, type = "text") => (
    <label>
      {t(`emp.f.${key}`)}
      <input type={type} value={values[key] ?? ""} onChange={(e) => set(key, e.target.value)} />
    </label>
  );
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form className="panel form-grid" aria-label={t("emp.add")} onSubmit={submit}>
      <h2 className="wide">{t("emp.add")}</h2>
      {field("number")}
      {field("full_name")}
      {field("name_with_initials")}
      {field("nic")}
      {field("date_of_birth", "date")}
      <label>
        {t("emp.f.division")}
        <select value={values.division ?? ""} onChange={(e) => set("division", e.target.value)}>
          <option value="">—</option>
          {divisions.data?.map((d) => (
            <option key={d.code} value={d.code}>
              {d.code} {d.name}
            </option>
          ))}
        </select>
      </label>
      {field("section")}
      {field("designation")}
      <label>
        {t("emp.f.employment_type")}
        <select value={values.employment_type ?? ""} onChange={(e) => set("employment_type", e.target.value)}>
          {data.types.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("emp.f.category")}
        <select value={values.category ?? ""} onChange={(e) => set("category", e.target.value)}>
          {data.categories.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
      </label>
      {field("join_date", "date")}
      {field("epf_no")}
      {field("phone")}
      <p className="muted wide">{t("emp.addHelp")}</p>
      <div className="wide row-actions">
        <button type="submit" disabled={save.isPending}>
          {t("emp.save")}
        </button>
      </div>
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function ImportEmployees() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<EmployeeImportResult | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) => importEmployees(file!, dryRun),
    onSuccess: (r) => {
      setResult(r);
      if (r.saved) void queryClient.invalidateQueries({ queryKey: employeesKey });
    },
  });
  return (
    <section className="panel" aria-label={t("emp.import")}>
      <h2>{t("emp.import")}</h2>
      <p className="muted">
        {t("emp.importHelp")} <a href={employeeTemplateUrl}>{t("emp.template")}</a>
      </p>
      <div className="inline-form">
        <label>
          {t("emp.file")}
          <input
            type="file"
            accept=".xlsx"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setResult(null);
            }}
          />
        </label>
        <button type="button" className="secondary" disabled={!file || run.isPending} onClick={() => run.mutate(true)}>
          {t("emp.check")}
        </button>
        <button
          type="button"
          disabled={!file || run.isPending || !result || result.errors.length > 0 || result.saved}
          onClick={() => run.mutate(false)}
        >
          {t("emp.importButton")}
        </button>
      </div>
      {result && result.errors.length > 0 && (
        <ul className="form-error" role="alert">
          {result.errors.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      {result && result.errors.length === 0 && (
        <p className="notice" role="status">
          {t(result.saved ? "emp.imported" : "emp.checked", { added: result.added, updated: result.updated })}
        </p>
      )}
      <ErrorLine error={run.error} />
    </section>
  );
}

/** P2B-20: employees' requests to change their details; HR approves or rejects. */
function DetailRequests() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const found = useQuery({ queryKey: detailChangesKey, queryFn: getDetailChanges });
  if (!found.data || found.data.results.length === 0) return <ErrorLine error={found.error} />;
  const done = (d: Awaited<ReturnType<typeof getDetailChanges>>) => {
    queryClient.setQueryData(detailChangesKey, d);
    void queryClient.invalidateQueries({ queryKey: employeesKey });
  };
  return (
    <section className="panel" aria-label={t("emp.requests")}>
      <h2>{t("emp.requests")}</h2>
      <ul className="plain">
        {found.data.results.map((r) => (
          <DetailRequestRow key={r.id} id={r.id} onDone={done}>
            <strong>
              <Link to={`/employees/${r.employee_id}`}>{r.employee}</Link>
            </strong>{" "}
            <span className="muted">{r.created_at.slice(0, 10)}</span>
            <ul>
              {r.changes.map((c) => (
                <li key={c.field}>
                  {t(`emp.f.${c.field}`)}: {c.before || "-"} → {c.after || "-"}
                </li>
              ))}
            </ul>
            {r.note && <p className="muted">{r.note}</p>}
            {r.bank && <p className="muted">{t("emp.requestBank")}</p>}
          </DetailRequestRow>
        ))}
      </ul>
    </section>
  );
}

function DetailRequestRow({ id, onDone, children }: { id: number; onDone: (d: Awaited<ReturnType<typeof getDetailChanges>>) => void; children: React.ReactNode }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const act = useMutation({
    mutationFn: (action: "approve" | "reject") => decideDetailChange(id, action, reason),
    onSuccess: onDone,
  });
  return (
    <li>
      {children}
      <div className="row-actions">
        <input aria-label={t("my.rejectReason")} placeholder={t("my.rejectReason")} value={reason} onChange={(e) => setReason(e.target.value)} />
        <button type="button" className="small" disabled={act.isPending} onClick={() => act.mutate("approve")}>
          {t("my.approve")}
        </button>
        <button type="button" className="small secondary" disabled={act.isPending} onClick={() => act.mutate("reject")}>
          {t("my.reject")}
        </button>
      </div>
      <ErrorLine error={act.error} />
    </li>
  );
}
