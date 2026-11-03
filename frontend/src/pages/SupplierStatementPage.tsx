import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { ApiError } from "../api/client";
import { checkSupplierStatement, getSupplierStatement, payablesKey, type StatementLine } from "../api/payables";
import { formatDecimal } from "../lib/decimal";

function amount(line: StatementLine): string {
  return line.debit !== "0.00" ? formatDecimal(line.debit) : `-${formatDecimal(line.credit)}`;
}

/** One supplier statement checked against our records (P2-10): what agrees, what is only on
 * theirs, what is only in ours, and the two balances. */
export default function SupplierStatementPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const queryClient = useQueryClient();
  const key = [...payablesKey, "statement", id];
  const statement = useQuery({ queryKey: key, queryFn: () => getSupplierStatement(Number(id)) });
  const [note, setNote] = useState("");
  const check = useMutation({
    mutationFn: () => checkSupplierStatement(Number(id), note),
    onSuccess: (latest) => queryClient.setQueryData(key, latest),
  });
  const s = statement.data;
  const r = s?.reconciliation;
  const error = statement.error ?? check.error;

  return (
    <main className="page">
      <p>
        <Link to="/supplier-statements">{t("ap.backToStatements")}</Link>
      </p>
      {s && r && (
        <>
          <h1>
            {t("ap.statementOf", { name: s.supplier.name, date: s.statement_date })}
          </h1>
          <section className="panel" aria-label={t("ar.summary")}>
            <p>
              <strong>{t(`ap.statuses.${s.status}`)}</strong> · {r.from} – {r.to} · {s.currency}
            </p>
            <dl className="details">
              <dt>{t("ap.theirBalance")}</dt>
              <dd>{formatDecimal(r.their_balance)}</dd>
              <dt>{t("ap.ourBalance")}</dt>
              <dd>{r.our_balance === null ? t("ap.foreignNote") : formatDecimal(r.our_balance)}</dd>
              {r.difference !== null && (
                <>
                  <dt>{t("ap.difference")}</dt>
                  <dd>
                    <strong>{formatDecimal(r.difference)}</strong>
                  </dd>
                </>
              )}
            </dl>
            {s.status === "checked" && <p>{t("ap.checkedBy", { name: s.checked_by ?? "", note: s.check_note })}</p>}
          </section>
          <section className="panel" aria-label={t("ap.theirsOnly")}>
            <h2>{t("ap.theirsOnly")}</h2>
            {r.theirs_only.length === 0 ? (
              <p className="muted">{t("ap.nothing")}</p>
            ) : (
              <ul>
                {r.theirs_only.map((line) => (
                  <li key={line.line_no}>
                    {line.date} · {line.reference} · {line.description} · {amount(line)}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="panel" aria-label={t("ap.oursOnly")}>
            <h2>{t("ap.oursOnly")}</h2>
            {r.ours_only.length === 0 ? (
              <p className="muted">{t("ap.nothing")}</p>
            ) : (
              <ul>
                {r.ours_only.map((row, i) => (
                  <li key={i}>
                    {row.date} · {row.reference} · <Link to={row.link}>{row.document}</Link> ·{" "}
                    {row.side === "charge" ? formatDecimal(row.amount) : `-${formatDecimal(row.amount)}`}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="panel" aria-label={t("ap.matched")}>
            <h2>{t("ap.matched")}</h2>
            <div className="table-wrap">
              <table aria-label={t("ap.matched")}>
                <thead>
                  <tr>
                    <th>{t("vouchers.date")}</th>
                    <th>{t("ar.reference")}</th>
                    <th>{t("ap.document")}</th>
                    <th className="num">{t("ap.theirAmount")}</th>
                    <th className="num">{t("ap.difference")}</th>
                  </tr>
                </thead>
                <tbody>
                  {r.matched.map((m) => (
                    <tr key={m.line.line_no}>
                      <td>{m.line.date}</td>
                      <td>{m.line.reference}</td>
                      <td>
                        <Link to={m.ours.link}>{m.ours.document}</Link>
                      </td>
                      <td className="num">{amount(m.line)}</td>
                      <td className="num">{m.difference !== "0.00" ? <strong>{formatDecimal(m.difference)}</strong> : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          {s.can_check && (
            <form
              className="inline-form"
              aria-label={t("ap.check")}
              onSubmit={(e) => {
                e.preventDefault();
                check.mutate();
              }}
            >
              <label>
                {t("ap.checkNote")}
                <input value={note} required maxLength={2000} onChange={(e) => setNote(e.target.value)} />
              </label>
              <button type="submit" disabled={check.isPending}>
                {t("ap.markChecked")}
              </button>
            </form>
          )}
        </>
      )}
      {error ? (
        <p className="form-error" role="alert">
          {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
        </p>
      ) : null}
    </main>
  );
}
