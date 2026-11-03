import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import { allowCreditHold, listCreditHolds, receivablesKey, type CreditHold } from "../api/receivables";
import { formatDecimal } from "../lib/decimal";

/** Sales orders and tax invoices stopped by credit control (P2-08): the Director allows each
 * one, with a note. */
export default function CreditHoldsPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "waiting";
  const holds = useQuery({ queryKey: [...receivablesKey, "holds", status], queryFn: () => listCreditHolds(status) });

  return (
    <main className="page">
      <h1>{t("holds.title")}</h1>
      <p className="muted">{t("holds.help")}</p>
      <div className="toolbar">
        <label>
          {t("vouchers.status")}
          <select value={status} onChange={(e) => setParams({ status: e.target.value }, { replace: true })}>
            <option value="waiting">{t("holds.statuses.waiting")}</option>
            <option value="allowed">{t("holds.statuses.allowed")}</option>
            <option value="">{t("advances.allStatuses")}</option>
          </select>
        </label>
      </div>
      {holds.data && holds.data.length === 0 && <p className="muted">{t("holds.none")}</p>}
      {holds.data?.map((hold) => <HoldCard key={hold.id} hold={hold} />)}
    </main>
  );
}

function HoldCard({ hold }: { hold: CreditHold }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const allow = useMutation({
    mutationFn: () => allowCreditHold(hold.id, note),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: receivablesKey }),
  });

  return (
    <section className="panel" aria-label={hold.document_label}>
      <h2>
        <Link to={hold.link}>{hold.document_label}</Link> · <Link to={`/receivables/${hold.customer.id}`}>{hold.customer.name}</Link>
      </h2>
      <p>
        <strong>{t(`holds.statuses.${hold.status}`)}</strong> · {t("holds.stoppedBy", { name: hold.requested_by })} ·{" "}
        {hold.requested_at.slice(0, 16).replace("T", " ")}
      </p>
      <ul>
        {hold.reasons.split("\n").map((reason, i) => (
          <li key={i}>{reason}</li>
        ))}
      </ul>
      <dl className="details">
        <dt>{t("holds.amount")}</dt>
        <dd>LKR {formatDecimal(hold.amount_lkr)}</dd>
        <dt>{t("holds.exposure")}</dt>
        <dd>LKR {formatDecimal(hold.exposure_lkr)}</dd>
        <dt>{t("ar.creditLimit")}</dt>
        <dd>{hold.credit_limit === null ? t("ar.noLimit") : `LKR ${formatDecimal(hold.credit_limit)}`}</dd>
        <dt>{t("ar.overdue")}</dt>
        <dd>LKR {formatDecimal(hold.overdue_lkr)}</dd>
      </dl>
      {hold.status === "allowed" && (
        <p>{t("holds.allowedBy", { name: hold.decided_by ?? "", note: hold.note })}</p>
      )}
      {hold.can_allow && (
        <form
          className="inline-form"
          aria-label={t("holds.decision")}
          onSubmit={(e) => {
            e.preventDefault();
            allow.mutate();
          }}
        >
          <label>
            {t("holds.note")}
            <input value={note} maxLength={1000} required onChange={(e) => setNote(e.target.value)} />
          </label>
          <button type="submit" disabled={allow.isPending}>
            {t("holds.allow")}
          </button>
        </form>
      )}
      {allow.error ? (
        <p className="form-error" role="alert">
          {allow.error instanceof ApiError && allow.error.detail ? allow.error.detail : t("common.error")}
        </p>
      ) : null}
    </section>
  );
}
