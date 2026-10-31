import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { ApiError } from "../api/client";
import { INCOTERMS } from "../api/customers";
import {
  cancelProforma,
  getProforma,
  getProformaEmail,
  issueProforma,
  PACKING_FIELDS,
  proformaPdfUrl,
  proformasKey,
  sendProformaEmail,
  updateProforma,
  type PackingField,
  type ProformaDetail,
} from "../api/proformas";
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

/** One proforma invoice (spec 5.2): its lines and packing list, issue, cancel, print, email. */
export default function ProformaPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const proforma = useQuery({ queryKey: [...proformasKey, "one", id], queryFn: () => getProforma(Number(id)) });
  const data = proforma.data;

  return (
    <main className="page">
      <p>
        <Link to="/proformas">{t("proformas.backToList")}</Link>
      </p>
      <h1>
        {t("proformas.proforma")} {data?.number}
      </h1>
      {data && (
        <>
          <p className="muted">
            {t(`proformas.statuses.${data.status}`)} · {data.issue_date} · {data.customer.code} {data.customer.name} ·{" "}
            <Link to={`/quotations/${data.quotation.id}`}>{data.quotation.label}</Link>
          </p>
          {data.status === "cancelled" && <p className="notice">{t("proformas.cancelledBecause", { reason: data.cancel_reason })}</p>}
          <p>
            <a className="button-link secondary" href={proformaPdfUrl(data.id)} target="_blank" rel="noreferrer">
              {t("proformas.printPdf")}
            </a>{" "}
            {data.status === "draft" && <span className="muted">{t("proformas.printsAsDraft")}</span>}
          </p>
          <p className="muted">{t("proformas.noSale")}</p>
          {data.can_edit ? <ProformaForm key={`${data.id}-${data.total_amount}`} proforma={data} /> : <ReadOnly proforma={data} />}
          <Actions proforma={data} />
        </>
      )}
      <ErrorLine error={proforma.error} />
    </main>
  );
}

type LineState = { quotation_line: number; quantity: string } & Record<PackingField, string>;

