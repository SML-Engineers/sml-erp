import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { listDivisions } from "../api/admin";
import { ApiError } from "../api/client";
import { INCOTERMS, listContacts, listCustomers, listPickerCurrencies, type Customer } from "../api/customers";
import {
  createQuotation,
  getQuotation,
  quotationFileUrl,
  quotationsKey,
  removeQuotationFile,
  updateQuotation,
  uploadQuotationFile,
  type LineInput,
  type QuotationDetail,
} from "../api/quotations";
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

const emptyLine = (): LineInput => ({
  description: "",
  drawing_no: "",
  drawing_rev: "",
  quantity: "",
  unit: "pcs",
  min_order_qty: null,
  unit_price: "",
  is_tooling: false,
  tax_code: null,
  breaks: [],
});

/** A quotation: entered and changed by its creator while a draft (spec 5.1). */
export default function QuotationPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const isNew = id === undefined || id === "new";
  const quotation = useQuery({
    queryKey: [...quotationsKey, "one", id],
    queryFn: () => getQuotation(Number(id)),
    enabled: !isNew,
  });
  const data = quotation.data;
  const title = data ? `${t("quotations.quotation")} ${data.number}${data.revision ? ` Rev ${data.revision}` : ""}` : t("quotations.new");

  return (
    <main className="page">
      <p>
        <Link to="/quotations">{t("quotations.backToList")}</Link>
      </p>
      <h1>{title}</h1>
      {data && (
        <p className="muted">
          {t(`quotations.statuses.${data.status}`)} · {data.division} · {data.quote_date} · {t("vouchers.createdBy", { name: data.created_by })}
        </p>
      )}
      {data?.can_see_costing && (
        <p>
          <Link className="button-link" to={`/quotations/${data.id}/costing`}>
            {t("quoteCosting.open")}
          </Link>{" "}
          <span className="muted">{t("quoteCosting.internalOnly")}</span>
        </p>
      )}
      {(isNew || data?.can_edit) && <QuotationForm key={data?.id ?? "new"} quotation={data} />}
      {data && !data.can_edit && <ReadOnly quotation={data} />}
      {data && <Files quotation={data} />}
      <ErrorLine error={quotation.error} />
    </main>
  );
}

