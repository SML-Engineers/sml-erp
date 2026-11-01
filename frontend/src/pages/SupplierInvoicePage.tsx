import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { listDivisions } from "../api/admin";
import { ApiError } from "../api/client";
import { listPayees } from "../api/payees";
import {
  addInvoiceScan,
  approveInvoiceException,
  cancelSupplierInvoice,
  createSupplierInvoice,
  deleteSupplierInvoice,
  getOpenLines,
  getSupplierInvoice,
  invoiceScanUrl,
  matchSupplierInvoice,
  removeInvoiceScan,
  reopenSupplierInvoice,
  requestInvoiceException,
  returnInvoiceException,
  siKey,
  updateSupplierInvoice,
  type InvoiceDetail,
  type InvoiceInput,
} from "../api/supplierInvoices";
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

function useDone() {
  const queryClient = useQueryClient();
  return (latest: InvoiceDetail) => {
    queryClient.setQueryData([...siKey, "one", String(latest.id)], latest);
    void queryClient.invalidateQueries({ queryKey: [...siKey, "list"] });
  };
}

/** One supplier invoice (spec 5A.4): entering it against GRN lines, the scan, the three-way
 * match, and the Director's approval of an exception. */
export default function SupplierInvoicePage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const isNew = id === "new";
  const invoice = useQuery({ queryKey: [...siKey, "one", id], queryFn: () => getSupplierInvoice(Number(id)), enabled: !isNew });
  const data = invoice.data;
  return (
    <main className="page">
      <p>
        <Link to="/supplier-invoices">{t("si.backToList")}</Link>
      </p>
      <h1>{isNew ? t("si.new") : t("si.one", { no: data?.invoice_no ?? "", supplier: data?.supplier.name ?? "" })}</h1>
      {isNew && <InvoiceForm />}
      {data && (
        <>
          <p className="muted">
            {t(`si.statuses.${data.status}`)} · {data.number} · {data.division} · {t("si.dueOn", { date: data.due_date })}
            {data.journal && ` · ${t("si.posted", { journal: data.journal })}`}
          </p>
          {data.discrepancies.length > 0 && data.status !== "posted" && (
            <section className="notice" aria-label={t("si.differences")}>
              <strong>{t("si.differences")}</strong>
              <ul>
                {data.discrepancies.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            </section>
          )}
          {data.exception_reason && <p className="muted">{t("si.exceptionReason", { reason: data.exception_reason })}</p>}
          {data.cancel_reason && <p className="notice">{t("si.cancelReason", { reason: data.cancel_reason })}</p>}
          {data.can_edit ? <InvoiceForm key={`${data.id}-${data.total_amount}`} invoice={data} /> : <ReadOnly invoice={data} />}
          <Scans invoice={data} />
          <Actions invoice={data} />
        </>
      )}
      <ErrorLine error={invoice.error} />
    </main>
  );
}

type Row = { grn_line: number; bill: boolean; quantity: string; unit_price: string; tax_code: string };

