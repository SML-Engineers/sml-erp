import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import {
  cancelDeliveryNote,
  createDeliveryNote,
  deleteDeliveryNote,
  deliveryPdfUrl,
  dnKey,
  getDeliveryNote,
  issueDeliveryNote,
  orderForDelivery,
  recordReceipt,
  signedCopyUrl,
  updateDeliveryNote,
  type DNDetail,
  type DNOrderLine,
} from "../api/deliveryNotes";
import { compareDecimal, formatDecimal, formatQuantity } from "../lib/decimal";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

const today = () => new Date().toLocaleDateString("en-CA");

/** One delivery note (P2-04): made from an open order, issued when the goods leave, printed
 * for the customer to sign, and the signed copy kept when it comes back. */
export default function DeliveryNotePage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const [search] = useSearchParams();
  const isNew = id === "new";
  const orderId = Number(search.get("order"));
  const note = useQuery({ queryKey: [...dnKey, "one", id], queryFn: () => getDeliveryNote(Number(id)), enabled: !isNew });
  const order = useQuery({ queryKey: [...dnKey, "order", orderId], queryFn: () => orderForDelivery(orderId), enabled: isNew && orderId > 0 });
  const data = note.data;

  return (
    <main className="page">
      <p>
        <Link to="/delivery-notes">{t("dn.backToList")}</Link>
      </p>
      <h1>{isNew ? t("dn.new") : `${t("dn.one")} ${data?.number ?? ""}`}</h1>
      {isNew && order.data && (
        <>
          <p className="muted">
            {order.data.number} · {order.data.customer}
            {order.data.customer_po && ` · ${t("dn.customerPo")} ${order.data.customer_po}`}
          </p>
          <NoteForm orderId={order.data.id} lines={order.data.lines} address={order.data.delivery_address} />
        </>
      )}
      {data && (
        <>
          <p className="muted">
            {t(`dn.statuses.${data.status}`)} · {data.delivery_date} · {data.customer.name} ·{" "}
            <Link to={`/sales-orders/${data.order.id}`}>{data.order.number}</Link>
            {data.order.customer_po && ` · ${t("dn.customerPo")} ${data.order.customer_po}`}
            {(data.invoices ?? []).map((i) => (
              <span key={i.id}>
                {" · "}
                <Link to={`/tax-invoices/${i.id}`}>{i.number || t("ti.draftNo", { id: i.id })}</Link>
              </span>
            ))}
          </p>
          {data.status === "cancelled" && <p className="notice">{t("proformas.cancelledBecause", { reason: data.cancel_reason })}</p>}
          {data.can_edit ? (
            <NoteForm key={`${data.id}-${data.vehicle_no}-${data.lines.map((l) => l.quantity).join()}`} note={data} lines={data.lines} address={data.delivery_address} />
          ) : (
            <ReadOnly note={data} />
          )}
          <Actions note={data} />
        </>
      )}
      <ErrorLine error={note.error ?? order.error} />
    </main>
  );
}

