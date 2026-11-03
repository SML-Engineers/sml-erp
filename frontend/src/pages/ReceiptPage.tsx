import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { ApiError } from "../api/client";
import {
  approveReceipt,
  getReceipt,
  receiptPdfUrl,
  receiptsKey,
  rejectReceipt,
  type ReceiptDetail,
} from "../api/receipts";
import { formatDecimal } from "../lib/decimal";

/** One customer receipt (P2-07): the invoices it pays, the Accountant's approval, the printed
 * receipt. */
export default function ReceiptPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const queryClient = useQueryClient();
  const receipt = useQuery({ queryKey: [...receiptsKey, "one", id], queryFn: () => getReceipt(Number(id)) });
  const [comment, setComment] = useState("");
  const [reason, setReason] = useState("");
  const done = (latest: ReceiptDetail) => {
    queryClient.setQueryData([...receiptsKey, "one", id], latest);
    void queryClient.invalidateQueries({ queryKey: [...receiptsKey, "list"] });
  };
  const act = useMutation({ mutationFn: (call: () => Promise<ReceiptDetail>) => call(), onSuccess: done });
  const r = receipt.data;
  const error = receipt.error ?? act.error;

  return (
    <main className="page">
      <p>
        <Link to="/receipts">{t("receipts.backToList")}</Link>
      </p>
      <h1>
        {t("advances.receipt")} {r?.number}
      </h1>
      {r && (
        <section className="panel" aria-label={t("advances.details")}>
          <p>
            <strong>{t(`receipts.statuses.${r.status}`)}</strong> · {r.receipt_date} · {t("vouchers.createdBy", { name: r.created_by })}
          </p>
          <dl className="details">
            <dt>{t("quotations.customer")}</dt>
            <dd>
              {r.customer.code} {r.customer.name}
            </dd>
            <dt>{t("advances.amount")}</dt>
            <dd>
              {r.currency ?? "LKR"} {formatDecimal(r.amount)}
              {r.currency && r.currency !== "LKR" && r.amount_lkr && ` = LKR ${formatDecimal(r.amount_lkr)} (${r.exchange_rate ?? ""})`}
            </dd>
            <dt>{t("advances.method")}</dt>
            <dd>
              {t(`advances.methods.${r.method}`)} {r.reference}
              {r.account ? ` → ${r.account.code} ${r.account.name}` : ""}
            </dd>
            {r.method === "cheque" && (
              <>
                <dt>{t("receipts.chequeDate")}</dt>
                <dd>
                  {r.cheque_date}
                  {r.cheque_bank && ` · ${r.cheque_bank}`}
                </dd>
              </>
            )}
            {r.journal_entry && (
              <>
                <dt>{t("advances.journal")}</dt>
                <dd>{r.journal_entry.number}</dd>
              </>
            )}
            {r.notes && (
              <>
                <dt>{t("customers.field.notes")}</dt>
                <dd>{r.notes}</dd>
              </>
            )}
          </dl>
          {r.status === "post_dated" && <p className="muted">{t("receipts.postDatedHelp", { date: r.cheque_date })}</p>}
          <div className="table-wrap">
            <table aria-label={t("receipts.invoices")}>
              <thead>
                <tr>
                  <th>{t("receipts.invoice")}</th>
                  <th>{t("vouchers.date")}</th>
                  <th>{t("vouchers.division")}</th>
                  <th className="num">{t("receipts.total")}</th>
                  <th className="num">{t("receipts.pay")}</th>
                </tr>
              </thead>
              <tbody>
                {r.allocations.map((a) => (
                  <tr key={a.invoice.id}>
                    <td className="mono">{a.invoice.number}</td>
                    <td>{a.invoice.invoice_date}</td>
                    <td>{a.invoice.division}</td>
                    <td className="num">{formatDecimal(a.invoice.total_amount)}</td>
                    <td className="num">{formatDecimal(a.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            <a className="button-link secondary" href={receiptPdfUrl(r.id)} target="_blank" rel="noreferrer">
              {t("advances.printReceipt")}
            </a>
          </p>
          {r.can_approve && (
            <div className="inline-form" role="group" aria-label={t("advances.decision")}>
              <label>
                {t("quotations.approverNote")}
                <input value={comment} maxLength={500} onChange={(e) => setComment(e.target.value)} />
              </label>
              <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => approveReceipt(r.id, comment))}>
                {t("advances.approve")}
              </button>
              <label>
                {t("advances.rejectReason")}
                <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
              </label>
              <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => rejectReceipt(r.id, reason))}>
                {t("advances.reject")}
              </button>
            </div>
          )}
          {r.history.length > 0 && (
            <ul className="changes" aria-label={t("quotations.approvalHistory")}>
              {r.history.map((h, i) => (
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
