import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { listDivisions } from "../api/admin";
import { ApiError } from "../api/client";
import { itemsKey, listItems } from "../api/items";
import { listPayees } from "../api/payees";
import {
  approvePurchaseOrder,
  cancelPurchaseOrder,
  closePurchaseOrder,
  createPurchaseOrder,
  getPurchaseOrder,
  getPurchaseOrderEmail,
  poKey,
  purchaseOrderPdfUrl,
  returnPurchaseOrder,
  revisePurchaseOrder,
  sendPurchaseOrderEmail,
  submitPurchaseOrder,
  updatePurchaseOrder,
  type PayMode,
  type PODetail,
  type POInput,
} from "../api/purchaseOrders";
import { getTaxes, taxesKey } from "../api/taxes";
import SearchSelect from "../components/SearchSelect";
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

/** One purchase order (spec 5A.1): raising it, the Director's approval, revising, cancelling
 * or closing it short. */
export default function PurchaseOrderPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const isNew = id === "new";
  const order = useQuery({
    queryKey: [...poKey, "one", id],
    queryFn: () => getPurchaseOrder(Number(id)),
    enabled: !isNew,
  });
  const data = order.data;

  return (
    <main className="page">
      <p>
        <Link to="/purchase-orders">{t("po.backToList")}</Link>
      </p>
      <h1>{isNew ? t("po.new") : `${t("po.order")} ${data?.label ?? ""}`}</h1>
      {isNew && <OrderForm />}
      {data && (
        <>
          <p className="muted">
            {t(`po.statuses.${data.status}`)} · {data.po_date} · {data.division} · {data.supplier.code} {data.supplier.name}
            {data.parent && (
              <>
                {" · "}
                {t("po.revisionOf")} <Link to={`/purchase-orders/${data.parent.id}`}>{data.parent.label}</Link>
              </>
            )}
          </p>
          {data.revisions.map((r) => (
            <p key={r.id} className="notice">
              {t("po.replacedBy")} <Link to={`/purchase-orders/${r.id}`}>{r.label}</Link> ({t(`po.statuses.${r.status}`)})
            </p>
          ))}
          {data.end_reason && ["closed", "cancelled", "revised"].includes(data.status) && (
            <p className="notice">{t("po.because", { reason: data.end_reason })}</p>
          )}
          <p>
            <a className="button-link secondary" href={purchaseOrderPdfUrl(data.id)} target="_blank" rel="noreferrer">
              {t("po.print")}
            </a>{" "}
            {!["approved", "partly_received", "received", "closed"].includes(data.status) && <span className="muted">{t("po.printsAsDraft")}</span>}
          </p>
          {data.can_edit ? <OrderForm key={`${data.id}-${data.total_amount}`} order={data} /> : <ReadOnly order={data} />}
          <Actions order={data} />
          {(data.can_email || data.emails.length > 0) && <EmailPanel order={data} />}
        </>
      )}
      <ErrorLine error={order.error} />
    </main>
  );
}

type LineState = { item: string; quantity: string; unit_price: string; tax_code: string; description: string };
const blankLine: LineState = { item: "", quantity: "", unit_price: "", tax_code: "", description: "" };