function NoteForm({ note, orderId, lines, address }: { note?: DNDetail; orderId?: number; lines: DNOrderLine[]; address: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [values, setValues] = useState({
    delivery_date: note?.delivery_date ?? today(),
    vehicle_no: note?.vehicle_no ?? "",
    driver: note?.driver ?? "",
    delivery_address: note?.delivery_address ?? address,
    notes: note?.notes ?? "",
  });
  const [quantities, setQuantities] = useState<Record<number, string>>(
    Object.fromEntries(lines.map((l) => [l.id, l.quantity ? formatQuantity(l.quantity).replace(/,/g, "") : ""])),
  );
  const [items, setItems] = useState<Record<number, string>>(Object.fromEntries(lines.map((l) => [l.id, l.item ?? ""])));
  const save = useMutation({
    mutationFn: () => {
      const input = {
        ...values,
        order: orderId,
        lines: lines.map((l) => ({ order_line: l.id, quantity: quantities[l.id] ?? "", item: items[l.id] ?? "" })),
      };
      return note ? updateDeliveryNote(note.id, input) : createDeliveryNote(input);
    },
    onSuccess: (saved) => {
      queryClient.setQueryData([...dnKey, "one", String(saved.id)], saved);
      void queryClient.invalidateQueries({ queryKey: dnKey });
      if (!note) navigate(`/delivery-notes/${saved.id}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("dn.form")} onSubmit={submit}>
      <label>
        {t("dn.date")}
        <input type="date" value={values.delivery_date} required onChange={(e) => setValues({ ...values, delivery_date: e.target.value })} />
      </label>
      <label>
        {t("dn.vehicle")}
        <input value={values.vehicle_no} maxLength={30} onChange={(e) => setValues({ ...values, vehicle_no: e.target.value })} />
      </label>
      <label>
        {t("dn.driver")}
        <input value={values.driver} maxLength={100} onChange={(e) => setValues({ ...values, driver: e.target.value })} />
      </label>
      <label className="wide">
        {t("dn.address")}
        <textarea rows={2} value={values.delivery_address} onChange={(e) => setValues({ ...values, delivery_address: e.target.value })} />
      </label>
      <div className="wide table-wrap">
        <table aria-label={t("dn.lines")}>
          <thead>
            <tr>
              <th>#</th>
              <th>{t("quotations.description")}</th>
              <th className="num">{t("dn.ordered")}</th>
              <th className="num">{t("dn.deliveredBefore")}</th>
              <th className="num">{t("dn.toDeliver")}</th>
              <th className="num">{t("dn.now")}</th>
              <th>{t("dn.part")}</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.id}>
                <td>{l.line_no}</td>
                <td>
                  {l.description}
                  {l.drawing_no && <div className="muted">{l.drawing_no}</div>}
                  {l.schedule.length > 0 && (
                    <div className="muted">{l.schedule.map((d) => `${d.due_date}: ${formatQuantity(d.quantity)}`).join(" · ")}</div>
                  )}
                </td>
                <td className="num">
                  {formatQuantity(l.ordered)} {l.unit}
                </td>
                <td className="num">{formatQuantity(l.delivered_before)}</td>
                <td className="num">{formatQuantity(l.to_deliver)}</td>
                <td className="num">
                  <input
                    inputMode="decimal"
                    className="num"
                    size={10}
                    aria-label={t("dn.nowOf", { n: l.line_no })}
                    value={quantities[l.id] ?? ""}
                    onChange={(e) => setQuantities((now) => ({ ...now, [l.id]: e.target.value }))}
                  />
                </td>
                <td>
                  <input
                    size={12}
                    maxLength={30}
                    aria-label={t("dn.partOf", { n: l.line_no })}
                    value={items[l.id] ?? ""}
                    onChange={(e) => setItems((now) => ({ ...now, [l.id]: e.target.value }))}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <label className="wide">
        {t("dn.notes")}
        <input value={values.notes} maxLength={2000} onChange={(e) => setValues({ ...values, notes: e.target.value })} />
      </label>
      <div className="wide">
        <p className="muted">{t("dn.formHelp")}</p>
        <button type="submit" disabled={save.isPending}>
          {note ? t("vouchers.saveDraft") : t("dn.makeDraft")}
        </button>
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function ReadOnly({ note }: { note: DNDetail }) {
  const { t } = useTranslation();
  const on = note.lines.filter((l) => l.quantity);
  return (
    <section className="panel" aria-label={t("dn.details")}>
      <dl className="details">
        <dt>{t("dn.vehicle")}</dt>
        <dd>{note.vehicle_no || "–"}</dd>
        <dt>{t("dn.driver")}</dt>
        <dd>{note.driver || "–"}</dd>
        <dt>{t("dn.address")}</dt>
        <dd>{note.delivery_address || "–"}</dd>
        {note.issued_by && (
          <>
            <dt>{t("dn.issuedBy")}</dt>
            <dd>{note.issued_by}</dd>
          </>
        )}
        {note.received_by && (
          <>
            <dt>{t("dn.receivedBy")}</dt>
            <dd>
              {note.received_by} · {note.received_on}
              {note.signed_copy && (
                <>
                  {" · "}
                  <a href={signedCopyUrl(note.id)} target="_blank" rel="noreferrer">
                    {t("dn.signedCopy")}
                  </a>
                </>
              )}
            </dd>
          </>
        )}
      </dl>
      <div className="table-wrap">
        <table aria-label={t("dn.lines")}>
          <thead>
            <tr>
              <th>#</th>
              <th>{t("quotations.description")}</th>
              <th className="num">{t("dn.ordered")}</th>
              <th className="num">{t("dn.now")}</th>
              <th>{t("dn.part")}</th>
              <th className="num">{t("dn.stockValue")}</th>
            </tr>
          </thead>
          <tbody>
            {on.map((l) => (
              <tr key={l.id}>
                <td>{l.line_no}</td>
                <td>{l.description}</td>
                <td className="num">
                  {formatQuantity(l.ordered)} {l.unit}
                </td>
                <td className="num">{formatQuantity(l.quantity ?? "0")}</td>
                <td>{l.item || "–"}</td>
                <td className="num">{l.cost && compareDecimal(l.cost, "0") !== 0 ? formatDecimal(l.cost) : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {note.notes && <p>{note.notes}</p>}
    </section>
  );
}

function Actions({ note }: { note: DNDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [receivedBy, setReceivedBy] = useState("");
  const [receivedOn, setReceivedOn] = useState(today());
  const [file, setFile] = useState<File | null>(null);
  const done = (latest: DNDetail) => {
    queryClient.setQueryData([...dnKey, "one", String(latest.id)], latest);
    void queryClient.invalidateQueries({ queryKey: dnKey });
  };
  const act = useMutation({ mutationFn: (call: () => Promise<DNDetail>) => call(), onSuccess: done });
  const remove = useMutation({
    mutationFn: () => deleteDeliveryNote(note.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: dnKey });
      navigate("/delivery-notes");
    },
  });

  return (
    <section className="panel" aria-label={t("dn.actions")}>
      <p>
        <a className="button-link secondary" href={deliveryPdfUrl(note.id)} target="_blank" rel="noreferrer">
          {note.status === "draft" ? t("dn.printDraft") : t("dn.print")}
        </a>
      </p>
      {note.can_edit && (
        <p>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => issueDeliveryNote(note.id))}>
            {t("dn.issue")}
          </button>{" "}
          <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {t("dn.delete")}
          </button>{" "}
          <span className="muted">{t("dn.issueHelp")}</span>
        </p>
      )}
      {note.can_receive && (
        <div className="inline-form" aria-label={t("dn.recordReceipt")}>
          <label>
            {t("dn.receivedBy")}
            <input value={receivedBy} maxLength={100} onChange={(e) => setReceivedBy(e.target.value)} />
          </label>
          <label>
            {t("dn.receivedOn")}
            <input type="date" value={receivedOn} onChange={(e) => setReceivedOn(e.target.value)} />
          </label>
          <label>
            {t("dn.signedCopyFile")}
            <input type="file" accept="image/jpeg,image/png,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => recordReceipt(note.id, receivedBy, receivedOn, file))}>
            {t("dn.recordReceipt")}
          </button>
        </div>
      )}
      {note.can_cancel && (
        <div className="inline-form">
          <label>
            {t("dn.cancelReason")}
            <input value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => cancelDeliveryNote(note.id, reason))}>
            {t("dn.cancel")}
          </button>
        </div>
      )}
      <ErrorLine error={act.error ?? remove.error} />
    </section>
  );
}
