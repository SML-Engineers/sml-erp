import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ApiError } from "../api/client";
import {
  discardRevaluation,
  listRevaluations,
  postRevaluation,
  prepareRevaluation,
  revaluationKey,
  type RevaluationRow,
} from "../api/revaluation";
import { formatDecimal } from "../lib/decimal";

function lastMonth(): string {
  const now = new Date();
  const d = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** Month-end revaluation (P2-21): open foreign-currency invoices and bank balances valued at
 * the month-end rate, checked by the Accountant and posted. */
export default function RevaluationPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [month, setMonth] = useState(lastMonth());
  const [typed, setTyped] = useState<Record<string, string>>({});
  const list = useQuery({
    queryKey: [...revaluationKey, month],
    queryFn: () => listRevaluations(`${month}-01`),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: revaluationKey });
  const prepare = useMutation({
    mutationFn: () => {
      const balances: Record<string, string> = {};
      for (const a of list.data?.accounts ?? []) {
        const value = typed[a.id] ?? a.statement_balance ?? "";
        if (value.trim() !== "") balances[String(a.id)] = value.trim();
      }
      return prepareRevaluation(`${month}-01`, balances);
    },
    onSuccess: refresh,
  });
  const post = useMutation({ mutationFn: (id: number) => postRevaluation(id), onSuccess: refresh });
  const discard = useMutation({ mutationFn: (id: number) => discardRevaluation(id), onSuccess: refresh });
  const accounts = list.data?.accounts ?? [];
  return (
    <main className="page">
      <h1>{t("reval.title")}</h1>
      <p className="muted">{t("reval.help")}</p>
      <section className="panel" aria-label={t("reval.workOut")}>
        <h2>{t("reval.workOut")}</h2>
        <div className="toolbar">
          <label>
            {t("reval.month")}
            <input type="month" value={month} onChange={(e) => e.target.value && setMonth(e.target.value)} />
          </label>
        </div>
        {accounts.length > 0 && (
          <>
            <p className="muted">{t("reval.balancesHelp")}</p>
            <div className="table-wrap">
              <table aria-label={t("reval.balances")}>
                <thead>
                  <tr>
                    <th>{t("reval.account")}</th>
                    <th>{t("reval.currency")}</th>
                    <th>{t("reval.balanceAtEnd")}</th>
                  </tr>
                </thead>
                <tbody>
                  {accounts.map((a) => (
                    <tr key={a.id}>
                      <td>
                        {a.code} {a.name}
                      </td>
                      <td>{a.currency}</td>
                      <td>
                        <input
                          aria-label={t("reval.balanceOf", { code: a.code })}
                          inputMode="decimal"
                          value={typed[a.id] ?? a.statement_balance ?? ""}
                          onChange={(e) => setTyped({ ...typed, [a.id]: e.target.value })}
                        />
                        {a.statement_date && typed[a.id] === undefined && (
                          <span className="muted"> {t("reval.fromStatement", { date: a.statement_date })}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
        <button type="button" disabled={prepare.isPending} onClick={() => prepare.mutate()}>
          {t("reval.prepare", { month })}
        </button>
        <ErrorLine error={list.error ?? prepare.error ?? post.error ?? discard.error} />
      </section>
      {list.data?.runs.map((r) => (
        <RunCard
          key={r.id}
          run={r}
          busy={post.isPending || discard.isPending}
          onPost={() => post.mutate(r.id)}
          onDiscard={() => discard.mutate(r.id)}
        />
      ))}
    </main>
  );
}

function RunCard({
  run: r,
  busy,
  onPost,
  onDiscard,
}: {
  run: RevaluationRow;
  busy: boolean;
  onPost: () => void;
  onDiscard: () => void;
}) {
  const { t } = useTranslation();
  const entries = [r.journal_entry, r.reversal_entry, r.balances_entry].filter(Boolean).join(", ");
  return (
    <section className="panel" aria-label={r.month_end}>
      <h2>
        {r.month_end.slice(0, 7)} · {t(`reval.statuses.${r.status}`)}
        {entries && ` · ${entries}`}
      </h2>
      <dl className="details">
        <dt>{t("reval.openItemsTotal")}</dt>
        <dd>LKR {formatDecimal(r.open_items_total)}</dd>
        <dt>{t("reval.balancesTotal")}</dt>
        <dd>LKR {formatDecimal(r.balances_total)}</dd>
      </dl>
      {r.lines.length === 0 ? (
        <p className="muted">{t("reval.nothing")}</p>
      ) : (
        <div className="table-wrap">
          <table aria-label={t("reval.linesOf", { month: r.month_end.slice(0, 7) })}>
            <thead>
              <tr>
                <th>{t("reval.what")}</th>
                <th>{t("reval.party")}</th>
                <th>{t("reval.division")}</th>
                <th className="num">{t("reval.open")}</th>
                <th className="num">{t("reval.carried")}</th>
                <th className="num">{t("reval.rate")}</th>
                <th className="num">{t("reval.revalued")}</th>
                <th className="num">{t("reval.difference")}</th>
              </tr>
            </thead>
            <tbody>
              {r.lines.map((x) => (
                <tr key={x.id}>
                  <td>
                    {t(`reval.kinds.${x.kind}`)}: {x.link ? <Link to={x.link}>{x.document}</Link> : x.document}
                    {x.balance_from && <div className="muted">{x.balance_from}</div>}
                  </td>
                  <td>{x.party}</td>
                  <td>{x.division}</td>
                  <td className="num">
                    {x.currency} {formatDecimal(x.open_amount)}
                  </td>
                  <td className="num">{formatDecimal(x.carried_lkr)}</td>
                  <td className="num">
                    {x.rate} <span className="muted">({x.rate_date})</span>
                  </td>
                  <td className="num">{formatDecimal(x.revalued_lkr)}</td>
                  <td className="num">{formatDecimal(x.difference)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {r.status === "draft" && (
        <div className="row-actions">
          <button type="button" disabled={busy} onClick={onPost}>
            {t("reval.post")}
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={onDiscard}>
            {t("reval.discard")}
          </button>
        </div>
      )}
    </section>
  );
}