function ProformaForm({ proforma }: { proforma: ProformaDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [values, setValues] = useState({
    customer_po: proforma.customer_po,
    payment_terms: proforma.payment_terms,
    delivery_lead_time: proforma.delivery_lead_time,
    incoterm: proforma.incoterm,
    port_of_loading: proforma.port_of_loading,
    port_of_destination: proforma.port_of_destination,
    bank_account: proforma.bank_account ? String(proforma.bank_account.id) : "",
    advance_pct: Number(proforma.advance_pct) ? proforma.advance_pct : "",
    discount_pct: Number(proforma.discount_pct) ? proforma.discount_pct : "",
    notes: proforma.notes,
  });
  const [lines, setLines] = useState<LineState[]>(
    proforma.lines.map((l) => ({
      quotation_line: l.quotation_line,
      quantity: l.quantity,
      ...Object.fromEntries(PACKING_FIELDS.map((f) => [f, l[f] ?? ""])),
    })) as LineState[],
  );
  const set = (field: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [field]: value }));
  const setLine = (index: number, change: Partial<LineState>) => setLines((now) => now.map((l, i) => (i === index ? { ...l, ...change } : l)));
  const unused = proforma.quotation_lines.filter((q) => !lines.some((l) => l.quotation_line === q.id));

  const save = useMutation({
    mutationFn: () =>
      updateProforma(proforma.id, {
        ...values,
        bank_account: values.bank_account ? Number(values.bank_account) : null,
        lines: lines.map((l) => ({
          ...Object.fromEntries(Object.entries(l).filter(([, v]) => v !== "")),
          quotation_line: l.quotation_line,
          quantity: l.quantity,
        })),
      }),
    onSuccess: (latest) => queryClient.setQueryData([...proformasKey, "one", String(latest.id)], latest),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("proformas.form")} onSubmit={submit}>
      <label>
        {t("proformas.customerPo")}
        <input value={values.customer_po} maxLength={50} onChange={(e) => set("customer_po")(e.target.value)} />
      </label>
      <label>
        {t("quotations.paymentTerms")}
        <input value={values.payment_terms} maxLength={200} onChange={(e) => set("payment_terms")(e.target.value)} />
      </label>
      <label>
        {t("quotations.leadTime")}
        <input value={values.delivery_lead_time} maxLength={100} onChange={(e) => set("delivery_lead_time")(e.target.value)} />
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
      <label>
        {t("proformas.portOfLoading")}
        <input value={values.port_of_loading} maxLength={100} onChange={(e) => set("port_of_loading")(e.target.value)} />
      </label>
      <label>
        {t("proformas.portOfDestination")}
        <input value={values.port_of_destination} maxLength={100} onChange={(e) => set("port_of_destination")(e.target.value)} />
      </label>
      <label>
        {t("proformas.bankAccount")}
        <select value={values.bank_account} onChange={(e) => set("bank_account")(e.target.value)}>
          <option value="">—</option>
          {proforma.bank_choices.map((a) => (
            <option key={a.id} value={a.id}>
              {a.code} {a.bank_name || a.name} ({a.currency})
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("proformas.advancePct")}
        <input inputMode="decimal" className="num" value={values.advance_pct} placeholder="0" onChange={(e) => set("advance_pct")(e.target.value)} />
      </label>
      <label>
        {t("quotations.discountPct")}
        <input inputMode="decimal" className="num" value={values.discount_pct} placeholder="0" onChange={(e) => set("discount_pct")(e.target.value)} />
      </label>
      <label className="wide">
        {t("customers.field.notes")}
        <textarea rows={3} value={values.notes} onChange={(e) => set("notes")(e.target.value)} />
      </label>

      <div className="wide">
        <h2>{t("proformas.linesAndPacking")}</h2>
        <p className="muted">{t("proformas.priceHelp")}</p>
        {lines.map((l, index) => {
          const source = proforma.quotation_lines.find((q) => q.id === l.quotation_line);
          const n = String(index + 1);
          return (
            <fieldset key={l.quotation_line} className="quote-line">
              <legend>
                {t("quotations.lineN", { n })}: {source?.description}
              </legend>
              <div className="form-grid">
                <label>
                  {t("quotations.quantity")}
                  <input inputMode="decimal" className="num" aria-label={t("quotations.quantityOf", { n })} value={l.quantity} required onChange={(e) => setLine(index, { quantity: e.target.value })} />
                </label>
                {PACKING_FIELDS.map((field) => (
                  <label key={field}>
                    {t(`proformas.packing.${field}`)}
                    <input
                      inputMode="decimal"
                      className="num"
                      aria-label={t("proformas.packingOf", { what: t(`proformas.packing.${field}`), n })}
                      value={l[field]}
                      onChange={(e) => setLine(index, { [field]: e.target.value } as Partial<LineState>)}
                    />
                  </label>
                ))}
              </div>
              {lines.length > 1 && (
                <button type="button" className="small secondary" onClick={() => setLines((now) => now.filter((_, i) => i !== index))}>
                  {t("quotations.removeLine")}
                </button>
              )}
            </fieldset>
          );
        })}
        {unused.length > 0 && (
          <label>
            {t("proformas.addQuotationLine")}
            <select
              value=""
              onChange={(e) => {
                const chosen = proforma.quotation_lines.find((q) => String(q.id) === e.target.value);
                if (chosen)
                  setLines((now) => [
                    ...now,
                    { quotation_line: chosen.id, quantity: chosen.quantity, ...Object.fromEntries(PACKING_FIELDS.map((f) => [f, ""])) } as LineState,
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
      <Totals proforma={proforma} />
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

function Totals({ proforma }: { proforma: ProformaDetail }) {
  const { t } = useTranslation();
  const c = proforma.currency;
  const pack = proforma.packing_totals;
  return (
    <div className="wide">
      {Number(proforma.discount_total) !== 0 && (
        <p>
          {t("quotations.discountLine", { pct: proforma.discount_pct })}: <strong>−{formatDecimal(proforma.discount_total)}</strong>
        </p>
      )}
      <p>
        {t("quotations.subtotal")}: <strong>{c} {formatDecimal(proforma.subtotal)}</strong> · {t("vouchers.tax")}:{" "}
        <strong>{formatDecimal(proforma.tax_total)}</strong> · {t("vouchers.total")}:{" "}
        <strong>
          {c} {formatDecimal(proforma.total_amount)}
        </strong>
      </p>
      {Number(proforma.advance_pct) !== 0 && (
        <p>{t("proformas.advanceLine", { pct: proforma.advance_pct, amount: `${c} ${formatDecimal(proforma.advance_amount)}` })}</p>
      )}
      {pack.cartons && (
        <p className="muted">
          {t("proformas.packingTotals", {
            cartons: pack.cartons,
            net: pack.net_weight_kg ? formatQuantity(pack.net_weight_kg) : "—",
            gross: pack.gross_weight_kg ? formatQuantity(pack.gross_weight_kg) : "—",
            volume: pack.volume_m3 ? formatQuantity(pack.volume_m3) : "—",
          })}
        </p>
      )}
    </div>
  );
}

function ReadOnly({ proforma }: { proforma: ProformaDetail }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("proformas.details")}>
      <div className="table-wrap">
        <table aria-label={t("proformas.linesAndPacking")}>
          <thead>
            <tr>
              <th>#</th>
              <th>{t("quotations.description")}</th>
              <th className="num">{t("quotations.quantity")}</th>
              <th className="num">{t("quotations.unitPrice")}</th>
              <th className="num">{t("vouchers.total")}</th>
              <th className="num">{t("proformas.packing.cartons")}</th>
              <th className="num">{t("proformas.packing.gross_weight_kg")}</th>
            </tr>
          </thead>
          <tbody>
            {proforma.lines.map((l) => (
              <tr key={l.line_no}>
                <td>{l.line_no}</td>
                <td>{l.description}</td>
                <td className="num">
                  {formatQuantity(l.quantity)} {l.unit}
                </td>
                <td className="num">{formatDecimal(l.unit_price)}</td>
                <td className="num">{formatDecimal(l.total)}</td>
                <td className="num">{l.cartons ?? ""}</td>
                <td className="num">{l.gross_weight_kg ? formatQuantity(l.gross_weight_kg) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Totals proforma={proforma} />
    </section>
  );
}

function Actions({ proforma }: { proforma: ProformaDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState<{ to: string; subject: string; body: string } | null>(null);
  const done = (latest: ProformaDetail) => {
    queryClient.setQueryData([...proformasKey, "one", String(latest.id)], latest);
    void queryClient.invalidateQueries({ queryKey: [...proformasKey, "list"] });
    setMessage(null);
  };
  const act = useMutation({ mutationFn: (call: () => Promise<ProformaDetail>) => call(), onSuccess: done });
  const load = useMutation({
    mutationFn: () => getProformaEmail(proforma.id),
    onSuccess: (draft) => setMessage({ to: draft.to.join(", "), subject: draft.subject, body: draft.body }),
  });
  const to = (value: string) =>
    value
      .split(/[,;]/)
      .map((a) => a.trim())
      .filter(Boolean);

  return (
    <section className="panel" aria-label={t("proformas.actions")}>
      {proforma.can_edit && (
        <p>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => issueProforma(proforma.id))}>
            {t("proformas.issue")}
          </button>{" "}
          <span className="muted">{t("proformas.issueHelp")}</span>
        </p>
      )}
      {proforma.can_email && !message && (
        <button type="button" disabled={load.isPending} onClick={() => load.mutate()}>
          {t("quotations.emailToCustomer")}
        </button>
      )}
      {message && (
        <form
          className="form-grid"
          aria-label={t("quotations.emailForm")}
          onSubmit={(e) => {
            e.preventDefault();
            act.mutate(() => sendProformaEmail(proforma.id, { to: to(message.to), cc: [], subject: message.subject, body: message.body }));
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
            <button type="submit">{t("quotations.sendEmail")}</button>{" "}
            <button type="button" className="secondary" onClick={() => setMessage(null)}>
              {t("quotations.cancel")}
            </button>
          </div>
        </form>
      )}
      {proforma.can_cancel && (
        <div className="inline-form">
          <label>
            {t("proformas.cancelReason")}
            <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => cancelProforma(proforma.id, reason))}>
            {t("proformas.cancel")}
          </button>
        </div>
      )}
      <ErrorLine error={act.error ?? load.error} />
      {proforma.advances.length > 0 && (
        <p>
          {t("proformas.advancesReceived")}:{" "}
          {proforma.advances.map((a) => `${a.number} (${formatDecimal(a.amount)})`).join(", ")}
        </p>
      )}
      {proforma.emails.length > 0 && (
        <ul className="changes" aria-label={t("quotations.emailsSent")}>
          {proforma.emails.map((m, i) => (
            <li key={i}>
              {m.status === "sent" ? "✓" : "✗"} {m.sent_at.slice(0, 16).replace("T", " ")} · {m.to} · {m.by}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
