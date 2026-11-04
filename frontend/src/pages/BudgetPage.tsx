import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import {
  budgetAction,
  budgetExportUrl,
  budgetsKey,
  discardBudget,
  getBudget,
  importBudget,
  saveBudget,
  type BudgetDetail,
  type BudgetRowInput,
} from "../api/budgets";
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

interface EditRow {
  key: number;
  account: string; // account id, "" until chosen
  division: string;
  amounts: Record<string, string>;
}

let nextKey = 1;

function toEdit(data: BudgetDetail): EditRow[] {
  return data.rows.map((r) => ({
    key: nextKey++,
    account: String(r.account.id),
    division: r.division,
    amounts: { ...r.amounts },
  }));
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function monthLabel(month: string): string {
  const [y, m] = month.split("-");
  return `${MONTHS[Number(m) - 1]} ${y.slice(2)}`;
}

/** One budget version (P2-22): the grid of accounts, divisions and months; Excel import and
 * export; sending it to the Director, who approves, returns or rejects it. */
export default function BudgetPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const budgetId = Number(id);
  const query = useQuery({ queryKey: [...budgetsKey, budgetId], queryFn: () => getBudget(budgetId) });
  const data = query.data;
  const [rows, setRows] = useState<EditRow[]>([]);
  const [notes, setNotes] = useState("");
  const [reason, setReason] = useState("");
  const [file, setFile] = useState<File | null>(null);

  useEffect(() => {
    if (data) {
      setRows(toEdit(data));
      setNotes(data.notes);
    }
  }, [data]);

  const fresh = (got: BudgetDetail | null) => {
    if (got) queryClient.setQueryData([...budgetsKey, budgetId], got);
    void queryClient.invalidateQueries({ queryKey: budgetsKey });
  };
  const save = useMutation({
    mutationFn: () => {
      const given: BudgetRowInput[] = rows
        .filter((r) => r.account)
        .map((r) => ({ account: Number(r.account), division: r.division, amounts: r.amounts }));
      return saveBudget(budgetId, notes, given);
    },
    onSuccess: fresh,
  });
  const upload = useMutation({ mutationFn: (f: File) => importBudget(budgetId, f), onSuccess: fresh });
  const act = useMutation({
    mutationFn: (action: "submit" | "approve" | "return" | "reject") => budgetAction(budgetId, action, reason),
    onSuccess: (got) => {
      setReason("");
      fresh(got);
    },
  });
  const discard = useMutation({
    mutationFn: () => discardBudget(budgetId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: budgetsKey });
      void navigate("/budgets");
    },
  });

  if (!data) {
    return (
      <main className="page">
        <ErrorLine error={query.error} />
      </main>
    );
  }
  const editing = data.can_edit;
  const setRow = (key: number, change: Partial<EditRow>) =>
    setRows(rows.map((r) => (r.key === key ? { ...r, ...change } : r)));
  const rowTotal = (r: EditRow) =>
    Object.values(r.amounts)
      .map((v) => Number(String(v).replace(/,/g, "")) || 0)
      .reduce((a, b) => a + b, 0)
      .toFixed(2);

  return (
    <main className="page">
      <p>
        <Link to="/budgets">{t("budget.title")}</Link>
      </p>
      <h1>
        {t("budget.heading", { label: data.label, version: data.version })} · {t(`budget.statuses.${data.status}`)}
      </h1>
      <dl className="details">
        <dt>{t("budget.income")}</dt>
        <dd>LKR {formatDecimal(data.income)}</dd>
        <dt>{t("budget.costs")}</dt>
        <dd>LKR {formatDecimal(data.costs)}</dd>
        <dt>{t("budget.preparedBy")}</dt>
        <dd>{data.created_by}</dd>
      </dl>
      {editing ? (
        <label className="stacked">
          {t("budget.notes")}
          <input value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
      ) : (
        data.notes && <p>{data.notes}</p>
      )}

      <section className="panel" aria-label={t("budget.grid")}>
        <h2>
          {t("budget.grid")}{" "}
          <a className="button-link secondary small" href={budgetExportUrl(budgetId)}>
            {t("budget.export")}
          </a>
        </h2>
        <p className="muted">{t("budget.gridHelp")}</p>
        <div className="table-wrap">
          <table aria-label={t("budget.gridOf", { label: data.label })}>
            <thead>
              <tr>
                <th>{t("budget.account")}</th>
                <th>{t("budget.division")}</th>
                {data.months.map((m) => (
                  <th key={m} className="num">
                    {monthLabel(m)}
                  </th>
                ))}
                <th className="num">{t("budget.total")}</th>
              </tr>
            </thead>
            <tbody>
              {!editing &&
                data.rows.map((r) => (
                  <tr key={`${r.account.id}-${r.division}`}>
                    <td>
                      <span className="mono">{r.account.number}</span> {r.account.name}
                    </td>
                    <td>{r.division}</td>
                    {data.months.map((m) => (
                      <td key={m} className="num">
                        {r.amounts[m] ? formatDecimal(r.amounts[m]) : ""}
                      </td>
                    ))}
                    <td className="num">{formatDecimal(r.total)}</td>
                  </tr>
                ))}
              {editing &&
                rows.map((r, n) => (
                  <tr key={r.key}>
                    <td>
                      <select
                        aria-label={t("budget.accountOfRow", { n: n + 1 })}
                        value={r.account}
                        onChange={(e) => setRow(r.key, { account: e.target.value })}
                      >
                        <option value="">{t("budget.chooseAccount")}</option>
                        {data.accounts?.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.number} {a.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <select
                        aria-label={t("budget.divisionOfRow", { n: n + 1 })}
                        value={r.division}
                        onChange={(e) => setRow(r.key, { division: e.target.value })}
                      >
                        {data.divisions?.map((d) => (
                          <option key={d} value={d}>
                            {d}
                          </option>
                        ))}
                      </select>
                    </td>
                    {data.months.map((m) => (
                      <td key={m} className="num">
                        <input
                          className="amount"
                          inputMode="decimal"
                          aria-label={t("budget.amountOf", { n: n + 1, month: monthLabel(m) })}
                          value={r.amounts[m] ?? ""}
                          onChange={(e) => setRow(r.key, { amounts: { ...r.amounts, [m]: e.target.value } })}
                        />
                      </td>
                    ))}
                    <td className="num">{formatDecimal(rowTotal(r))}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        {editing && (
          <>
            <div className="row-actions">
              <button
                type="button"
                className="secondary"
                onClick={() =>
                  setRows([...rows, { key: nextKey++, account: "", division: data.divisions?.[0] ?? "", amounts: {} }])
                }
              >
                {t("budget.addRow")}
              </button>
              <button type="button" disabled={save.isPending} onClick={() => save.mutate()}>
                {t("budget.save")}
              </button>
            </div>
            <div className="inline-form">
              <input
                type="file"
                accept=".xlsx"
                aria-label={t("budget.importFile")}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <button
                type="button"
                className="secondary"
                disabled={!file || upload.isPending}
                onClick={() => file && upload.mutate(file)}
              >
                {t("budget.import")}
              </button>
            </div>
            <p className="muted">{t("budget.importHelp")}</p>
          </>
        )}
        <ErrorLine error={save.error ?? upload.error} />
      </section>

      {(editing || data.can_approve) && (
        <section className="panel" aria-label={t("budget.decision")}>
          <h2>{t("budget.decision")}</h2>
          <label className="stacked">
            {data.can_approve ? t("budget.reasonOrComment") : t("budget.comment")}
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div className="row-actions">
            {editing && (
              <>
                <button type="button" disabled={act.isPending} onClick={() => act.mutate("submit")}>
                  {t("budget.submit")}
                </button>
                {!data.approval && (
                  <button type="button" className="secondary" disabled={discard.isPending} onClick={() => discard.mutate()}>
                    {t("budget.discard")}
                  </button>
                )}
              </>
            )}
            {data.can_approve && (
              <>
                <button type="button" disabled={act.isPending} onClick={() => act.mutate("approve")}>
                  {t("budget.approve")}
                </button>
                <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("return")}>
                  {t("budget.return")}
                </button>
                <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("reject")}>
                  {t("budget.reject")}
                </button>
              </>
            )}
          </div>
          {editing && <p className="muted">{t("budget.saveFirst")}</p>}
          <ErrorLine error={act.error ?? discard.error} />
        </section>
      )}

      {data.approval && (
        <section className="panel" aria-label={t("budget.history")}>
          <h2>{t("budget.history")}</h2>
          <ul>
            {data.approval.history.map((h, i) => (
              <li key={i}>
                {h.action_label} · {h.by} · {h.at.slice(0, 16).replace("T", " ")}
                {h.reason && ` · ${h.reason}`}
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
