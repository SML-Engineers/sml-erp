import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { canDo } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import { changePeriod, listPeriods, periodsKey, type PeriodMonth } from "../api/journal";

/** Months of the year, open or closed. The Director closes a month once its books are done. */
export default function PeriodsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [year, setYear] = useState(new Date().getFullYear());
  const [reason, setReason] = useState("");
  const periods = useQuery({ queryKey: [...periodsKey, year], queryFn: () => listPeriods(year) });
  const canClose = canDo(me.access, "close_period");
  const change = useMutation({
    mutationFn: (row: PeriodMonth) => changePeriod(row.month, row.is_closed ? "reopen" : "close", reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: periodsKey });
      setReason("");
    },
  });
  const thisMonth = new Date().toISOString().slice(0, 7);

  return (
    <main className="page">
      <h1>{t("periods.title")}</h1>
      <p className="muted">{t("periods.help")}</p>
      <div className="toolbar">
        <button type="button" className="secondary" onClick={() => setYear(year - 1)}>
          {t("periods.previous")}
        </button>
        <strong aria-live="polite">{year}</strong>
        <button type="button" className="secondary" onClick={() => setYear(year + 1)}>
          {t("periods.next")}
        </button>
        {canClose && (
          <label>
            {t("access.reason")}
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
        )}
      </div>
      {periods.data && (
        <div className="table-wrap">
          <table aria-label={t("periods.title")}>
            <thead>
              <tr>
                <th>{t("periods.month")}</th>
                <th className="num">{t("periods.entries")}</th>
                <th>{t("users.status")}</th>
                <th>{t("periods.changedBy")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {periods.data.months.map((row) => (
                <tr key={row.month}>
                  <td className="mono">{row.month}</td>
                  <td className="num">{row.entries}</td>
                  <td>{row.is_closed ? t("periods.closed") : t("periods.open")}</td>
                  <td>{row.changed_by ?? ""}</td>
                  <td>
                    {canClose && (row.is_closed || row.month < thisMonth) && (
                      <button
                        type="button"
                        className={row.is_closed ? "small secondary" : "small"}
                        disabled={change.isPending}
                        onClick={() => change.mutate(row)}
                      >
                        {row.is_closed
                          ? t("periods.reopen", { month: row.month })
                          : t("periods.close", { month: row.month })}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {change.error && (
        <p className="form-error" role="alert">
          {change.error instanceof ApiError && change.error.detail ? change.error.detail : t("common.error")}
        </p>
      )}
    </main>
  );
}
