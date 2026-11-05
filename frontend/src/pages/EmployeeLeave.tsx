import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { adjustLeave, getEmployeeLeave, type EmployeeLeave as Data } from "../api/leave";
import { LeaveTable } from "./LeavePage";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** An employee's leave (P2B-03): the year's balances, the leave taken and HR's adjustments. */
export default function EmployeeLeave({ employeeId }: { employeeId: number }) {
  const { t } = useTranslation();
  const [year, setYear] = useState(new Date().getFullYear());
  const key = ["employees", employeeId, "leave", year];
  const found = useQuery({ queryKey: key, queryFn: () => getEmployeeLeave(employeeId, year) });
  const d = found.data;
  return (
    <section className="panel" aria-label={t("leave.balances")}>
      <h2>
        {t("leave.balances")}{" "}
        <button type="button" className="small secondary" onClick={() => setYear((y) => y - 1)}>
          ←
        </button>{" "}
        {year}{" "}
        <button type="button" className="small secondary" onClick={() => setYear((y) => y + 1)}>
          →
        </button>
      </h2>
      <ErrorLine error={found.error} />
      {d && (
        <>
          <div className="table-wrap">
            <table aria-label={t("leave.balances")}>
              <thead>
                <tr>
                  <th>{t("leave.type")}</th>
                  <th className="num">{t("leave.granted")}</th>
                  <th className="num">{t("leave.taken")}</th>
                  <th className="num">{t("leave.pending")}</th>
                  <th className="num">{t("leave.available")}</th>
                </tr>
              </thead>
              <tbody>
                {d.balances.map((b) => (
                  <tr key={b.leave_type}>
                    <td>{b.name}</td>
                    <td className="num">{b.granted}</td>
                    <td className="num">{b.taken}</td>
                    <td className="num">{b.pending}</td>
                    <td className="num">{b.available}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.grants.length > 0 && (
            <ul className="plain-list muted">
              {d.grants.map((g) => (
                <li key={g.id}>
                  {g.leave_type}: {g.days} — {g.reason} ({g.created_by})
                </li>
              ))}
            </ul>
          )}
          <LeaveTable rows={d.leave} showEmployee={false} />
          {d.can_adjust && <Adjust employeeId={employeeId} data={d} />}
        </>
      )}
    </section>
  );
}

function Adjust({ employeeId, data }: { employeeId: number; data: Data }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [entry, setEntry] = useState({ leave_type: "", days: "", reason: "" });
  const save = useMutation({
    mutationFn: () => adjustLeave(employeeId, { ...entry, year: data.year }),
    onSuccess: (d) => {
      setEntry({ leave_type: "", days: "", reason: "" });
      queryClient.setQueryData(["employees", employeeId, "leave", data.year], d);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form className="inline-form" aria-label={t("leave.adjust")} onSubmit={submit}>
      <label>
        {t("leave.type")}
        <select value={entry.leave_type} onChange={(e) => setEntry({ ...entry, leave_type: e.target.value })}>
          <option value="">—</option>
          {data.balances.map((b) => (
            <option key={b.leave_type} value={b.leave_type}>
              {b.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("leave.adjustDays")}
        <input inputMode="decimal" value={entry.days} onChange={(e) => setEntry({ ...entry, days: e.target.value })} />
      </label>
      <label>
        {t("leave.adjustReason")}
        <input value={entry.reason} onChange={(e) => setEntry({ ...entry, reason: e.target.value })} />
      </label>
      <button type="submit" disabled={save.isPending}>
        {t("leave.adjust")}
      </button>
      <ErrorLine error={save.error} />
    </form>
  );
}