function InvoiceForm({ invoice }: { invoice?: InvoiceDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const done = useDone();
  const suppliers = useQuery({ queryKey: ["payees", "", false], queryFn: () => listPayees("", false), enabled: !invoice });
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions, enabled: !invoice });
  const [supplier, setSupplier] = useState(invoice ? String(invoice.supplier.id) : "");
  const [division, setDivision] = useState(invoice?.division ?? "");
  const open = useQuery({
    queryKey: [...siKey, "open", supplier, division],
    queryFn: () => getOpenLines(supplier, division),
    enabled: Boolean(supplier && division),
  });
  const [values, setValues] = useState({
    invoice_no: invoice?.invoice_no ?? "",
    invoice_date: invoice?.invoice_date ?? new Date().toISOString().slice(0, 10),
    stated_total: invoice?.stated_total ?? "",
    notes: invoice?.notes ?? "",
  });
  const [rows, setRows] = useState<Record<number, Row>>(() =>
    Object.fromEntries(
      (invoice?.lines ?? []).map((l) => [
        l.grn_line,
        { grn_line: l.grn_line, bill: true, quantity: l.quantity, unit_price: l.unit_price, tax_code: l.tax_code ?? "" },
      ]),
    ),
  );
  const rowOf = (grnLine: number, fallback: Row): Row => rows[grnLine] ?? fallback;
  const setRow = (row: Row) => setRows((now) => ({ ...now, [row.grn_line]: row }));
  const set = (field: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [field]: value }));
  const save = useMutation({
    mutationFn: () => {
      const input: InvoiceInput = {
        ...values,
        stated_total: values.stated_total || null,
        lines: Object.values(rows)
          .filter((r) => r.bill)
          .map((r) => ({ grn_line: r.grn_line, quantity: r.quantity, unit_price: r.unit_price, tax_code: r.tax_code || null })),
      };
      return invoice ? updateSupplierInvoice(invoice.id, input) : createSupplierInvoice({ ...input, supplier: Number(supplier), division });
    },
    onSuccess: (saved) => {
      done(saved);
      if (!invoice) navigate(`/supplier-invoices/${saved.id}`);
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("si.form")} onSubmit={submit}>
      {!invoice && (
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
        {t("si.invoiceNo")}
        <input value={values.invoice_no} maxLength={50} required onChange={(e) => set("invoice_no")(e.target.value)} />
      </label>
      <label>
        {t("si.invoiceDate")}
        <input type="date" value={values.invoice_date} required onChange={(e) => set("invoice_date")(e.target.value)} />
      </label>
      <label>
        {t("si.statedTotal")}
        <input inputMode="decimal" value={values.stated_total} onChange={(e) => set("stated_total")(e.target.value)} />
      </label>
      <div className="wide table-wrap">
        {open.data && open.data.length === 0 && <p className="muted">{t("si.nothingOpen")}</p>}
        {open.data && open.data.length > 0 && (
          <table aria-label={t("si.billedLines")}>
            <thead>
              <tr>
                <th>{t("si.bill")}</th>
                <th>{t("grn.number")}</th>
                <th>{t("po.item")}</th>
                <th className="num">{t("si.open")}</th>
                <th className="num">{t("si.quantity")}</th>
                <th className="num">{t("si.price")}</th>
                <th>{t("si.tax")}</th>
              </tr>
            </thead>
            <tbody>
              {open.data.map((o) => {
                const row = rowOf(o.grn_line, {
                  grn_line: o.grn_line,
                  bill: false,
                  quantity: o.open_quantity,
                  unit_price: o.po_unit_price,
                  tax_code: o.po_tax_code ?? "",
                });
                return (
                  <tr key={o.grn_line}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={t("si.billOf", { item: o.item.code, grn: o.grn.number })}
                        checked={row.bill}
                        onChange={(e) => setRow({ ...row, bill: e.target.checked })}
                      />
                    </td>
                    <td>
                      {o.grn.number}
                      <div className="muted">{o.po.label}</div>
                    </td>
                    <td>
                      <span className="mono">{o.item.code}</span> {o.item.name}
                    </td>
                    <td className="num">
                      {formatQuantity(o.open_quantity)} {o.item.unit}
                    </td>
                    <td className="num">
                      <input
                        aria-label={t("si.quantityOf", { item: o.item.code })}
                        inputMode="decimal"
                        value={row.quantity}
                        disabled={!row.bill}
                        onChange={(e) => setRow({ ...row, quantity: e.target.value })}
                      />
                    </td>
                    <td className="num">
                      <input
                        aria-label={t("si.priceOf", { item: o.item.code })}
                        inputMode="decimal"
                        value={row.unit_price}
                        disabled={!row.bill}
                        onChange={(e) => setRow({ ...row, unit_price: e.target.value })}
                      />
                      <div className="muted">{t("si.poPrice", { price: formatDecimal(o.po_unit_price) })}</div>
                    </td>
                    <td>
                      <input
                        aria-label={t("si.taxOf", { item: o.item.code })}
                        value={row.tax_code}
                        maxLength={20}
                        disabled={!row.bill}
                        onChange={(e) => setRow({ ...row, tax_code: e.target.value.toUpperCase() })}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      <label className="wide">
        {t("customers.field.notes")}
        <textarea value={values.notes} onChange={(e) => set("notes")(e.target.value)} />
      </label>
      <p className="wide muted">{t("si.formHelp")}</p>
      <div className="wide">
        <button type="submit" disabled={save.isPending}>
          {t("si.save")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </form>
  );
}

function ReadOnly({ invoice }: { invoice: InvoiceDetail }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("si.details")}>
      <div className="table-wrap">
        <table aria-label={t("si.billedLines")}>
          <thead>
            <tr>
              <th>{t("grn.number")}</th>
              <th>{t("po.item")}</th>
              <th className="num">{t("si.accepted")}</th>
              <th className="num">{t("si.quantity")}</th>
              <th className="num">{t("si.price")}</th>
              <th className="num">{t("si.poPriceHeader")}</th>
              <th>{t("si.tax")}</th>
              <th className="num">{t("vouchers.total")}</th>
            </tr>
          </thead>
          <tbody>
            {invoice.lines.map((l) => (
              <tr key={l.line_no}>
                <td>
                  <Link to={`/goods-receipts/${l.grn.id}`}>{l.grn.number}</Link>
                  <div className="muted">
                    <Link to={`/purchase-orders/${l.po.id}`}>{l.po.label}</Link>
                  </div>
                </td>
                <td>
                  <span className="mono">{l.item.code}</span> {l.item.name}
                </td>
                <td className="num">{formatQuantity(l.accepted_quantity)}</td>
                <td className="num">
                  {formatQuantity(l.quantity)} {l.item.unit}
                </td>
                <td className={l.unit_price !== l.po_unit_price ? "num form-error" : "num"}>{formatDecimal(l.unit_price)}</td>
                <td className="num">{formatDecimal(l.po_unit_price)}</td>
                <td className={l.tax_code !== l.po_tax_code ? "form-error" : ""}>{l.tax_code ?? "—"}</td>
                <td className="num">{formatDecimal(l.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        {t("si.totals", {
          currency: invoice.currency,
          subtotal: formatDecimal(invoice.subtotal),
          tax: formatDecimal(invoice.tax_total),
          total: formatDecimal(invoice.total_amount),
          stated: invoice.stated_total ? formatDecimal(invoice.stated_total) : "—",
        })}
      </p>
      {invoice.notes && <p className="pre-line">{invoice.notes}</p>}
    </section>
  );
}

function Scans({ invoice }: { invoice: InvoiceDetail }) {
  const { t } = useTranslation();
  const done = useDone();
  const add = useMutation({ mutationFn: (file: File) => addInvoiceScan(invoice.id, file), onSuccess: done });
  const remove = useMutation({ mutationFn: (file: number) => removeInvoiceScan(invoice.id, file), onSuccess: done });
  return (
    <section className="panel" aria-label={t("si.scans")}>
      <h2>{t("si.scans")}</h2>
      {invoice.attachments.length === 0 && <p className="muted">{t("si.noScan")}</p>}
      <ul>
        {invoice.attachments.map((a) => (
          <li key={a.id}>
            <a href={invoiceScanUrl(invoice.id, a.id)} target="_blank" rel="noreferrer">
              {a.file_name}
            </a>{" "}
            <span className="muted">{a.uploaded_by}</span>{" "}
            {invoice.can_edit && (
              <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate(a.id)}>
                {t("grn.removePhoto")}
              </button>
            )}
          </li>
        ))}
      </ul>
      {invoice.can_edit && (
        <label>
          {t("si.addScan")}
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

function Actions({ invoice }: { invoice: InvoiceDetail }) {
  const { t } = useTranslation();
  const done = useDone();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const act = useMutation({
    mutationFn: (call: () => Promise<InvoiceDetail>) => call(),
    onSuccess: (latest) => {
      done(latest);
      setText("");
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteSupplierInvoice(invoice.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: siKey });
      navigate("/supplier-invoices");
    },
  });
  const needsText = invoice.can_request_exception || invoice.can_cancel || invoice.can_approve;
  if (!invoice.can_edit && !needsText && !invoice.can_reopen && invoice.history.length === 0) return null;
  return (
    <section className="panel" aria-label={t("si.actions")}>
      {invoice.can_edit && (
        <p>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => matchSupplierInvoice(invoice.id))}>
            {t("si.match")}
          </button>{" "}
          <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {t("si.delete")}
          </button>{" "}
          <span className="muted">{t("si.matchHelp")}</span>
        </p>
      )}
      {invoice.can_reopen && (
        <p>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => reopenSupplierInvoice(invoice.id))}>
            {t("si.reopen")}
          </button>
        </p>
      )}
      {needsText && (
        <div className="inline-form">
          <label>
            {t("salesOrders.comment")}
            <input value={text} maxLength={1000} onChange={(e) => setText(e.target.value)} />
          </label>
          {invoice.can_request_exception && (
            <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => requestInvoiceException(invoice.id, text))}>
              {t("si.askException")}
            </button>
          )}
          {invoice.can_cancel && (
            <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => cancelSupplierInvoice(invoice.id, text))}>
              {t("si.cancel")}
            </button>
          )}
          {invoice.can_approve && (
            <>
              <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => approveInvoiceException(invoice.id, text))}>
                {t("si.approve")}
              </button>
              <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => returnInvoiceException(invoice.id, text))}>
                {t("salesOrders.sendBack")}
              </button>
            </>
          )}
        </div>
      )}
      <ErrorLine error={act.error ?? remove.error} />
      {invoice.history.length > 0 && (
        <ul className="changes">
          {invoice.history.map((h, i) => (
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
