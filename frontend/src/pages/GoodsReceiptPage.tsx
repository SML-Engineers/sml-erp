import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError } from "../api/client";
import {
  addGoodsReceiptPhoto,
  approveExcess,
  approveReversal,
  confirmGoodsReceipt,
  deleteGoodsReceipt,
  getGoodsReceipt,
  goodsReceiptLabelsUrl,
  goodsReceiptPhotoUrl,
  grnKey,
  refuseReversal,
  removeGoodsReceiptPhoto,
  requestReversal,
  returnGoodsReceipt,
  updateGoodsReceipt,
  type ApprovalStep,
  type GRNDetail,
} from "../api/goodsReceipts";
import { poKey } from "../api/purchaseOrders";
import PackagesPanel from "../components/PackagesPanel";
import { formatQuantity } from "../lib/decimal";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

function useDone() {
  const queryClient = useQueryClient();
  return (latest: GRNDetail) => {
    queryClient.setQueryData([...grnKey, "one", String(latest.id)], latest);
    void queryClient.invalidateQueries({ queryKey: [...grnKey, "list"] });
    void queryClient.invalidateQueries({ queryKey: poKey });
  };
}

/** One goods receiving note (spec 5A.2): entering what arrived, confirming it, the Director's
 * approval of an excess, photos, and a reversal. */
export default function GoodsReceiptPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const grn = useQuery({ queryKey: [...grnKey, "one", id], queryFn: () => getGoodsReceipt(Number(id)) });
  const data = grn.data;

  return (
    <main className="page">
      <p>
        <Link to="/goods-receipts">{t("grn.backToList")}</Link>
      </p>
      <h1>{`${t("grn.one")} ${data?.number ?? ""}`}</h1>
      {data && (
        <>
          <p className="muted">
            {t(`grn.statuses.${data.status}`)} · {data.receipt_date} · {data.division} · {t("grn.po")}{" "}
            <Link to={`/purchase-orders/${data.purchase_order.id}`}>{data.purchase_order.label}</Link> · {data.supplier.code}{" "}
            {data.supplier.name} · {t("grn.store")} {data.store}
          </p>
          {data.confirmed_by && data.confirmed_at && (
            <p className="muted">{t("grn.confirmedBy", { name: data.confirmed_by, at: data.confirmed_at.slice(0, 16).replace("T", " ") })}</p>
          )}
          {data.reversal_reason && <p className="notice">{t("grn.reversalReason", { reason: data.reversal_reason })}</p>}
          {data.can_edit ? <ReceiptForm key={`${data.id}-${data.lines.map((l) => l.received_quantity).join()}`} grn={data} /> : <ReadOnly grn={data} />}
          {data.lines
            .filter((l) => l.item.package_type !== "none")
            .map((l) => (
              <PackagesPanel key={`${l.line_no}-${l.packages.map((p) => p.lot_no + (p.gross_weight ?? "")).join()}`} grn={data} line={l} />
            ))}
          {data.lines.some((l) => l.packages.length > 0) && (
            <p>
              <a className="button-link secondary" href={goodsReceiptLabelsUrl(data.id)} target="_blank" rel="noreferrer">
                {t("grn.printAllLabels")}
              </a>
            </p>
          )}
          <Actions grn={data} />
          <Photos grn={data} />
        </>
      )}
      <ErrorLine error={grn.error} />
    </main>
  );
}

