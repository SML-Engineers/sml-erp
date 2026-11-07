import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import {
  addPunchSite,
  attendanceKey,
  attendanceTemplateUrl,
  bringInPunches,
  changePunchSite,
  confirmAttendance,
  getAttendance,
  getAttendanceDays,
  getPunchSites,
  importAttendance,
  punchSitesKey,
  reopenAttendance,
  type AttendanceImportResult,
  type AttendanceMonth,
  type PunchBringIn,
  type PunchSite,
} from "../api/attendance";
import { ApiError } from "../api/client";
import PayPeriodLine from "../components/PayPeriodLine";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** Attendance (P2B-04): the sheet uploaded by HR, each employee's month, and HR's confirmation. */
export default function AttendancePage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const query = params.toString();
  const found = useQuery({ queryKey: [...attendanceKey, query], queryFn: () => getAttendance(query) });
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const d = found.data;
  return (
    <main className="page">
      <h1>{t("att.title")}</h1>
      <p className="muted">{t("att.help")}</p>
      <div className="toolbar">
        <label>
          {t("att.month")}
          <input type="month" value={params.get("month") ?? d?.month ?? ""} onChange={(e) => set("month", e.target.value)} />
        </label>
        {d && (
          <label>
            {t("att.division")}
            <select value={d.division} onChange={(e) => set("division", e.target.value)}>
              {d.divisions.map((code) => (
                <option key={code} value={code}>
                  {code}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      {d && <PayPeriodLine period={d.period} />}
      {d?.can_edit && <Upload />}
      {d?.can_edit && <PhonePunches month={d.month} />}
      <ErrorLine error={found.error} />
      {d && <MonthStatus data={d} />}
      {d && <Summary data={d} />}
      {d && <PunchSites />}
    </main>
  );
}

function Upload() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<AttendanceImportResult | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) => importAttendance(file!, dryRun),
    onSuccess: (r) => {
      setResult(r);
      if (r.saved) void queryClient.invalidateQueries({ queryKey: attendanceKey });
    },
  });
  return (
    <section className="panel" aria-label={t("att.upload")}>
      <h2>{t("att.upload")}</h2>
      <p className="muted">
        {t("att.uploadHelp")} <a href={attendanceTemplateUrl}>{t("att.template")}</a>
      </p>
      <div className="inline-form">
        <label>
          {t("att.file")}
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
          {t("att.check")}
        </button>
        <button
          type="button"
          disabled={!file || run.isPending || !result || result.errors.length > 0 || result.saved}
          onClick={() => run.mutate(false)}
        >
          {t("att.save")}
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
          {result.source === "device" && `${t("att.fromDevice")} `}
          {t(result.saved ? "att.saved" : "att.checked", {
            rows: result.rows,
            employees: result.employees,
            months: result.months.join(", "),
          })}
        </p>
      )}
      {result && (result.notes?.length ?? 0) > 0 && (
        <ul className="plain muted" aria-label={t("att.notBroughtIn")}>
          {result.notes!.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      <ErrorLine error={run.error} />
    </section>
  );
}

function MonthStatus({ data }: { data: AttendanceMonth }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const done = () => {
    setReason("");
    void queryClient.invalidateQueries({ queryKey: attendanceKey });
  };
  const confirm = useMutation({ mutationFn: () => confirmAttendance(data.division, data.month), onSuccess: done });
  const reopen = useMutation({ mutationFn: () => reopenAttendance(data.division, data.month, reason), onSuccess: done });
  return (
    <section className="panel" aria-label={t("att.status")}>
      <h2>
        {data.division} {data.month}: {data.confirmed ? t("att.confirmed") : t("att.open")}
      </h2>
      {data.confirmed ? (
        <p className="muted">{t("att.confirmedBy", { name: data.confirmed_by, at: data.confirmed_at?.slice(0, 10) })}</p>
      ) : (
        <p className="muted">{t("att.confirmHelp")}</p>
      )}
      {data.can_edit && !data.confirmed && (
        <button type="button" disabled={!data.month_ended || confirm.isPending} onClick={() => confirm.mutate()}>
          {t("att.confirm")}
        </button>
      )}
      {data.can_edit && data.confirmed && (
        <div className="inline-form">
          <label>
            {t("att.reopenReason")}
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="button" className="secondary" disabled={reopen.isPending} onClick={() => reopen.mutate()}>
            {t("att.reopen")}
          </button>
        </div>
      )}
      <ErrorLine error={confirm.error} />
      <ErrorLine error={reopen.error} />
    </section>
  );
}

function Summary({ data }: { data: AttendanceMonth }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="table-wrap">
      <table aria-label={t("att.summary")}>
        <thead>
          <tr>
            <th>{t("att.employee")}</th>
            <th className="num">{t("att.workingDays")}</th>
            <th className="num">{t("att.worked")}</th>
            <th className="num">{t("att.hours")}</th>
            <th className="num">{t("att.lateDays")}</th>
            <th className="num">{t("att.early")}</th>
            <th className="num">{t("att.leave")}</th>
            <th className="num">{t("att.absent")}</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.length === 0 && (
            <tr>
              <td colSpan={8} className="muted">
                {t("att.none")}
              </td>
            </tr>
          )}
          {data.rows.map((r) => (
            <Fragment key={r.employee.id}>
              <tr>
                <td>
                  <button
                    type="button"
                    className="link-button"
                    aria-expanded={open === r.employee.id}
                    onClick={() => setOpen(open === r.employee.id ? null : r.employee.id)}
                  >
                    {r.employee.number} {r.employee.name}
                  </button>
                </td>
                <td className="num">{r.working_days}</td>
                <td className="num">{r.days_worked}</td>
                <td className="num">{r.hours_worked}</td>
                <td className="num">
                  {r.late_days} ({r.late})
                </td>
                <td className="num">{r.early}</td>
                <td className="num">{r.leave_days}</td>
                <td className="num">{r.absent_days}</td>
              </tr>
              {open === r.employee.id && (
                <tr>
                  <td colSpan={8}>
                    <Days employeeId={r.employee.id} month={data.month} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Days({ employeeId, month }: { employeeId: number; month: string }) {
  const { t } = useTranslation();
  const found = useQuery({
    queryKey: [...attendanceKey, "days", employeeId, month],
    queryFn: () => getAttendanceDays(employeeId, month),
  });
  if (!found.data) return <ErrorLine error={found.error} />;
  return (
    <>
      <table aria-label={t("att.days")}>
        <thead>
          <tr>
            <th>{t("att.date")}</th>
            <th>{t("att.shift")}</th>
            <th>{t("att.in")}</th>
            <th>{t("att.out")}</th>
            <th>{t("att.leaveCode")}</th>
            <th className="num">{t("att.hours")}</th>
            <th className="num">{t("att.lateMin")}</th>
            <th>{t("att.remarks")}</th>
          </tr>
        </thead>
        <tbody>
          {found.data.days.map((x) => (
            <tr key={x.date}>
              <td>{x.date}</td>
              <td>{x.shift}</td>
              <td>{x.time_in}</td>
              <td>{x.time_out}</td>
              <td>{x.leave}</td>
              <td className="num">{x.worked}</td>
              <td className="num">{x.late || ""}</td>
              <td>{x.remarks}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {found.data.punches.length > 0 && (
        <details>
          <summary>{t("punch.raw", { count: found.data.punches.length })}</summary>
          <ul className="plain">
            {found.data.punches.map((p) => (
              <li key={`${p.at}${p.kind}`}>
                {p.at} {t(`punch.${p.kind}`)}
                {p.site && ` — ${p.site} (${p.distance_m} m)`}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}

/** P2B-12: a pay month's phone punches into attendance, after a preview. */
function PhonePunches({ month }: { month: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [result, setResult] = useState<PunchBringIn | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) => bringInPunches(month, dryRun),
    onSuccess: (r) => {
      setResult(r);
      if (r.saved) void queryClient.invalidateQueries({ queryKey: attendanceKey });
    },
  });
  return (
    <section className="panel" aria-label={t("punch.bringIn")}>
      <h2>{t("punch.bringIn")}</h2>
      <p className="muted">{t("punch.bringInHelp")}</p>
      <div className="inline-form">
        <button type="button" className="secondary" disabled={run.isPending} onClick={() => run.mutate(true)}>
          {t("punch.preview", { month })}
        </button>
        <button
          type="button"
          disabled={run.isPending || !result || result.saved || result.days === 0 || result.month !== month}
          onClick={() => run.mutate(false)}
        >
          {t("punch.save")}
        </button>
      </div>
      {result && (
        <p className="notice" role="status">
          {t(result.saved ? "punch.saved" : "punch.checked", {
            punches: result.punches,
            days: result.days,
            employees: result.employees,
          })}
        </p>
      )}
      {result && result.notes.length > 0 && (
        <ul className="plain">
          {result.notes.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      {result && result.rows.length > 0 && !result.saved && (
        <table aria-label={t("punch.days")}>
          <tbody>
            {result.rows.map((r) => (
              <tr key={`${r.number}${r.date}`}>
                <td>{r.number}</td>
                <td>{r.name}</td>
                <td>{r.date}</td>
                <td>
                  {r.time_in}–{r.time_out}
                </td>
                <td>{r.shift}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ErrorLine error={run.error} />
    </section>
  );
}

/** P2B-12: the places where staff limited to sites may clock in (a point and a radius). */
function PunchSites() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const found = useQuery({ queryKey: punchSitesKey, queryFn: getPunchSites });
  const empty = { name: "", latitude: "", longitude: "", radius_m: "200" };
  const [values, setValues] = useState(empty);
  const done = () => void queryClient.invalidateQueries({ queryKey: punchSitesKey });
  const add = useMutation({
    mutationFn: () => addPunchSite(values),
    onSuccess: () => {
      setValues(empty);
      done();
    },
  });
  const toggle = useMutation({
    mutationFn: (s: PunchSite) => changePunchSite(s.id, { is_active: !s.is_active }),
    onSuccess: done,
  });
  const d = found.data;
  if (!d) return <ErrorLine error={found.error} />;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  return (
    <section className="panel" aria-label={t("punch.sites")}>
      <h2>{t("punch.sites")}</h2>
      <p className="muted">{t("punch.sitesHelp")}</p>
      <table aria-label={t("punch.sites")}>
        <tbody>
          {d.results.map((s) => (
            <tr key={s.id} className={s.is_active ? "" : "muted"}>
              <td>{s.name}</td>
              <td>
                <a
                  href={`https://www.openstreetmap.org/?mlat=${s.latitude}&mlon=${s.longitude}#map=17/${s.latitude}/${s.longitude}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {s.latitude}, {s.longitude}
                </a>
              </td>
              <td className="num">{t("punch.radius", { metres: s.radius_m })}</td>
              <td>
                {d.can_edit && (
                  <button type="button" className="small secondary" onClick={() => toggle.mutate(s)}>
                    {s.is_active ? t("punch.deactivate") : t("punch.activate")}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {d.can_edit && (
        <form className="inline-form" aria-label={t("punch.addSite")} onSubmit={submit}>
          <label>
            {t("punch.siteName")}
            <input value={values.name} onChange={(e) => setValues({ ...values, name: e.target.value })} />
          </label>
          <label>
            {t("punch.latitude")}
            <input inputMode="decimal" value={values.latitude} onChange={(e) => setValues({ ...values, latitude: e.target.value })} />
          </label>
          <label>
            {t("punch.longitude")}
            <input inputMode="decimal" value={values.longitude} onChange={(e) => setValues({ ...values, longitude: e.target.value })} />
          </label>
          <label>
            {t("punch.radiusM")}
            <input inputMode="numeric" value={values.radius_m} onChange={(e) => setValues({ ...values, radius_m: e.target.value })} />
          </label>
          <button type="submit" disabled={add.isPending}>
            {t("punch.addSite")}
          </button>
        </form>
      )}
      <ErrorLine error={add.error ?? toggle.error} />
    </section>
  );
}