function OrderForm({ order }: { order?: PODetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const suppliers = useQuery({ queryKey: ["payees", "", false], queryFn: () => listPayees("", false), enabled: !order });
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions, enabled: !order });
  const items = useQuery({ queryKey: [...itemsKey, "list", "", "", false], queryFn: () => listItems("", "", false) });
  const taxes = useQuery({ queryKey: taxesKey, queryFn: getTaxes });
  const purchaseCodes = (taxes.data?.codes ?? []).filter((c) => c.is_active && c.use !== "sales");
  const [supplier, setSupplier] = useState("");
  const [division, setDivision] = useState("");
  const [values, setValues] = useState({
    delivery_date: order?.delivery_date ?? "",
    pay_mode: (order?.pay_mode ?? "online") as PayMode,
    payment_terms: order?.payment_terms ?? "",
    deliver_to: order?.deliver_to ?? "",
    notes: order?.notes ?? "",
  });
  const [lines, setLines] = useState<LineState[]>(
    order
      ? order.lines.map((l) => ({
          item: String(l.item.id),
          quantity: l.quantity,
          unit_price: l.unit_price,
          tax_code: l.tax_code ?? "",
          description: l.description,
        }))
      : [{ ...blankLine }],
  );
  const set = (field: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [field]: value }));
  const setLine = (index: number, change: Partial<LineState>) => setLines((now) => now.map((l, i) => (i === index ? { ...l, ...change } : l)));
  const itemOptions = (items.data ?? []).map((i) => ({ value: String(i.id), label: `${i.code} ${i.name} (${i.unit})` }));

  const save = useMutation({
    mutationFn: () => {
      const input: POInput = {
        ...values,
        delivery_date: values.delivery_date || null,
        lines: lines.map((l) => ({
          item: Number(l.item),
          quantity: l.quantity,
          unit_price: l.unit_price,
          tax_code: l.tax_code || null,
          description: l.description,
        })),
      };
      return order ? updatePurchaseOrder(order.id, input) : createPurchaseOrder({ ...input, supplier: Number(supplier), division });
    },
    onSuccess: (saved) => {
      queryClient.setQueryData([...poKey, "one", String(saved.id)], saved);
      void queryClient.invalidateQueries({ queryKey: [...poKey, "list"] });
      if (!order) navigate(`/purchase-orders/${saved.id}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("po.form")} onSubmit={submit}>
      {!order && (
        <>
          <div className="wide">
            <SearchSelect
              label={t("po.supplier")}
              options={(suppliers.data ?? []).map((s) => ({ value: String(s.id), label: `${s.code} ${s.name}` }))}
              value={supplier}
              onChange={setSupplier}
            />
          </div>
          <label>
            {t("vouchers.division")}
            <select value={division} required onChange={(e) => setDivision(e.target.value)}>
              <option value="">—</option>
              {(divisions.data ?? [])
                .filter((d) => d.division_type !== "shared")
                .map((d) => (
                  <option key={d.code} value={d.code}>
                    {d.code} {d.name}
                  </option>
                ))}
            </select>
          </label>
        </>
      )}
      <label>
        {t("po.deliveryDate")}
        <input type="date" value={values.delivery_date} onChange={(e) => set("delivery_date")(e.target.value)} />
      </label>
      <label>
        {t("po.payMode")}
        <select value={values.pay_mode} onChange={(e) => set("pay_mode")(e.target.value)}>
          {(["online", "cheque", "cash"] as const).map((m) => (
            <option key={m} value={m}>
              {t(`po.payModes.${m}`)}
            </option>
          ))}
        </select>
      </label>
      {order && (
        <label>
          {t("po.paymentTerms")}
          <input value={values.payment_terms} maxLength={100} onChange={(e) => set("payment_terms")(e.target.value)} />
        </label>
      )}
      {order && (
        <label className="wide">
          {t("po.deliverTo")}
          <textarea rows={2} value={values.deliver_to} onChange={(e) => set("deliver_to")(e.target.value)} />
        </label>
      )}
      <label className="wide">
        {t("customers.field.notes")}
        <textarea rows={2} value={values.notes} onChange={(e) => set("notes")(e.target.value)} />
      </label>

      <div className="wide">
        <h2>{t("po.lines")}</h2>
        {lines.map((l, index) => {
          const n = String(index + 1);
          return (
            <fieldset key={index} className="quote-line">
              <legend>{t("quotations.lineN", { n })}</legend>
              <div className="form-grid">
                <div className="wide">
                  <SearchSelect label={t("po.itemOf", { n })} options={itemOptions} value={l.item} onChange={(value) => setLine(index, { item: value })} />
                </div>
                <label>
                  {t("quotations.quantity")}
                  <input inputMode="decimal" className="num" aria-label={t("quotations.quantityOf", { n })} value={l.quantity} required onChange={(e) => setLine(index, { quantity: e.target.value })} />
                </label>
                <label>
                  {t("po.rate")}
                  <input inputMode="decimal" className="num" aria-label={t("po.rateOf", { n })} value={l.unit_price} required onChange={(e) => setLine(index, { unit_price: e.target.value })} />
                </label>
                <label>
                  {t("vouchers.taxCode")}
                  <select aria-label={t("quotations.taxCodeOf", { n })} value={l.tax_code} onChange={(e) => setLine(index, { tax_code: e.target.value })}>
                    <option value="">—</option>
                    {purchaseCodes.map((c) => (
                      <option key={c.code} value={c.code}>
                        {c.code} {c.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {lines.length > 1 && (
                <button type="button" className="small secondary" onClick={() => setLines((now) => now.filter((_, i) => i !== index))}>
                  {t("quotations.removeLine")}
                </button>
              )}
            </fieldset>
          );
        })}
        <button type="button" className="small secondary" onClick={() => setLines((now) => [...now, { ...blankLine }])}>
          {t("quotations.addLine")}
        </button>
      </div>
      {order && <Totals order={order} />}
      <div className="wide">
        <p className="muted">{t("quotations.worksOut")}</p>
        <button type="submit" disabled={save.isPending || (!order && (!supplier || !division))}>
          {order ? t("vouchers.saveDraft") : t("po.makeDraft")}
        </button>
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function Totals({ order }: { order: PODetail }) {
  const { t } = useTranslation();
  const c = order.currency;
  return (
    <div className="wide">
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

function ReadOnly({ order }: { order: PODetail }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("po.details")}>
      <dl className="details">
        <dt>{t("po.deliveryDate")}</dt>
        <dd>{order.delivery_date ?? "—"}</dd>
        <dt>{t("po.payMode")}</dt>
        <dd>
          {t(`po.payModes.${order.pay_mode}`)} · {order.payment_terms || "—"}
        </dd>
        <dt>{t("po.deliverTo")}</dt>
        <dd className="pre-line">{order.deliver_to || "—"}</dd>
        {order.notes && (
          <>
            <dt>{t("customers.field.notes")}</dt>
            <dd>{order.notes}</dd>
          </>
        )}
      </dl>
      <div className="table-wrap">
        <table aria-label={t("po.lines")}>
          <thead>
            <tr>
              <th>{t("po.item")}</th>
              <th>{t("quotations.description")}</th>
              <th className="num">{t("quotations.quantity")}</th>
              <th className="num">{t("po.rate")}</th>
              <th className="num">{t("vouchers.total")}</th>
              <th className="num">{t("po.received")}</th>
            </tr>
          </thead>
          <tbody>
            {order.lines.map((l) => (
              <tr key={l.line_no}>
                <td className="mono">{l.item.code}</td>
                <td>{l.description}</td>
                <td className="num">
                  {formatQuantity(l.quantity)} {l.unit}
                </td>
                <td className="num">{formatDecimal(l.unit_price)}</td>
                <td className="num">{formatDecimal(l.total)}</td>
                <td className="num">{formatQuantity(l.received_quantity)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Totals order={order} />
    </section>
  );
}

function Actions({ order }: { order: PODetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const done = (latest: PODetail) => {
    queryClient.setQueryData([...poKey, "one", String(latest.id)], latest);
    void queryClient.invalidateQueries({ queryKey: [...poKey, "list"] });
    setText("");
    if (latest.id !== order.id) navigate(`/purchase-orders/${latest.id}`);
  };
  const act = useMutation({ mutationFn: (call: () => Promise<PODetail>) => call(), onSuccess: done });
  const any = order.can_edit || order.can_approve || order.can_revise || order.can_cancel || order.can_close;
  if (!any && !order.approval) return null;

  return (
    <section className="panel" aria-label={t("po.actions")}>
      {order.can_edit && (
        <p>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => submitPurchaseOrder(order.id))}>
            {t("po.send")}
          </button>{" "}
          <span className="muted">{t("po.sendHelp")}</span>
        </p>
      )}
      {(order.can_approve || order.can_revise || order.can_cancel || order.can_close) && (
        <div className="inline-form">
          <label>
            {t("salesOrders.comment")}
            <input value={text} maxLength={500} onChange={(e) => setText(e.target.value)} />
          </label>
          {order.can_approve && (
            <>
              <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => approvePurchaseOrder(order.id, text))}>
                {t("po.approve")}
              </button>
              <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => returnPurchaseOrder(order.id, text))}>
                {t("salesOrders.sendBack")}
              </button>
            </>
          )}
          {order.can_revise && (
            <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => revisePurchaseOrder(order.id, text))}>
              {t("po.revise")}
            </button>
          )}
          {order.can_close && (
            <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => closePurchaseOrder(order.id, text))}>
              {t("po.close")}
            </button>
          )}
          {order.can_cancel && (
            <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => cancelPurchaseOrder(order.id, text))}>
              {t("po.cancel")}
            </button>
          )}
        </div>
      )}
      <ErrorLine error={act.error} />
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

function EmailPanel({ order }: { order: PODetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<{ to: string; subject: string; body: string } | null>(null);
  const load = useMutation({
    mutationFn: () => getPurchaseOrderEmail(order.id),
    onSuccess: (draft) => setMessage({ to: draft.to.join(", "), subject: draft.subject, body: draft.body }),
  });
  const send = useMutation({
    mutationFn: () =>
      sendPurchaseOrderEmail(order.id, {
        to: message!.to
          .split(/[,;]/)
          .map((a) => a.trim())
          .filter(Boolean),
        cc: [],
        subject: message!.subject,
        body: message!.body,
      }),
    onSuccess: (latest) => {
      queryClient.setQueryData([...poKey, "one", String(latest.id)], latest);
      setMessage(null);
    },
  });
  return (
    <section className="panel" aria-label={t("po.emailTitle")}>
      <h2>{t("po.emailTitle")}</h2>
      {order.can_email && !message && (
        <button type="button" disabled={load.isPending} onClick={() => load.mutate()}>
          {t("po.emailToSupplier")}
        </button>
      )}
      {message && (
        <form
          className="form-grid"
          aria-label={t("po.emailTitle")}
          onSubmit={(e) => {
            e.preventDefault();
            send.mutate();
          }}
        >
          <label className="wide">
            {t("quotations.emailTo")}
            <input value={message.to} required onChange={(e) => setMessage({ ...message, to: e.target.value })} />
          </label>
          <label className="wide">
            {t("quotations.emailSubject")}
            <input value={message.subject} required onChange={(e) => setMessage({ ...message, subject: e.target.value })} />
          </label>
          <label className="wide">
            {t("quotations.emailBody")}
            <textarea rows={6} value={message.body} required onChange={(e) => setMessage({ ...message, body: e.target.value })} />
          </label>
          <div className="wide">
            <button type="submit" disabled={send.isPending}>
              {t("quotations.sendEmail")}
            </button>{" "}
            <button type="button" className="secondary" onClick={() => setMessage(null)}>
              {t("quotations.cancel")}
            </button>
          </div>
        </form>
      )}
      <ErrorLine error={load.error ?? send.error} />
      {order.emails.length > 0 && (
        <ul className="changes" aria-label={t("quotations.emailsSent")}>
          {order.emails.map((m, i) => (
            <li key={i}>
              {m.status === "sent" ? "✓" : "✗"} {m.sent_at.slice(0, 16).replace("T", " ")} · {m.to} · {m.by}
              {m.error ? ` · ${m.error}` : ""}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