function ReceiptForm({ grn }: { grn: GRNDetail }) {
  const { t } = useTranslation();
  const done = useDone();
  const [values, setValues] = useState({
    receipt_date: grn.receipt_date,
    delivery_note_no: grn.delivery_note_no,
    vehicle_no: grn.vehicle_no,
    supplier_invoice_no: grn.supplier_invoice_no,
    notes: grn.notes,
  });
  const [lines, setLines] = useState(
    grn.lines.map((l) => ({ po_line: l.po_line, received_quantity: l.received_quantity, damaged_quantity: l.damaged_quantity, notes: l.notes })),
  );
  const set = (field: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [field]: value }));
  const setLine = (index: number, change: Partial<(typeof lines)[number]>) =>
    setLines((now) => now.map((l, i) => (i === index ? { ...l, ...change } : l)));
  const save = useMutation({ mutationFn: () => updateGoodsReceipt(grn.id, { ...values, lines }), onSuccess: done });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("grn.form")} onSubmit={submit}>
      <label>
        {t("grn.receiptDate")}
        <input type="date" value={values.receipt_date} required onChange={(e) => set("receipt_date")(e.target.value)} />
      </label>
      <label>
        {t("grn.deliveryNote")}
        <input value={values.delivery_note_no} maxLength={50} onChange={(e) => set("delivery_note_no")(e.target.value)} />
      </label>
      <label>
        {t("grn.vehicle")}
        <input value={values.vehicle_no} maxLength={30} onChange={(e) => set("vehicle_no")(e.target.value)} />
      </label>
      <label>
        {t("grn.supplierInvoice")}
        <input value={values.supplier_invoice_no} maxLength={50} onChange={(e) => set("supplier_invoice_no")(e.target.value)} />
      </label>
      <div className="wide table-wrap">
        <table aria-label={t("grn.lines")}>
          <thead>
            <tr>
              <th>{t("po.item")}</th>
              <th className="num">{t("grn.ordered")}</th>
              <th className="num">{t("grn.stillExpected")}</th>
              <th className="num">{t("grn.received")}</th>
              <th className="num">{t("grn.damaged")}</th>
              <th>{t("grn.lineNotes")}</th>
            </tr>
          </thead>
          <tbody>
            {grn.lines.map((l, i) => (
              <tr key={l.po_line}>
                <td>
                  <span className="mono">{l.item.code}</span> {l.description}
                </td>
                <td className="num">
                  {formatQuantity(l.ordered_quantity)} {l.unit}
                </td>
                <td className="num">{formatQuantity(l.outstanding_quantity)}</td>
                <td className="num">
                  <input
                    aria-label={t("grn.receivedOf", { item: l.item.code })}
                    inputMode="decimal"
                    value={lines[i].received_quantity}
                    disabled={l.item.package_type !== "none"}
                    onChange={(e) => setLine(i, { received_quantity: e.target.value })}
                  />
                </td>
                <td className="num">
                  <input
                    aria-label={t("grn.damagedOf", { item: l.item.code })}
                    inputMode="decimal"
                    value={lines[i].damaged_quantity}
                    disabled={l.item.package_type !== "none"}
                    onChange={(e) => setLine(i, { damaged_quantity: e.target.value })}
                  />
                </td>
                <td>
                  <input
                    aria-label={t("grn.notesOf", { item: l.item.code })}
                    maxLength={300}
                    value={lines[i].notes}
                    onChange={(e) => setLine(i, { notes: e.target.value })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <label className="wide">
        {t("customers.field.notes")}
        <textarea value={values.notes} maxLength={5000} onChange={(e) => set("notes")(e.target.value)} />
      </label>
      <p className="wide muted">{t("grn.formHelp")}</p>
      <div className="wide">
        <button type="submit" disabled={save.isPending}>
          {t("grn.save")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </form>
  );
}

function ReadOnly({ grn }: { grn: GRNDetail }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("grn.details")}>
      <dl className="details">
        <dt>{t("grn.deliveryNote")}</dt>
        <dd>{grn.delivery_note_no || "—"}</dd>
        <dt>{t("grn.vehicle")}</dt>
        <dd>{grn.vehicle_no || "—"}</dd>
        <dt>{t("grn.supplierInvoice")}</dt>
        <dd>{grn.supplier_invoice_no || "—"}</dd>
        {grn.notes && (
          <>
            <dt>{t("customers.field.notes")}</dt>
            <dd>{grn.notes}</dd>
          </>
        )}
      </dl>
      <div className="table-wrap">
        <table aria-label={t("grn.lines")}>
          <thead>
            <tr>
              <th>{t("po.item")}</th>
              <th className="num">{t("grn.stillExpected")}</th>
              <th className="num">{t("grn.received")}</th>
              <th className="num">{t("grn.damaged")}</th>
              <th className="num">{t("grn.good")}</th>
              <th className="num">{t("grn.excess")}</th>
            </tr>
          </thead>
          <tbody>
            {grn.lines.map((l) => (
              <tr key={l.line_no}>
                <td>
                  <span className="mono">{l.item.code}</span> {l.description}
                  {l.notes && <div className="muted">{l.notes}</div>}
                </td>
                <td className="num">{formatQuantity(l.outstanding_quantity)}</td>
                <td className="num">
                  {formatQuantity(l.received_quantity)} {l.unit}
                </td>
                <td className="num">{formatQuantity(l.damaged_quantity)}</td>
                <td className="num">{formatQuantity(l.good_quantity)}</td>
                <td className={Number(l.excess_quantity) > 0 ? "num form-error" : "num"}>{formatQuantity(l.excess_quantity)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function History({ label, rows }: { label: string; rows: ApprovalStep[] }) {
  if (rows.length === 0) return null;
  return (
    <ul className="changes" aria-label={label}>
      {rows.map((h, i) => (
        <li key={i}>
          {h.at.slice(0, 16).replace("T", " ")} · {h.action_label} · {h.by}
          {h.reason ? ` · ${h.reason}` : ""}
        </li>
      ))}
    </ul>
  );
}

function Actions({ grn }: { grn: GRNDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const done = useDone();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const act = useMutation({
    mutationFn: (call: () => Promise<GRNDetail>) => call(),
    onSuccess: (latest) => {
      done(latest);
      setText("");
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteGoodsReceipt(grn.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: grnKey });
      navigate("/goods-receipts");
    },
  });
  const needsText = grn.can_approve_excess || grn.can_request_reversal || grn.can_approve_reversal;
  const any = grn.can_edit || needsText;
  if (!any && grn.excess_history.length === 0 && grn.reversal_history.length === 0) return null;

  return (
    <section className="panel" aria-label={t("grn.actions")}>
      {grn.can_edit && (
        <p>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => confirmGoodsReceipt(grn.id))}>
            {t("grn.confirm")}
          </button>{" "}
          <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {t("grn.delete")}
          </button>{" "}
          <span className="muted">{t("grn.confirmHelp")}</span>
        </p>
      )}
      {needsText && (
        <div className="inline-form">
          <label>
            {t("salesOrders.comment")}
            <input value={text} maxLength={500} onChange={(e) => setText(e.target.value)} />
          </label>
          {grn.can_approve_excess && (
            <>
              <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => approveExcess(grn.id, text))}>
                {t("grn.approveExcess")}
              </button>
              <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => returnGoodsReceipt(grn.id, text))}>
                {t("salesOrders.sendBack")}
              </button>
            </>
          )}
          {grn.can_request_reversal && (
            <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => requestReversal(grn.id, text))}>
              {t("grn.requestReversal")}
            </button>
          )}
          {grn.can_approve_reversal && (
            <>
              <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => approveReversal(grn.id, text))}>
                {t("grn.approveReversal")}
              </button>
              <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => refuseReversal(grn.id, text))}>
                {t("grn.refuseReversal")}
              </button>
            </>
          )}
        </div>
      )}
      <ErrorLine error={act.error ?? remove.error} />
      <History label={t("grn.excessHistory")} rows={grn.excess_history} />
      <History label={t("grn.reversalHistory")} rows={grn.reversal_history} />
    </section>
  );
}

