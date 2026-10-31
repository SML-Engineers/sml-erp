import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { ApiError } from "../api/client";
import { INCOTERMS } from "../api/customers";
import {
  approveSalesOrder,
  cancelSalesOrder,
  completeSalesOrder,
  confirmSalesOrder,
  getSalesOrder,
  returnSalesOrder,
  salesOrdersKey,
  updateSalesOrder,
  type Delivery,
  type SalesOrderDetail,
} from "../api/salesOrders";
import { getTaxes, taxesKey } from "../api/taxes";
import { formatDecimal, formatQuantity } from "../lib/decimal";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** One sales order (spec 5.3): its lines and delivery dates, confirming, approval, closing. */
export default function SalesOrderPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const order = useQuery({ queryKey: [...salesOrdersKey, "one", id], queryFn: () => getSalesOrder(Number(id)) });
  const data = order.data;

  return (
    <main className="page">
      <p>
        <Link to="/sales-orders">{t("salesOrders.backToList")}</Link>
      </p>
      <h1>
        {t("salesOrders.order")} {data?.number}
      </h1>
      {data && (
        <>
          <p className="muted">
            {t(`salesOrders.statuses.${data.status}`)} · {data.order_date} · {data.division} · {data.customer.code} {data.customer.name}
            {data.quotation && (
              <>
                {" · "}
                <Link to={`/quotations/${data.quotation.id}`}>{data.quotation.label}</Link>
              </>
            )}
            {data.proforma && (
              <>
                {" · "}
                <Link to={`/proformas/${data.proforma.id}`}>{data.proforma.number}</Link>
              </>
            )}
          </p>
          {data.source === "direct" && <p className="notice">{t("salesOrders.directNotice")}</p>}
          {data.status === "cancelled" && <p className="notice">{t("proformas.cancelledBecause", { reason: data.cancel_reason })}</p>}
          <p className="muted">{t("salesOrders.noSale")}</p>
          {data.can_edit ? <OrderForm key={`${data.id}-${data.total_amount}-${data.status}`} order={data} /> : <ReadOnly order={data} />}
          <Actions order={data} />
        </>
      )}
      <ErrorLine error={order.error} />
    </main>
  );
}

type LineState = {
  quotation_line: number | null;
  description: string;
  quantity: string;
  unit_price: string;
  unit: string;
  tax_code: string;
  schedule: Delivery[];
};

