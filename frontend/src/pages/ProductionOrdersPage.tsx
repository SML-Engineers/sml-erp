import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import {
  addOrder,
  changeOrder,
  getOrder,
  getOrders,
  getSalesLines,
  orderAction,
  ordersKey,
  orderWhereUsed,
  type OrderAction,
  type OrderValues,
  type OrderWhereUsed,
  type ProductionOrder,
} from "../api/productionOrders";
import OrderCostsPanel from "../components/OrderCostsPanel";
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

/** P3-06: moulding production orders, their material requirements and where-used. */
export default function ProductionOrdersPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("open");
  const [adding, setAdding] = useState(false);
  const open = Number(params.get("order")) || null;
  const show = (id: number | null) => setParams(id ? { order: String(id) } : {});
  const found = useQuery({ queryKey: [...ordersKey, q, status], queryFn: () => getOrders(q, status) });
  const d = found.data;
  return (
    <main className="page">
      <h1>{t("prodOrder.title")}</h1>
      <p className="muted">{t("prodOrder.help")}</p>
      <div className="inline-form">
        <label>
          {t("prodOrder.search")}
          <input value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label>
          {t("prodOrder.status")}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="open">{t("prodOrder.open")}</option>
            <option value="">{t("prodOrder.all")}</option>
            {d?.statuses.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        {d?.can_plan && (
          <button type="button" onClick={() => setAdding(true)}>
            {t("prodOrder.add")}
          </button>
        )}
      </div>
      <ErrorLine error={found.error} />
      {adding && (
        <NewOrder
          onClose={() => setAdding(false)}
          onSaved={(o) => {
            setAdding(false);
            show(o.id);
          }}
        />
      )}
      {open && <Detail key={open} id={open} onClose={() => show(null)} />}
      {d && (
        <div className="table-wrap">
          <table aria-label={t("prodOrder.title")}>
            <thead>
              <tr>
                <th>{t("prodOrder.number")}</th>
                <th>{t("prodOrder.part")}</th>
                <th className="num">{t("prodOrder.quantity")}</th>
                <th>{t("prodOrder.for")}</th>
                <th>{t("prodOrder.firstDue")}</th>
                <th>{t("prodOrder.status")}</th>
              </tr>
            </thead>
            <tbody>
              {d.results.map((o) => (
                <tr key={o.id}>
                  <td>
                    <button type="button" className="link" onClick={() => show(o.id)}>
                      {o.number}
                    </button>
                  </td>
                  <td>
                    {o.item} <span className="muted small">{o.item_name}</span>
                  </td>
                  <td className="num">
                    {formatDecimal(o.quantity)} {o.unit}
                  </td>
                  <td>{o.purpose === "sales" ? `${o.sales_order} ${o.customer}` : t("prodOrder.stock")}</td>
                  <td>{o.first_due}</td>
                  <td>{o.status_label}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {d.results.length === 0 && <p className="muted">{t("prodOrder.none")}</p>}
        </div>
      )}
      <WhereUsed />
    </main>
  );
}

function NewOrder({ onClose, onSaved }: { onClose: () => void; onSaved: (o: ProductionOrder) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [values, setValues] = useState<OrderValues>({ item: "", quantity: "", purpose: "stock", due_date: "", notes: "" });
  const [find, setFind] = useState("");
  const lines = useQuery({
    queryKey: [...ordersKey, "sales-lines", find],
    queryFn: () => getSalesLines(find),
    enabled: values.purpose === "sales",
  });
  const save = useMutation({
    mutationFn: () => {
      const body: OrderValues = { item: values.item, quantity: values.quantity, purpose: values.purpose, notes: values.notes };
      if (values.purpose === "sales") body.sales_line = values.sales_line;
      else body.due_date = values.due_date;
      return addOrder(body);
    },
    onSuccess: (o) => {
      queryClient.invalidateQueries({ queryKey: ordersKey });
      onSaved(o);
    },
  });
  const set = (key: keyof OrderValues) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const chosen = lines.data?.results.find((l) => l.id === values.sales_line);
  return (
    <section className="panel" aria-label={t("prodOrder.add")}>
      <h2>{t("prodOrder.add")}</h2>
      <form className="form-grid" aria-label={t("prodOrder.add")} onSubmit={submit}>
        <label>
          {t("prodOrder.part")}
          <input value={values.item} onChange={set("item")} />
        </label>
        <label>
          {t("prodOrder.quantity")}
          <input inputMode="decimal" value={values.quantity} onChange={set("quantity")} />
        </label>
        <label>
          {t("prodOrder.for")}
          <select value={values.purpose} onChange={set("purpose")}>
            <option value="stock">{t("prodOrder.stock")}</option>
            <option value="sales">{t("prodOrder.salesOrder")}</option>
          </select>
        </label>
        {values.purpose === "stock" ? (
          <label>
            {t("prodOrder.dueDate")}
            <input type="date" value={values.due_date} onChange={set("due_date")} />
          </label>
        ) : (
          <>
            <label>
              {t("prodOrder.findLine")}
              <input value={find} onChange={(e) => setFind(e.target.value)} />
            </label>
            <label className="wide">
              {t("prodOrder.salesLine")}
              <select
                value={values.sales_line ?? ""}
                onChange={(e) => setValues({ ...values, sales_line: Number(e.target.value) || undefined })}
              >
                <option value="">{t("prodOrder.choose")}</option>
                {lines.data?.results.map((l) => (
                  <option key={l.id} value={l.id}>
                    {t("prodOrder.lineOption", {
                      order: l.order,
                      line: l.line_no,
                      customer: l.customer,
                      description: l.description,
                      left: formatDecimal(l.left),
                      unit: l.unit,
                    })}
                  </option>
                ))}
              </select>
            </label>
            {chosen && (
              <p className="muted wide">
                {t("prodOrder.schedule")}:{" "}
                {chosen.schedule.map((s) => `${formatDecimal(s.quantity)} ${t("prodOrder.by")} ${s.due_date}`).join("; ")}
              </p>
            )}
          </>
        )}
        <label className="wide">
          {t("prodOrder.notes")}
          <input value={values.notes} onChange={set("notes")} />
        </label>
        <div className="wide row-actions">
          <button type="submit" disabled={save.isPending}>
            {t("prodOrder.save")}
          </button>
          <button type="button" className="secondary" onClick={onClose}>
            {t("prodOrder.close")}
          </button>
        </div>
        <div className="wide">
          <ErrorLine error={save.error} />
        </div>
      </form>
    </section>
  );
}

function Detail({ id, onClose }: { id: number; onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = ["production-order", id];
  const found = useQuery({ queryKey: key, queryFn: () => getOrder(id) });
  const [reason, setReason] = useState("");
  const [request, setRequest] = useState("");
  const act = useMutation({
    mutationFn: ({ action, body }: { action: OrderAction; body?: Record<string, string> }) => orderAction(id, action, body),
    onSuccess: (o) => {
      if (o.purchase_request) setRequest(o.purchase_request.number);
      queryClient.setQueryData(key, o);
      queryClient.invalidateQueries({ queryKey: ordersKey });
    },
  });
  const o = found.data;
  if (!o) return <ErrorLine error={found.error} />;
  return (
    <section className="panel" aria-label={t("prodOrder.panel", { number: o.number })}>
      <h2>
        {o.number} — {o.status_label}
      </h2>
      <p>
        <strong>
          {o.item} {o.item_name}
        </strong>{" "}
        × {formatDecimal(o.quantity)} {o.unit}
        {o.mould && <> · {t("prodOrder.mould", { mould: o.mould })}</>}
        {o.bom && <> · {t("prodOrder.bomRev", { item: o.bom.item, revision: o.bom.revision })}</>}
        {o.family_shots && <> · {t("prodOrder.shots", { shots: formatDecimal(o.family_shots) })}</>}
        {o.status !== "draft" && <> · {t("prodOrder.made", { made: formatDecimal(o.made) })}</>}
      </p>
      <p className="muted">
        {o.sales_line
          ? t("prodOrder.forLine", {
              order: o.sales_line.order,
              line: o.sales_line.line_no,
              customer: o.sales_line.customer,
            })
          : t("prodOrder.forStock")}
        {" · "}
        {t("prodOrder.due")}: {o.dues.map((d) => `${formatDecimal(d.quantity)} ${t("prodOrder.by")} ${d.due_date}`).join("; ")}
      </p>
      {o.end_reason && <p className="notice">{t("prodOrder.cancelled", { reason: o.end_reason })}</p>}
      {o.status === "draft" && !o.bom && <p className="notice">{t("prodOrder.noBom")}</p>}
      <h3>{o.status === "draft" ? t("prodOrder.needsPreview") : t("prodOrder.needs")}</h3>
      <div className="table-wrap">
        <table aria-label={t("prodOrder.needs")}>
          <thead>
            <tr>
              <th>{t("prodOrder.material")}</th>
              <th className="num">{t("prodOrder.required")}</th>
              <th className="num">{t("prodOrder.onHand")}</th>
              <th className="num">{t("prodOrder.coming")}</th>
              <th className="num">{t("prodOrder.otherOrders")}</th>
              <th className="num">{t("prodOrder.shortage")}</th>
            </tr>
          </thead>
          <tbody>
            {o.requirements.map((r) => (
              <tr key={r.seq}>
                <td>
                  {r.code} <span className="muted small">{r.name}</span>
                  {r.customer_supplied && <span className="muted small"> {t("prodOrder.customerSupplied")}</span>}
                </td>
                <td className="num">
                  {formatDecimal(r.required)} {r.unit}
                </td>
                <td className="num">{formatDecimal(r.on_hand)}</td>
                <td className="num">{formatDecimal(r.coming)}</td>
                <td className="num">{formatDecimal(r.other_orders)}</td>
                <td className={`num${Number(r.shortage) > 0 ? " form-error" : ""}`}>
                  {Number(r.shortage) > 0 ? formatDecimal(r.shortage) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {o.short && <p className="notice">{o.can_request ? t("prodOrder.shortCanRequest") : t("prodOrder.shortTold")}</p>}
      {request && <p className="notice">{t("prodOrder.requested", { number: request })}</p>}
      {o.can_edit && <EditDraft order={o} onSaved={(d) => queryClient.setQueryData(key, d)} />}
      {o.costs && <OrderCostsPanel costs={o.costs} busy={act.isPending} onRefresh={() => act.mutate({ action: "refresh-costs" })} />}
      <div className="row-actions">
        {o.can_release && (
          <button type="button" disabled={act.isPending} onClick={() => act.mutate({ action: "release" })}>
            {t("prodOrder.release")}
          </button>
        )}
        {o.can_complete && (
          <button type="button" disabled={act.isPending} onClick={() => act.mutate({ action: "complete" })}>
            {t("prodOrder.complete")}
          </button>
        )}
        {o.can_close && (
          <button type="button" disabled={act.isPending} onClick={() => act.mutate({ action: "close" })}>
            {t("prodOrder.closeOrder")}
          </button>
        )}
        {o.can_request && o.short && (
          <button type="button" disabled={act.isPending} onClick={() => act.mutate({ action: "purchase-request" })}>
            {t("prodOrder.raiseRequest")}
          </button>
        )}
        <button type="button" className="secondary" onClick={onClose}>
          {t("prodOrder.close")}
        </button>
      </div>
      {o.can_cancel && (
        <div className="inline-form">
          <label>
            {t("prodOrder.cancelReason")}
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button
            type="button"
            className="secondary"
            disabled={act.isPending}
            onClick={() => act.mutate({ action: "cancel", body: { reason } })}
          >
            {t("prodOrder.cancel")}
          </button>
        </div>
      )}
      <ErrorLine error={act.error} />
    </section>
  );
}

function EditDraft({ order, onSaved }: { order: ProductionOrder; onSaved: (o: ProductionOrder) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [quantity, setQuantity] = useState(order.quantity);
  const [due, setDue] = useState(order.dues[0]?.due_date ?? "");
  const save = useMutation({
    mutationFn: () => changeOrder(order.id, order.purpose === "stock" ? { quantity, due_date: due } : { quantity }),
    onSuccess: (o) => {
      queryClient.invalidateQueries({ queryKey: ordersKey });
      onSaved(o);
    },
  });
  return (
    <form
      className="inline-form"
      aria-label={t("prodOrder.change")}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <label>
        {t("prodOrder.quantity")}
        <input inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
      </label>
      {order.purpose === "stock" && (
        <label>
          {t("prodOrder.dueDate")}
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </label>
      )}
      <button type="submit" className="secondary" disabled={save.isPending}>
        {t("prodOrder.change")}
      </button>
      <ErrorLine error={save.error} />
    </form>
  );
}

function WhereUsed() {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [result, setResult] = useState<OrderWhereUsed | null>(null);
  const look = useMutation({ mutationFn: () => orderWhereUsed(code), onSuccess: setResult });
  return (
    <section className="panel" aria-label={t("prodOrder.whereUsed")}>
      <h2>{t("prodOrder.whereUsed")}</h2>
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          look.mutate();
        }}
      >
        <label>
          {t("prodOrder.itemCode")}
          <input value={code} onChange={(e) => setCode(e.target.value)} />
        </label>
        <button type="submit" disabled={look.isPending || !code}>
          {t("prodOrder.look")}
        </button>
      </form>
      <ErrorLine error={look.error} />
      {result && (
        <>
          <p>
            <strong>
              {result.item} {result.name}
            </strong>
          </p>
          <p>
            {result.making.length
              ? t("prodOrder.making", {
                  count: result.making.length,
                  total: formatDecimal(result.making_total),
                  orders: result.making.map((o) => o.number).join(", "),
                })
              : t("prodOrder.makingNone")}
          </p>
          <p>
            {result.needing.length
              ? t("prodOrder.needing", {
                  orders: result.needing.map((x) => `${x.number} (${formatDecimal(x.required)} ${x.unit})`).join(", "),
                })
              : t("prodOrder.needingNone")}
          </p>
        </>
      )}
    </section>
  );
}