function QuotationForm({ quotation }: { quotation?: QuotationDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const customers = useQuery({ queryKey: ["customers", "", false], queryFn: () => listCustomers("", false) });
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions, enabled: !quotation });
  const currencies = useQuery({ queryKey: ["currencies", "picker"], queryFn: listPickerCurrencies });
  const taxes = useQuery({ queryKey: taxesKey, queryFn: getTaxes });
  const [customerId, setCustomerId] = useState(quotation ? String(quotation.customer.id) : "");
  const contacts = useQuery({
    queryKey: ["customers", Number(customerId), "contacts"],
    queryFn: () => listContacts(Number(customerId)),
    enabled: customerId !== "",
  });
  const [values, setValues] = useState({
    division: quotation?.division ?? "",
    contact: quotation?.contact ? String(quotation.contact.id) : "",
    currency: quotation?.currency ?? "",
    valid_until: quotation?.valid_until ?? "",
    enquiry_ref: quotation?.enquiry_ref ?? "",
    payment_terms: quotation?.payment_terms ?? "",
    delivery_lead_time: quotation?.delivery_lead_time ?? "",
    incoterm: quotation?.incoterm ?? "",
    notes: quotation?.notes ?? "",
  });
  const [lines, setLines] = useState<LineInput[]>(
    quotation?.lines.map((l) => ({
      id: l.id,
      description: l.description,
      drawing_no: l.drawing_no,
      drawing_rev: l.drawing_rev,
      quantity: l.quantity,
      unit: l.unit,
      min_order_qty: l.min_order_qty,
      unit_price: l.unit_price,
      is_tooling: l.is_tooling,
      tax_code: l.tax_code,
      breaks: l.breaks,
    })) ?? [emptyLine()],
  );
  const set = (field: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [field]: value }));
  const setLine = (index: number, change: Partial<LineInput>) =>
    setLines((now) => now.map((l, i) => (i === index ? { ...l, ...change } : l)));
  const salesCodes = (taxes.data?.codes ?? []).filter((c) => c.is_active && c.use !== "purchases");
  const production = (divisions.data ?? []).filter((d) => d.division_type !== "shared");

  function chooseCustomer(value: string) {
    setCustomerId(value);
    const chosen: Customer | undefined = customers.data?.find((c) => String(c.id) === value);
    if (chosen && !quotation) {
      // The customer's own terms, as a starting point.
      setValues((now) => ({
        ...now,
        contact: chosen.main_contact ? String(chosen.main_contact.id) : "",
        currency: chosen.currency,
        incoterm: chosen.incoterm,
        payment_terms: chosen.payment_terms_days ? `${chosen.payment_terms_days} days` : t("quotations.onReceipt"),
      }));
    }
  }

  const save = useMutation({
    mutationFn: () => {
      const input = {
        customer: customerId ? Number(customerId) : undefined,
        contact: values.contact ? Number(values.contact) : null,
        division: quotation ? undefined : values.division,
        currency: values.currency || undefined,
        valid_until: values.valid_until || undefined,
        enquiry_ref: values.enquiry_ref,
        payment_terms: values.payment_terms,
        delivery_lead_time: values.delivery_lead_time,
        incoterm: values.incoterm,
        notes: values.notes,
        lines: lines.map((l) => ({ ...l, min_order_qty: l.min_order_qty?.trim() ? l.min_order_qty : null })),
      };
      return quotation ? updateQuotation(quotation.id, input) : createQuotation(input);
    },
    onSuccess: (saved) => {
      queryClient.setQueryData([...quotationsKey, "one", String(saved.id)], saved);
      void queryClient.invalidateQueries({ queryKey: quotationsKey });
      if (!quotation) navigate(`/quotations/${saved.id}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("quotations.form")} onSubmit={submit}>
      <div className="wide">
        <SearchSelect
          label={t("quotations.customer")}
          options={(customers.data ?? []).map((c) => ({ value: String(c.id), label: `${c.code} ${c.name}` }))}
          value={customerId}
          onChange={chooseCustomer}
        />
      </div>
      {!quotation && (
        <label>
          {t("vouchers.division")}
          <select value={values.division} required onChange={(e) => set("division")(e.target.value)}>
            <option value="">—</option>
            {production.map((d) => (
              <option key={d.code} value={d.code}>
                {d.code} {d.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        {t("quotations.contact")}
        <select value={values.contact} onChange={(e) => set("contact")(e.target.value)}>
          <option value="">—</option>
          {contacts.data
            ?.filter((c) => c.is_active)
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
        </select>
      </label>
      <label>
        {t("customers.currency")}
        <select value={values.currency} onChange={(e) => set("currency")(e.target.value)}>
          <option value="">—</option>
          {currencies.data?.map((c) => (
            <option key={c.code} value={c.code}>
              {c.code} – {c.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("quotations.validUntil")}
        <input type="date" value={values.valid_until} placeholder={t("quotations.sevenDays")} onChange={(e) => set("valid_until")(e.target.value)} />
      </label>
      <label>
        {t("quotations.enquiryRef")}
        <input value={values.enquiry_ref} maxLength={100} onChange={(e) => set("enquiry_ref")(e.target.value)} />
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
      <label className="wide">
        {t("customers.field.notes")}
        <textarea rows={2} value={values.notes} onChange={(e) => set("notes")(e.target.value)} />
      </label>

      <div className="wide">
        <h2>{t("quotations.lines")}</h2>
        {lines.map((l, index) => {
          const n = String(index + 1);
          return (
            <fieldset key={index} className="quote-line">
              <legend>{t("quotations.lineN", { n })}</legend>
              <label className="wide">
                {t("quotations.description")}
                <textarea
                  rows={2}
                  aria-label={t("quotations.descriptionOf", { n })}
                  value={l.description}
                  required
                  onChange={(e) => setLine(index, { description: e.target.value })}
                />
              </label>
              <div className="form-grid">
                <label>
                  {t("quotations.drawingNo")}
                  <input aria-label={t("quotations.drawingNoOf", { n })} value={l.drawing_no} maxLength={50} onChange={(e) => setLine(index, { drawing_no: e.target.value })} />
                </label>
                <label>
                  {t("quotations.drawingRev")}
                  <input aria-label={t("quotations.drawingRevOf", { n })} value={l.drawing_rev} maxLength={20} onChange={(e) => setLine(index, { drawing_rev: e.target.value })} />
                </label>
                <label>
                  {t("quotations.quantity")}
                  <input
                    inputMode="decimal"
                    className="num"
                    aria-label={t("quotations.quantityOf", { n })}
                    value={l.quantity}
                    required
                    onChange={(e) => setLine(index, { quantity: e.target.value })}
                  />
                </label>
                <label>
                  {t("quotations.unit")}
                  <input aria-label={t("quotations.unitOf", { n })} value={l.unit} maxLength={20} onChange={(e) => setLine(index, { unit: e.target.value })} />
                </label>
                <label>
                  {t("quotations.unitPrice")}
                  <input
                    inputMode="decimal"
                    className="num"
                    aria-label={t("quotations.unitPriceOf", { n })}
                    value={l.unit_price}
                    required
                    onChange={(e) => setLine(index, { unit_price: e.target.value })}
                  />
                </label>
                <label>
                  {t("quotations.moq")}
                  <input
                    inputMode="decimal"
                    className="num"
                    aria-label={t("quotations.moqOf", { n })}
                    value={l.min_order_qty ?? ""}
                    onChange={(e) => setLine(index, { min_order_qty: e.target.value })}
                  />
                </label>
                <label>
                  <input
                    type="checkbox"
                    aria-label={t("quotations.toolingOf", { n })}
                    checked={l.is_tooling ?? false}
                    onChange={(e) => setLine(index, { is_tooling: e.target.checked })}
                  />{" "}
                  {t("quotations.tooling")}
                </label>
                <label>
                  {t("vouchers.taxCode")}
                  <select aria-label={t("quotations.taxCodeOf", { n })} value={l.tax_code ?? ""} onChange={(e) => setLine(index, { tax_code: e.target.value || null })}>
                    <option value="">{t("quotations.noTax")}</option>
                    {salesCodes.map((c) => (
                      <option key={c.code} value={c.code}>
                        {c.code} – {c.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div role="group" aria-label={t("quotations.breaksOf", { n })}>
                <p className="muted">{t("quotations.breaksHelp")}</p>
                {l.breaks.map((b, row) => (
                  <div key={row} className="inline-form">
                    <label>
                      {t("quotations.breakQuantity")}
                      <input
                        inputMode="decimal"
                        className="num"
                        value={b.quantity}
                        onChange={(e) => setLine(index, { breaks: l.breaks.map((x, r) => (r === row ? { ...x, quantity: e.target.value } : x)) })}
                      />
                    </label>
                    <label>
                      {t("quotations.unitPrice")}
                      <input
                        inputMode="decimal"
                        className="num"
                        value={b.unit_price}
                        onChange={(e) => setLine(index, { breaks: l.breaks.map((x, r) => (r === row ? { ...x, unit_price: e.target.value } : x)) })}
                      />
                    </label>
                    <button type="button" className="small secondary" onClick={() => setLine(index, { breaks: l.breaks.filter((_, r) => r !== row) })}>
                      {t("vouchers.removeLine")}
                    </button>
                  </div>
                ))}
                <button type="button" className="small secondary" onClick={() => setLine(index, { breaks: [...l.breaks, { quantity: "", unit_price: "" }] })}>
                  {t("quotations.addBreak")}
                </button>
              </div>
              {lines.length > 1 && (
                <button type="button" className="small secondary" onClick={() => setLines((now) => now.filter((_, i) => i !== index))}>
                  {t("quotations.removeLine")}
                </button>
              )}
            </fieldset>
          );
        })}
        <button type="button" className="secondary" onClick={() => setLines((now) => [...now, emptyLine()])}>
          {t("quotations.addLine")}
        </button>
      </div>

      {quotation && <Totals quotation={quotation} />}
      <div className="wide">
        <p className="muted">{t("quotations.worksOut")}</p>
        <button type="submit" disabled={save.isPending}>
          {t("vouchers.saveDraft")}
        </button>
      </div>
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function Totals({ quotation }: { quotation: QuotationDetail }) {
  const { t } = useTranslation();
  return (
    <div className="wide">
      <p>
        {t("quotations.subtotal")}: <strong>{quotation.currency} {formatDecimal(quotation.subtotal)}</strong> · {t("vouchers.tax")}:{" "}
        <strong>{formatDecimal(quotation.tax_total)}</strong> · {t("vouchers.total")}:{" "}
        <strong>
          {quotation.currency} {formatDecimal(quotation.total_amount)}
        </strong>
      </p>
      {quotation.currency !== "LKR" && (
        <p className="muted">
          {t("quotations.rateUsed", {
            currency: quotation.currency,
            rate: quotation.exchange_rate,
            date: quotation.rate_date ?? quotation.quote_date,
            lkr: formatDecimal(quotation.total_lkr),
          })}
        </p>
      )}
    </div>
  );
}

function ReadOnly({ quotation }: { quotation: QuotationDetail }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("quotations.details")}>
      <p>
        {quotation.customer.code} {quotation.customer.name}
        {quotation.contact && ` · ${quotation.contact.name}`}
        {quotation.enquiry_ref && ` · ${t("quotations.enquiryRef")} ${quotation.enquiry_ref}`}
      </p>
      <p className="muted">
        {t("quotations.validUntil")} {quotation.valid_until} · {quotation.payment_terms}
        {quotation.incoterm && ` · ${quotation.incoterm}`}
        {quotation.delivery_lead_time && ` · ${quotation.delivery_lead_time}`}
      </p>
      <div className="table-wrap">
        <table aria-label={t("quotations.lines")}>
          <thead>
            <tr>
              <th>#</th>
              <th>{t("quotations.description")}</th>
              <th>{t("quotations.drawingNo")}</th>
              <th className="num">{t("quotations.quantity")}</th>
              <th className="num">{t("quotations.unitPrice")}</th>
              <th className="num">{t("vouchers.tax")}</th>
              <th className="num">{t("vouchers.total")}</th>
            </tr>
          </thead>
          <tbody>
            {quotation.lines.map((l) => (
              <tr key={l.line_no}>
                <td>{l.line_no}</td>
                <td>
                  {l.description}
                  {l.is_tooling && <span className="muted"> ({t("quotations.toolingShort")})</span>}
                  {l.breaks.length > 0 && (
                    <div className="muted">
                      {l.breaks.map((b) => `${formatQuantity(b.quantity)} @ ${formatDecimal(b.unit_price)}`).join(" · ")}
                    </div>
                  )}
                </td>
                <td>
                  {l.drawing_no}
                  {l.drawing_rev && ` rev ${l.drawing_rev}`}
                </td>
                <td className="num">
                  {formatQuantity(l.quantity)} {l.unit}
                </td>
                <td className="num">{formatDecimal(l.unit_price)}</td>
                <td className="num">{formatDecimal(l.tax_amount)}</td>
                <td className="num">{formatDecimal(l.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Totals quotation={quotation} />
      {quotation.notes && <p>{quotation.notes}</p>}
    </section>
  );
}

function Files({ quotation }: { quotation: QuotationDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [lineNo, setLineNo] = useState(quotation.lines.length === 1 ? "1" : "");
  const [warnings, setWarnings] = useState<string[]>([]);
  const refresh = (latest: QuotationDetail) => {
    queryClient.setQueryData([...quotationsKey, "one", String(quotation.id)], latest);
    setWarnings(latest.upload_warnings ?? []);
  };
  const upload = useMutation({
    mutationFn: (file: File) => uploadQuotationFile(quotation.id, file, lineNo ? Number(lineNo) : null),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: (fileId: number) => removeQuotationFile(quotation.id, fileId), onSuccess: refresh });

  return (
    <section className="panel" aria-label={t("quotations.files")}>
      <h2>{t("quotations.files")}</h2>
      {quotation.files.length === 0 && <p className="muted">{t("quotations.noFiles")}</p>}
      <ul className="changes">
        {quotation.files.map((f) => (
          <li key={f.id}>
            <a href={quotationFileUrl(quotation.id, f.id)} target="_blank" rel="noreferrer">
              {f.file_name}
            </a>{" "}
            <span className="muted">{f.line_no ? t("quotations.forLine", { n: String(f.line_no) }) : t("quotations.forQuotation")}</span>{" "}
            {quotation.can_edit && (
              <button type="button" className="small secondary" onClick={() => remove.mutate(f.id)}>
                {t("vouchers.removeFile")}
              </button>
            )}
          </li>
        ))}
      </ul>
      {quotation.can_edit && (
        <div className="inline-form">
          <label>
            {t("quotations.fileFor")}
            <select value={lineNo} onChange={(e) => setLineNo(e.target.value)}>
              <option value="">{t("quotations.forQuotation")}</option>
              {quotation.lines.map((l) => (
                <option key={l.line_no} value={l.line_no}>
                  {t("quotations.forLine", { n: String(l.line_no) })}
                  {l.drawing_no && ` (${l.drawing_no})`}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("vouchers.chooseFiles")}
            <input
              type="file"
              accept="application/pdf,image/jpeg,image/png"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) upload.mutate(file);
                e.target.value = "";
              }}
            />
          </label>
          {upload.isPending && <span role="status">{t("vouchers.uploading")}</span>}
        </div>
      )}
      {warnings.map((w) => (
        <p key={w} className="notice" role="status">
          ⚠ {w}
        </p>
      ))}
      <ErrorLine error={upload.error ?? remove.error} />
    </section>
  );
}
