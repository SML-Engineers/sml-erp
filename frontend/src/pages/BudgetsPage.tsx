import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { budgetsKey, listBudgets, startBudget } from "../api/budgets";
import { ApiError } from "../api/client";
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

/** Budgets (P2-22): each financial year's versions, and a new one started by the Accountant. */
export default function BudgetsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: budgetsKey, queryFn: listBudgets });
  const [year, setYear] = useState("");
  const start = useMutation({
    mutationFn: () => startBudget(Number(year || list.data?.current_year), ""),
    onSuccess: (made) => {
      void queryClient.invalidateQueries({ queryKey: budgetsKey });
      void navigate(`/budgets/${made.id}`);
    },
  });
  const data = list.data;
  return (
    <main className="page">
      <h1>{t("budget.title")}</h1>
      <p className="muted">{t("budget.help")}</p>
      {data?.can_manage && (
        <section className="panel" aria-label={t("budget.start")}>
          <h2>{t("budget.start")}</h2>
          <div className="inline-form">
            <label>
              {t("budget.yearStarting")}
              <input
                inputMode="numeric"
                placeholder={String(data.current_year)}
                value={year}
                onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))}
              />
            </label>
            <button type="button" disabled={start.isPending} onClick={() => start.mutate()}>
              {t("budget.startButton")}
            </button>
          </div>
          <p className="muted">{t("budget.startHelp")}</p>
          <ErrorLine error={start.error} />
        </section>
      )}
      <ErrorLine error={list.error} />
      {data && (
        <div className="table-wrap">
          <table aria-label={t("budget.list")}>
            <thead>
              <tr>
                <th>{t("budget.year")}</th>
                <th>{t("budget.version")}</th>
                <th>{t("budget.status")}</th>
                <th className="num">{t("budget.income")}</th>
                <th className="num">{t("budget.costs")}</th>
                <th>{t("budget.preparedBy")}</th>
              </tr>
            </thead>
            <tbody>
              {data.budgets.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    {t("budget.none")}
                  </td>
                </tr>
              )}
              {data.budgets.map((b) => (
                <tr key={b.id}>
                  <td>
                    <Link to={`/budgets/${b.id}`}>{b.label}</Link>
                  </td>
                  <td>{b.version}</td>
                  <td>{t(`budget.statuses.${b.status}`)}</td>
                  <td className="num">{formatDecimal(b.income)}</td>
                  <td className="num">{formatDecimal(b.costs)}</td>
                  <td>{b.created_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
