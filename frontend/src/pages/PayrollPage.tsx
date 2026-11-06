import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError } from "../api/client";
import {
  actOnPayroll,
  getPayroll,
  listPayroll,
  payrollKey,
  payrollRunKey,
  preparePayroll,
  setPayrollEntry,
  type PayrollAction,
  type PayrollLine,
  type PayrollRun,
} from "../api/payroll";
import PayPeriodLine from "../components/PayPeriodLine";
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

/** The monthly payroll (P2B-06): the list of payrolls, and HR prepares a division's pay month. */
export default function PayrollPage() {
  const { id } = useParams();
  return id ? <RunPage id={Number(id)} /> : <ListPage />;
}

function ListPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: payrollKey, queryFn: listPayroll });
  const [division, setDivision] = useState("");
  const [month, setMonth] = useState("");
  const d = list.data;
  const prepare = useMutation({
    mutationFn: () => preparePayroll(division || d!.divisions[0], month || d!.last_month),
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: payrollKey });
      void navigate(`/payroll/${run.id}`);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    prepare.mutate();
  };
  return (
    <div className="page">
      <h1>{t("payroll.title")}</h1>
      <p className="muted">{t("payroll.help")}</p>
      <ErrorLine error={list.error} />
      {d?.can_prepare && (
        <form className="panel form-grid" aria-label={t("payroll.prepare")} onSubmit={submit}>
          <h2 className="wide">{t("payroll.prepare")}</h2>
          <label>
            {t("payroll.division")}
            <select value={division || d.divisions[0] || ""} onChange={(e) => setDivision(e.target.value)}>
              {d.divisions.map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("payroll.month")}
            <input type="month" value={month || d.last_month} onChange={(e) => setMonth(e.target.value)} />
          </label>
          <p className="muted wide">{t("payroll.prepareHelp")}</p>
          <div className="wide row-actions">
            <button type="submit" disabled={prepare.isPending}>
              {t("payroll.prepareButton")}
            </button>
          </div>
          <div className="wide">
            <ErrorLine error={prepare.error} />
          </div>
        </form>
      )}
      {d && (
        <div className="table-wrap">
          <table aria-label={t("payroll.list")}>
            <thead>
              <tr>
                <th>{t("payroll.month")}</th>
                <th>{t("payroll.division")}</th>
                <th>{t("payroll.status")}</th>
                <th className="num">{t("payroll.employees")}</th>
                <th className="num">{t("payroll.net")}</th>
              </tr>
            </thead>
            <tbody>
              {d.results.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    {t("payroll.none")}
                  </td>
                </tr>
              )}
              {d.results.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/payroll/${r.id}`}>{r.month}</Link>
                  </td>
                  <td>{r.division}</td>
                  <td>{r.status_label}</td>
                  <td className="num">{r.totals.employees}</td>
                  <td className="num">{formatDecimal(r.totals.net)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RunPage({ id }: { id: number }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = payrollRunKey(id);
  const found = useQuery({ queryKey: key, queryFn: () => getPayroll(id) });
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const done = (run: PayrollRun) => {
    queryClient.setQueryData(key, run);
    void queryClient.invalidateQueries({ queryKey: payrollKey, exact: true });
  };
  const act = useMutation({
    mutationFn: (action: PayrollAction) => actOnPayroll(id, action, reason),
    onSuccess: (run) => {
      setReason("");
      done(run);
    },
  });
  const r = found.data;
  return (
    <div className="page">
      <p>
        <Link to="/payroll">{t("payroll.back")}</Link>
      </p>
      <ErrorLine error={found.error} />
      {r && (
        <>
          <h1>
            {t("payroll.runTitle", { division: r.division, month: r.month })}{" "}
            <span className="tag">{r.returned && r.status === "draft" ? t("payroll.returned") : r.status_label}</span>
          </h1>
          <PayPeriodLine period={r.period} />
          <dl className="details">
            <div>
              <dt>{t("payroll.employees")}</dt>
              <dd>{r.totals.employees}</dd>
            </div>
            <div>
              <dt>{t("payroll.gross")}</dt>
              <dd>{formatDecimal(r.totals.gross)}</dd>
            </div>
            <div>
              <dt>{t("payroll.epf8")}</dt>
              <dd>{formatDecimal(r.totals.epf_employee)}</dd>
            </div>
            <div>
              <dt>{t("payroll.apit")}</dt>
              <dd>{formatDecimal(r.totals.apit)}</dd>
            </div>
            <div>
              <dt>{t("payroll.deductions")}</dt>
              <dd>{formatDecimal(r.totals.deductions)}</dd>
            </div>
            <div>
              <dt>{t("payroll.net")}</dt>
              <dd>
                <strong>{formatDecimal(r.totals.net)}</strong>
              </dd>
            </div>
            <div>
              <dt>{t("payroll.employer")}</dt>
              <dd>
                {t("payroll.employerValue", {
                  epf: formatDecimal(r.totals.epf_employer),
                  etf: formatDecimal(r.totals.etf),
                })}
              </dd>
            </div>
          </dl>
          {!r.sees_people && <p className="muted">{t("payroll.totalsOnly")}</p>}
          {r.sees_people && (
            <div className="table-wrap">
              <table aria-label={t("payroll.lines")}>
                <thead>
                  <tr>
                    <th>{t("payroll.employee")}</th>
                    <th className="num">{t("payroll.gross")}</th>
                    <th className="num">{t("payroll.epf8")}</th>
                    <th className="num">{t("payroll.apit")}</th>
                    <th className="num">{t("payroll.deductions")}</th>
                    <th className="num">{t("payroll.net")}</th>
                  </tr>
                </thead>
                <tbody>
                  {r.lines.map((x) => (
                    <Fragment key={x.employee.id}>
                      <tr>
                        <td>
                          <button
                            type="button"
                            className="link"
                            aria-expanded={open === x.employee.id}
                            onClick={() => setOpen(open === x.employee.id ? null : x.employee.id)}
                          >
                            {x.employee.number} {x.employee.name}
                          </button>
                          {x.days_employed < x.days_in_period && (
                            <span className="muted">
                              {" "}
                              {t("payroll.part", { days: x.days_employed, of: x.days_in_period })}
                            </span>
                          )}
                        </td>
                        <td className="num">{formatDecimal(x.gross)}</td>
                        <td className="num">{formatDecimal(x.epf_employee)}</td>
                        <td className="num">{formatDecimal(x.apit)}</td>
                        <td className="num">{formatDecimal(x.deductions)}</td>
                        <td className="num">{formatDecimal(x.net)}</td>
                      </tr>
                      {open === x.employee.id && (
                        <tr>
                          <td colSpan={6}>
                            <Details line={x} run={r} onDone={done} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {r.history.length > 0 && (
            <ul className="muted">
              {r.history.map((h, i) => (
                <li key={i}>
                  {h.action} — {h.user}
                  {h.reason && `: ${h.reason}`}
                </li>
              ))}
            </ul>
          )}
          {(r.can_submit || r.can_approve) && (
            <label>
              {r.can_approve ? t("payroll.comment") : t("payroll.submitComment")}
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
          )}
          <div className="row-actions">
            {r.can_work_out && (
              <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("work-out")}>
                {t("payroll.workOut")}
              </button>
            )}
            {r.can_submit && (
              <button type="button" disabled={act.isPending} onClick={() => act.mutate("submit")}>
                {t("payroll.submit")}
              </button>
            )}
            {r.can_approve && (
              <>
                <button type="button" disabled={act.isPending} onClick={() => act.mutate("approve")}>
                  {t("payroll.approve")}
                </button>
                <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("return")}>
                  {t("payroll.return")}
                </button>
                <button type="button" className="danger" disabled={act.isPending} onClick={() => act.mutate("reject")}>
                  {t("payroll.reject")}
                </button>
              </>
            )}
          </div>
          <ErrorLine error={act.error} />
        </>
      )}
    </div>
  );
}

function Details({ line, run, onDone }: { line: PayrollLine; run: PayrollRun; onDone: (r: PayrollRun) => void }) {
  const { t } = useTranslation();
  const [entry, setEntry] = useState({ component: "", amount: "", note: "" });
  const save = useMutation({
    mutationFn: () =>
      setPayrollEntry(run.id, {
        employee: line.employee.id,
        component: entry.component || run.components[0]?.code || "",
        amount: entry.amount,
        note: entry.note,
      }),
    onSuccess: (r) => {
      setEntry({ component: "", amount: "", note: "" });
      onDone(r);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const mine = run.entries.filter((x) => x.employee === line.employee.id);
  return (
    <div>
      <p className="muted">
        {t("payroll.rates", { day: formatDecimal(line.day_rate), hour: formatDecimal(line.hourly_rate) })}
      </p>
      <table aria-label={t("payroll.items", { number: line.employee.number })}>
        <tbody>
          {line.items.map((i, n) => (
            <tr key={n}>
              <td>
                {i.name}
                {i.kind === "employer" && <span className="tag"> {t("payroll.byEmployer")}</span>}
              </td>
              <td className="num">{i.kind === "earning" ? formatDecimal(i.amount) : `(${formatDecimal(i.amount)})`}</td>
              <td className="muted">{i.basis}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {mine.length > 0 && (
        <p className="muted">
          {t("payroll.entered")}: {mine.map((x) => `${x.component} ${formatDecimal(x.amount)}`).join(", ")}
        </p>
      )}
      {run.can_work_out && (
        <form className="form-grid" aria-label={t("payroll.enter")} onSubmit={submit}>
          <label>
            {t("payroll.component")}
            <select value={entry.component || run.components[0]?.code} onChange={(e) => setEntry({ ...entry, component: e.target.value })}>
              {run.components.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("payroll.amount")}
            <input inputMode="decimal" value={entry.amount} onChange={(e) => setEntry({ ...entry, amount: e.target.value })} />
          </label>
          <label>
            {t("payroll.note")}
            <input value={entry.note} onChange={(e) => setEntry({ ...entry, note: e.target.value })} />
          </label>
          <div className="row-actions">
            <button type="submit" disabled={save.isPending}>
              {t("payroll.enter")}
            </button>
          </div>
          <p className="muted wide">{t("payroll.enterHelp")}</p>
          <div className="wide">
            <ErrorLine error={save.error} />
          </div>
        </form>
      )}
    </div>
  );
}