function Photos({ grn }: { grn: GRNDetail }) {
  const { t } = useTranslation();
  const done = useDone();
  const add = useMutation({ mutationFn: (file: File) => addGoodsReceiptPhoto(grn.id, file), onSuccess: done });
  const remove = useMutation({ mutationFn: (photo: number) => removeGoodsReceiptPhoto(grn.id, photo), onSuccess: done });
  if (!grn.can_add_photo && grn.photos.length === 0) return null;
  return (
    <section className="panel" aria-label={t("grn.photos")}>
      <h2>{t("grn.photos")}</h2>
      {grn.photos.length === 0 && <p className="muted">{t("grn.noPhotos")}</p>}
      <ul>
        {grn.photos.map((p) => (
          <li key={p.id}>
            <a href={goodsReceiptPhotoUrl(grn.id, p.id)} target="_blank" rel="noreferrer">
              {p.file_name}
            </a>{" "}
            <span className="muted">
              {p.uploaded_by} · {p.uploaded_at.slice(0, 16).replace("T", " ")}
            </span>{" "}
            {grn.can_edit && (
              <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate(p.id)}>
                {t("grn.removePhoto")}
              </button>
            )}
          </li>
        ))}
      </ul>
      {grn.can_add_photo && (
        <label>
          {t("grn.addPhoto")}
          <input
            type="file"
            accept="image/jpeg,image/png,application/pdf"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) add.mutate(file);
              e.target.value = "";
            }}
          />
        </label>
      )}
      <ErrorLine error={add.error ?? remove.error} />
    </section>
  );
}
