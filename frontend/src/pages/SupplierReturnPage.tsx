import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError } from "../api/client";
import { approveReturn, confirmReturn, deleteReturn, getReturn, rtnKey, sendBackReturn, type ReturnDetail } from "../api/supplierReturns";
import { formatDecimal, formatQuantity } from "../lib/decimal";

/** One supplier return (P16-12): its lots, the Director's approval for accepted goods, and
 * the debit notes. */
export default function SupplierReturnPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const ret = useQuery({ queryKey: [...rtnKey, "one", id], queryFn: () => getReturn(Number(id)) });
  const [text, setText] = useState("");
  const done = (latest: ReturnDetail) => {
    queryClient.setQueryData([...rtnKey, "one", String(latest.id)], latest);
    void queryClient.invalidateQueries({ queryKey: [...rtnKey, "list"] });
    setText("");
  };
  const act = useMutation({ mutationFn: (call: () => Promise<ReturnDetail>) => call(), onSuccess: done });
  const remove = useMutation({
    mutationFn: () => deleteReturn(Number(id)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: rtnKey });
      navigate("/supplier-returns");
    },
  });
  const data = ret.data;
  const error = act.error ?? remove.error ?? ret.error;
  return (
    <main className="page">
      <p>
        <Link to="/supplier-returns">{t("rtn.backToList")}</Link>
      </p>
      <h1>{`${t("rtn.one")} ${data?.number ?? ""}`}</h1>
      {data && (
        <>
          <p className="muted">
            {t(`rtn.statuses.${data.status}`)} · {t(`rtn.kinds.${data.kind}`)} · {data.return_date} · {data.supplier.name} ·{" "}
            <Link to={`/goods-receipts/${data.grn.id}`}>{data.grn.number}</Link>
            {data.vehicle_no && ` · ${data.vehicle_no}`}
            {data.journal && ` · ${t("si.posted", { journal: data.journal })}`}
          </p>
          <p>{t("rtn.reasonGiven", { reason: data.reason })}</p>
          <p>
            <a className="button-link secondary" href={`/api/v1/supplier-returns/${data.id}/pdf/`} target="_blank" rel="noreferrer">
              {t("rtn.print")}
            </a>
          </p>
          <div className="table-wrap">
            <table aria-label={t("rtn.lines")}>
              <thead>
                <tr>
                  <th>{t("stock.lot")}</th>
                  <th>{t("po.item")}</th>
                  <th className="num">{t("rtn.toReturn")}</th>
                  {data.kind === "accepted" && data.status === "confirmed" && (
                    <>
                      <th className="num">{t("rtn.notInvoiced")}</th>
                      <th className="num">{t("rtn.invoiced")}</th>
                      <th className="num">{t("stock.value")}</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {data.lines.map((l) => (
                  <tr key={l.line_no}>
                    <td className="mono">{l.lot_no}</td>
                    <td>
                      <span className="mono">{l.item.code}</span> {l.item.name}
                    </td>
                    <td className="num">
                      {formatQuantity(l.quantity)} {l.item.unit}
                    </td>
                    {data.kind === "accepted" && data.status === "confirmed" && (
                      <>
                        <td className="num">{formatQuantity(l.uninvoiced_quantity)}</td>
                        <td className="num">{formatQuantity(l.invoiced_quantity)}</td>
                        <td className="num">{formatDecimal(l.value)}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.debit_notes.length > 0 && (
            <section className="panel" aria-label={t("rtn.debitNotes")}>
              <h2>{t("rtn.debitNotes")}</h2>
              <ul>
                {data.debit_notes.map((d) => (
                  <li key={d.number}>
                    {t("rtn.debitNote", { number: d.number, amount: formatDecimal(d.total_lkr), qty: formatQuantity(d.quantity) })}{" "}
                    <Link to={`/supplier-invoices/${d.invoice.id}`}>{d.invoice.invoice_no}</Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {(data.can_edit || data.can_approve) && (
            <section className="panel" aria-label={t("rtn.actions")}>
              {data.can_edit && (
                <p>
                  <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => confirmReturn(data.id))}>
                    {data.kind === "accepted" ? t("rtn.sendToDirector") : t("rtn.confirm")}
                  </button>{" "}
                  <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate()}>
                    {t("rtn.delete")}
                  </button>
                </p>
              )}
              {data.can_approve && (
                <div className="inline-form">
                  <label>
                    {t("salesOrders.comment")}
                    <input value={text} maxLength={500} onChange={(e) => setText(e.target.value)} />
                  </label>
                  <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => approveReturn(data.id, text))}>
                    {t("rtn.approve")}
                  </button>
                  <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => sendBackReturn(data.id, text))}>
                    {t("salesOrders.sendBack")}
                  </button>
                </div>
              )}
            </section>
          )}
          {data.history.length > 0 && (
            <ul className="changes">
              {data.history.map((h, i) => (
                <li key={i}>
                  {h.at.slice(0, 16).replace("T", " ")} · {h.action_label} · {h.by}
                  {h.reason ? ` · ${h.reason}` : ""}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
        </p>
      )}
    </main>
  );
}
