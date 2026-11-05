import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import { checkOvertime, getOvertime, overtimeKey } from "../api/overtime";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** Overtime (P2B-05): each employee's month worked out by the rules, checked by the section's
 * supervisor or the Director. */
export default function OvertimePage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const query = params.toString();
  const found = useQuery({ queryKey: [...overtimeKey, query], queryFn: () => getOvertime(query) });
  const [chosen, setChosen] = useState<number[]>([]);
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setChosen([]);
  };
  const d = found.data;
  const check = useMutation({
    mutationFn: () => checkOvertime(d!.division, d!.month, chosen),
    onSuccess: () => {
      setChosen([]);
      void queryClient.invalidateQueries({ queryKey: overtimeKey });
    },
  });
  const checkable = d?.rows.filter((r) => r.can_check).map((r) => r.employee.id) ?? [];
  return (
    <main className="page">
      <h1>{t("ot.title")}</h1>
      <p className="muted">{t("ot.help")}</p>
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
      <ErrorLine error={found.error} />
      {d && !d.confirmed && <p className="notice">{t("ot.notConfirmed")}</p>}
      {d?.rule && (
        <p className="muted">
          {t("ot.ruleLine", {
            day: d.rule.normal_day_minutes / 60,
            working: d.rule.rate_working_day,
            sunday: d.rule.rate_sunday,
            holiday: d.rule.rate_holiday,
            grace: d.rule.grace_minutes,
          })}
        </p>
      )}
      {d && (
        <div className="table-wrap">
          <table aria-label={t("ot.title")}>
            <thead>
              <tr>
                <th>
                  {checkable.length > 0 && (
                    <input
                      type="checkbox"
                      aria-label={t("ot.chooseAll")}
                      checked={chosen.length === checkable.length}
                      onChange={(e) => setChosen(e.target.checked ? checkable : [])}
                    />
                  )}
                </th>
                <th>{t("att.employee")}</th>
                <th className="num">{t("ot.working")}</th>
                <th className="num">{t("ot.sunday")}</th>
                <th className="num">{t("ot.holiday")}</th>
                <th className="num">{t("ot.short")}</th>
                <th className="num">{t("ot.nopayTime")}</th>
                <th className="num">{t("ot.nopayDays")}</th>
                <th>{t("ot.checked")}</th>
              </tr>
            </thead>
            <tbody>
              {d.rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="muted">
                    {t("ot.none")}
                  </td>
                </tr>
              )}
              {d.rows.map((r) => (
                <tr key={r.employee.id}>
                  <td>
                    {r.can_check && (
                      <input
                        type="checkbox"
                        aria-label={`${t("ot.choose")} ${r.employee.number}`}
                        checked={chosen.includes(r.employee.id)}
                        onChange={(e) =>
                          setChosen((c) => (e.target.checked ? [...c, r.employee.id] : c.filter((x) => x !== r.employee.id)))
                        }
                      />
                    )}
                  </td>
                  <td>
                    {r.employee.number} {r.employee.name}
                    {r.employee.section && <span className="muted"> {r.employee.section}</span>}
                  </td>
                  <td className="num">{r.ot_working}</td>
                  <td className="num">{r.ot_sunday}</td>
                  <td className="num">{r.ot_holiday}</td>
                  <td className="num">
                    {r.short} ({t("ot.shortLeaves", { count: r.short_leaves })})
                  </td>
                  <td className="num">{r.nopay_time}</td>
                  <td className="num">{r.nopay_days}</td>
                  <td>{r.checked_by ? t("ot.checkedBy", { name: r.checked_by }) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {checkable.length > 0 && (
        <div className="row-actions">
          <button type="button" disabled={chosen.length === 0 || check.isPending} onClick={() => check.mutate()}>
            {t("ot.check", { count: chosen.length })}
          </button>
        </div>
      )}
      <ErrorLine error={check.error} />
    </main>
  );
}