function OrderForm({ order }: { order: SalesOrderDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const direct = order.source === "direct";
  const taxes = useQuery({ queryKey: taxesKey, queryFn: getTaxes, enabled: direct });
  const salesCodes = (taxes.data?.codes ?? []).filter((c) => c.is_active && c.use !== "purchases");
  const [values, setValues] = useState({
    customer_po: order.customer_po,
    po_date: order.po_date ?? "",
    payment_terms: order.payment_terms,
    incoterm: order.incoterm,
    delivery_address: order.delivery_address,
    notes: order.notes,
    discount_pct: Number(order.discount_pct) ? order.discount_pct : "",
  });
  const [lines, setLines] = useState<LineState[]>(
    order.lines.map((l) => ({
      quotation_line: l.quotation_line,
      description: l.description,
      quantity: l.quantity,
      unit_price: l.unit_price,
      unit: l.unit,
      tax_code: l.tax_code ?? "",
      schedule: l.schedule.map((d) => ({ ...d })),
    })),
  );
  const set = (field: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [field]: value }));
  const setLine = (index: number, change: Partial<LineState>) => setLines((now) => now.map((l, i) => (i === index ? { ...l, ...change } : l)));
  const setDelivery = (index: number, at: number, change: Partial<Delivery>) =>
    setLine(index, { schedule: lines[index].schedule.map((d, j) => (j === at ? { ...d, ...change } : d)) });
  const unused = order.quotation_lines.filter((q) => !lines.some((l) => l.quotation_line === q.id));

  const save = useMutation({
    mutationFn: () =>
      updateSalesOrder(order.id, {
        customer_po: values.customer_po,
        po_date: values.po_date || null,
        payment_terms: values.payment_terms,
        incoterm: values.incoterm,
        delivery_address: values.delivery_address,
        notes: values.notes,
        ...(direct ? { discount_pct: values.discount_pct } : {}),
        lines: lines.map((l) =>
          direct
            ? {
                description: l.description,
                quantity: l.quantity,
                unit_price: l.unit_price,
                unit: l.unit,
                tax_code: l.tax_code || null,
                schedule: l.schedule,
              }
            : { quotation_line: l.quotation_line, quantity: l.quantity, schedule: l.schedule },
        ),
      }),
    onSuccess: (latest) => {
      queryClient.setQueryData([...salesOrdersKey, "one", String(latest.id)], latest);
      void queryClient.invalidateQueries({ queryKey: [...salesOrdersKey, "list"] });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("salesOrders.form")} onSubmit={submit}>
      <label>
        {t("proformas.customerPo")}
        <input value={values.customer_po} maxLength={50} onChange={(e) => set("customer_po")(e.target.value)} />
      </label>
      <label>
        {t("salesOrders.poDate")}
        <input type="date" value={values.po_date} onChange={(e) => set("po_date")(e.target.value)} />
      </label>
      <label>
        {t("quotations.paymentTerms")}
        <input value={values.payment_terms} maxLength={200} onChange={(e) => set("payment_terms")(e.target.value)} />
      </label>
      <label>
        {t("customers.field.incoterm")}
        <select value={values.incoterm} onChange={(e) => set("incoterm")(e.target.value)}>
          <option value="">—</option>
          {INCOTERMS.map((term) => (
            <option key={term} value={term}>
              {t(`customers.incoterms.${term}`)}
            </option>
          ))}
        </select>
      </label>
      {direct && (
        <label>
          {t("quotations.discountPct")}
          <input inputMode="decimal" className="num" value={values.discount_pct} placeholder="0" onChange={(e) => set("discount_pct")(e.target.value)} />
        </label>
      )}
      <label className="wide">
        {t("salesOrders.deliveryAddress")}
        <textarea rows={2} value={values.delivery_address} onChange={(e) => set("delivery_address")(e.target.value)} />
      </label>
      <label className="wide">
        {t("customers.field.notes")}
        <textarea rows={2} value={values.notes} onChange={(e) => set("notes")(e.target.value)} />
      </label>

      <div className="wide">
        <h2>{t("salesOrders.linesAndDeliveries")}</h2>
        <p className="muted">{direct ? t("salesOrders.directPriceHelp") : t("proformas.priceHelp")}</p>
        <p className="muted">{t("salesOrders.scheduleHelp")}</p>
        {lines.map((l, index) => {
          const n = String(index + 1);
          return (
            <fieldset key={index} className="quote-line">
              <legend>
                {t("quotations.lineN", { n })}
                {!direct && `: ${l.description}`}
              </legend>
              <div className="form-grid">
                {direct && (
                  <label className="wide">
                    {t("quotations.description")}
                    <input aria-label={t("salesOrders.descriptionOf", { n })} value={l.description} required onChange={(e) => setLine(index, { description: e.target.value })} />
                  </label>
                )}
                <label>
                  {t("quotations.quantity")}
                  <input inputMode="decimal" className="num" aria-label={t("quotations.quantityOf", { n })} value={l.quantity} required onChange={(e) => setLine(index, { quantity: e.target.value })} />
                </label>
                {direct && (
                  <>
                    <label>
                      {t("quotations.unitPrice")}
                      <input inputMode="decimal" className="num" aria-label={t("salesOrders.priceOf", { n })} value={l.unit_price} required onChange={(e) => setLine(index, { unit_price: e.target.value })} />
                    </label>
                    <label>
                      {t("vouchers.taxCode")}
                      <select aria-label={t("quotations.taxCodeOf", { n })} value={l.tax_code} onChange={(e) => setLine(index, { tax_code: e.target.value })}>
                        <option value="">—</option>
                        {salesCodes.map((c) => (
                          <option key={c.code} value={c.code}>
                            {c.code} {c.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  </>
                )}
              </div>
              <table aria-label={t("salesOrders.deliveriesOf", { n })}>
                <thead>
                  <tr>
                    <th>{t("salesOrders.deliveryDate")}</th>
                    <th className="num">{t("quotations.quantity")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {l.schedule.map((d, at) => (
                    <tr key={at}>
                      <td>
                        <input
                          type="date"
                          aria-label={t("salesOrders.dateOf", { n, k: String(at + 1) })}
                          value={d.due_date}
                          required
                          onChange={(e) => setDelivery(index, at, { due_date: e.target.value })}
                        />
                      </td>
                      <td>
                        <input
                          inputMode="decimal"
                          className="num"
                          aria-label={t("salesOrders.qtyOf", { n, k: String(at + 1) })}
                          value={d.quantity}
                          required
                          onChange={(e) => setDelivery(index, at, { quantity: e.target.value })}
                        />
                      </td>
                      <td>
                        {l.schedule.length > 1 && (
                          <button
                            type="button"
                            className="small secondary"
                            onClick={() => setLine(index, { schedule: l.schedule.filter((_, j) => j !== at) })}
                          >
                            {t("salesOrders.removeDelivery")}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button
                type="button"
                className="small secondary"
                onClick={() => setLine(index, { schedule: [...l.schedule, { due_date: l.schedule.at(-1)?.due_date ?? "", quantity: "" }] })}
              >
                {t("salesOrders.addDelivery")}
              </button>{" "}
              {lines.length > 1 && (
                <button type="button" className="small secondary" onClick={() => setLines((now) => now.filter((_, i) => i !== index))}>
                  {t("quotations.removeLine")}
                </button>
              )}
            </fieldset>
          );
        })}
        {direct && (
          <button
            type="button"
            className="small secondary"
            onClick={() =>
              setLines((now) => [
                ...now,
                { quotation_line: null, description: "", quantity: "", unit_price: "", unit: "pcs", tax_code: "", schedule: [{ due_date: "", quantity: "" }] },
              ])
            }
          >
            {t("quotations.addLine")}
          </button>
        )}
        {unused.length > 0 && (
          <label>
            {t("proformas.addQuotationLine")}
            <select
              value=""
              onChange={(e) => {
                const chosen = order.quotation_lines.find((q) => String(q.id) === e.target.value);
                if (chosen)
                  setLines((now) => [
                    ...now,
                    {
                      quotation_line: chosen.id,
                      description: chosen.description,
                      quantity: chosen.quantity,
                      unit_price: "",
                      unit: "",
                      tax_code: "",
                      schedule: [{ due_date: order.order_date, quantity: chosen.quantity }],
                    },
                  ]);
              }}
            >
              <option value="">—</option>
              {unused.map((q) => (
                <option key={q.id} value={q.id}>
                  {q.line_no}. {q.description}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <Totals order={order} />
      <div className="wide">
        <p className="muted">{t("quotations.worksOut")}</p>
        <button type="submit" disabled={save.isPending}>
          {t("vouchers.saveDraft")}
        </button>
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function Totals({ order }: { order: SalesOrderDetail }) {
  const { t } = useTranslation();
  const c = order.currency;
  return (
    <div className="wide">
      {Number(order.discount_total) !== 0 && (
        <p>
          {t("quotations.discountLine", { pct: order.discount_pct })}: <strong>−{formatDecimal(order.discount_total)}</strong>
        </p>
      )}
      <p>
        {t("quotations.subtotal")}: <strong>{c} {formatDecimal(order.subtotal)}</strong> · {t("vouchers.tax")}:{" "}
        <strong>{formatDecimal(order.tax_total)}</strong> · {t("vouchers.total")}:{" "}
        <strong>
          {c} {formatDecimal(order.total_amount)}
        </strong>
      </p>
    </div>
  );
}

function ReadOnly({ order }: { order: SalesOrderDetail }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("salesOrders.details")}>
      <dl className="details">
        <dt>{t("proformas.customerPo")}</dt>
        <dd>
          {order.customer_po || "—"}
          {order.po_date ? ` (${order.po_date})` : ""}
        </dd>
        <dt>{t("quotations.paymentTerms")}</dt>
        <dd>{order.payment_terms || "—"}</dd>
        <dt>{t("customers.field.incoterm")}</dt>
        <dd>{order.incoterm || "—"}</dd>
        <dt>{t("salesOrders.deliveryAddress")}</dt>
        <dd>{order.delivery_address || "—"}</dd>
        {order.notes && (
          <>
            <dt>{t("customers.field.notes")}</dt>
            <dd>{order.notes}</dd>
          </>
        )}
      </dl>
      <div className="table-wrap">
        <table aria-label={t("salesOrders.linesAndDeliveries")}>
          <thead>
            <tr>
              <th>#</th>
              <th>{t("quotations.description")}</th>
              <th className="num">{t("quotations.quantity")}</th>
              <th className="num">{t("quotations.unitPrice")}</th>
              <th className="num">{t("vouchers.total")}</th>
              <th>{t("salesOrders.deliveries")}</th>
            </tr>
          </thead>
          <tbody>
            {order.lines.map((l) => (
              <tr key={l.line_no}>
                <td>{l.line_no}</td>
                <td>{l.description}</td>
                <td className="num">
                  {formatQuantity(l.quantity)} {l.unit}
                </td>
                <td className="num">{formatDecimal(l.unit_price)}</td>
                <td className="num">{formatDecimal(l.total)}</td>
                <td>{l.schedule.map((d) => `${d.due_date}: ${formatQuantity(d.quantity)}`).join(" · ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Totals order={order} />
    </section>
  );
}

function Actions({ order }: { order: SalesOrderDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [comment, setComment] = useState("");
  const [reason, setReason] = useState("");
  const done = (latest: SalesOrderDetail) => {
    queryClient.setQueryData([...salesOrdersKey, "one", String(latest.id)], latest);
    void queryClient.invalidateQueries({ queryKey: [...salesOrdersKey, "list"] });
    setComment("");
    setReason("");
  };
  const act = useMutation({ mutationFn: (call: () => Promise<SalesOrderDetail>) => call(), onSuccess: done });
  const nothing = !order.can_edit && !order.can_approve && !order.can_complete && !order.can_cancel;
  if (nothing && !order.approval && order.advances.length === 0) return null;

  return (
    <section className="panel" aria-label={t("salesOrders.actions")}>
      {order.can_edit && (
        <p>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => confirmSalesOrder(order.id))}>
            {order.source === "direct" ? t("salesOrders.sendForApproval") : t("salesOrders.confirm")}
          </button>{" "}
          <span className="muted">{order.source === "direct" ? t("salesOrders.sendHelp") : t("salesOrders.confirmHelp")}</span>
        </p>
      )}
      {order.can_approve && (
        <div className="inline-form">
          <label>
            {t("salesOrders.comment")}
            <input value={comment} maxLength={500} onChange={(e) => setComment(e.target.value)} />
          </label>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => approveSalesOrder(order.id, comment))}>
            {t("salesOrders.approve")}
          </button>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => returnSalesOrder(order.id, comment))}>
            {t("salesOrders.sendBack")}
          </button>
        </div>
      )}
      {order.can_complete && (
        <p>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => completeSalesOrder(order.id))}>
            {t("salesOrders.complete")}
          </button>{" "}
          <span className="muted">{t("salesOrders.completeHelp")}</span>
        </p>
      )}
      {order.can_cancel && (
        <div className="inline-form">
          <label>
            {t("proformas.cancelReason")}
            <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => cancelSalesOrder(order.id, reason))}>
            {t("salesOrders.cancel")}
          </button>
        </div>
      )}
      <ErrorLine error={act.error} />
      {order.advances.length > 0 && (
        <p>
          {t("proformas.advancesReceived")}:{" "}
          {order.advances.map((a) => (
            <span key={a.id}>
              <Link to={`/advances/${a.id}`}>{a.number}</Link> ({formatDecimal(a.amount)}){" "}
            </span>
          ))}
        </p>
      )}
      {order.approval && order.approval.history.length > 0 && (
        <ul className="changes" aria-label={t("salesOrders.approvalHistory")}>
          {order.approval.history.map((h, i) => (
            <li key={i}>
              {h.at.slice(0, 16).replace("T", " ")} · {h.action_label} · {h.by}
              {h.reason ? ` · ${h.reason}` : ""}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
