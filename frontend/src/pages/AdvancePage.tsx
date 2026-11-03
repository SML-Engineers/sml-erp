import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import {
  advancesKey,
  approveAdvance,
  getAdvance,
  receiptUrl,
  rejectAdvance,
  setOffAdvance,
  type AdvanceDetail,
} from "../api/advances";
import { ApiError } from "../api/client";
import { compareDecimal, formatDecimal } from "../lib/decimal";

/** One customer advance: its details, the Accountant's approval, and the receipt. */
export default function AdvancePage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const queryClient = useQueryClient();
  const advance = useQuery({ queryKey: [...advancesKey, "one", id], queryFn: () => getAdvance(Number(id)) });
  const [comment, setComment] = useState("");
  const [reason, setReason] = useState("");
  const [setOff, setSetOff] = useState({ invoice: "", amount: "" });
  const done = (latest: AdvanceDetail) => {
    queryClient.setQueryData([...advancesKey, "one", id], latest);
    void queryClient.invalidateQueries({ queryKey: [...advancesKey, "list"] });
  };
  const act = useMutation({ mutationFn: (call: () => Promise<AdvanceDetail>) => call(), onSuccess: done });
  const a = advance.data;
  const error = advance.error ?? act.error;

  return (
    <main className="page">
      <p>
        <Link to="/advances">{t("advances.backToList")}</Link>
      </p>
      <h1>
        {t("advances.receipt")} {a?.number}
      </h1>
      {a && (
        <section className="panel" aria-label={t("advances.details")}>
          <p>
            <strong>{t(`advances.statuses.${a.status}`)}</strong> · {a.receipt_date} · {a.division} ·{" "}
            {t("vouchers.createdBy", { name: a.created_by })}
          </p>
          <dl className="details">
            <dt>{t("quotations.customer")}</dt>
            <dd>
              {a.customer.code} {a.customer.name}
            </dd>
            {a.quotation && (
              <>
                <dt>{t("advances.againstQuotation")}</dt>
                <dd>{a.quotation.label}</dd>
              </>
            )}
            <dt>{t("advances.amount")}</dt>
            <dd>
              {a.currency} {formatDecimal(a.amount)}
              {a.currency !== "LKR" && ` = LKR ${formatDecimal(a.amount_lkr)} (${a.exchange_rate})`}
            </dd>
            <dt>{t("advances.method")}</dt>
            <dd>
              {t(`advances.methods.${a.method}`)} {a.reference} → {a.account.code} {a.account.name}
            </dd>
            {a.journal_entry && (
              <>
                <dt>{t("advances.journal")}</dt>
                <dd>{a.journal_entry.number}</dd>
                <dt>{t("advances.balance")}</dt>
                <dd>LKR {formatDecimal(a.balance_lkr)}</dd>
              </>
            )}
            {a.notes && (
              <>
                <dt>{t("customers.field.notes")}</dt>
                <dd>{a.notes}</dd>
              </>
            )}
          </dl>
          <p>
            <a className="button-link secondary" href={receiptUrl(a.id)} target="_blank" rel="noreferrer">
              {t("advances.printReceipt")}
            </a>
          </p>
          {a.can_approve && (
            <div className="inline-form" role="group" aria-label={t("advances.decision")}>
              <label>
                {t("quotations.approverNote")}
                <input value={comment} maxLength={500} onChange={(e) => setComment(e.target.value)} />
              </label>
              <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => approveAdvance(a.id, comment))}>
                {t("advances.approve")}
              </button>
              <label>
                {t("advances.rejectReason")}
                <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
              </label>
              <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => rejectAdvance(a.id, reason))}>
                {t("advances.reject")}
              </button>
            </div>
          )}
          {(a.set_offs ?? []).length > 0 && (
            <>
              <h2>{t("receipts.setOffs")}</h2>
              <ul aria-label={t("receipts.setOffs")}>
                {(a.set_offs ?? []).map((s, i) => (
                  <li key={i}>
                    {s.set_off_date} · <Link to={`/tax-invoices/${s.invoice.id}`} className="mono">{s.invoice.number}</Link> · LKR{" "}
                    {formatDecimal(s.amount)} · {s.journal_entry} · {s.by}
                  </li>
                ))}
              </ul>
            </>
          )}
          {a.can_set_off && (
            <form
              className="inline-form"
              aria-label={t("receipts.setOffNew")}
              onSubmit={(e) => {
                e.preventDefault();
                act.mutate(() => setOffAdvance(a.id, Number(setOff.invoice), setOff.amount.replace(/,/g, "")), {
                  onSuccess: () => setSetOff({ invoice: "", amount: "" }),
                });
              }}
            >
              <label>
                {t("receipts.invoice")}
                <select
                  value={setOff.invoice}
                  required
                  onChange={(e) => {
                    const chosen = (a.open_invoices ?? []).find((i) => String(i.id) === e.target.value);
                    const left = a.balance_lkr;
                    const amount = chosen ? (compareDecimal(chosen.open_amount, left) < 0 ? chosen.open_amount : left) : "";
                    setSetOff({ invoice: e.target.value, amount });
                  }}
                >
                  <option value="">—</option>
                  {(a.open_invoices ?? []).map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.number} ({t("receipts.open")} {formatDecimal(i.open_amount)})
                    </option>
                  ))}
                </select>
              </label>
              <label>
                {t("advances.amountIn", { currency: "LKR" })}
                <input inputMode="decimal" className="num" value={setOff.amount} required onChange={(e) => setSetOff({ ...setOff, amount: e.target.value })} />
              </label>
              <button type="submit" disabled={act.isPending}>
                {t("receipts.setOff")}
              </button>
            </form>
          )}
          {a.history.length > 0 && (
            <ul className="changes" aria-label={t("quotations.approvalHistory")}>
              {a.history.map((h, i) => (
                <li key={i}>
                  {h.action_label} · {h.by} · {h.at.slice(0, 16).replace("T", " ")}
                  {h.reason && ` · ${h.reason}`}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {error ? (
        <p className="form-error" role="alert">
          {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
        </p>
      ) : null}
    </main>
  );
}
