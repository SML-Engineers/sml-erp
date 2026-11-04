import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { listDivisions } from "../api/admin";
import { ApiError } from "../api/client";
import { INCOTERMS, listContacts, listCustomers, listPickerCurrencies, type Customer } from "../api/customers";
import {
  approveQuotation,
  createQuotation,
  getQuotation,
  markQuotationSent,
  getQuotationEmail,
  OUTCOME_REASONS,
  quotationPdfUrl,
  sendQuotationEmail,
  recordOutcome,
  returnQuotation,
  reviseQuotation,
  submitQuotation,
  quotationFileUrl,
  quotationsKey,
  removeQuotationFile,
  updateQuotation,
  uploadQuotationFile,
  uploadQuotationImage,
  removeQuotationImage,
  quotationImageUrl,
  MAX_QUOTATION_IMAGES,
  MAX_QUOTATION_IMAGE_BYTES,
  type LineInput,
  type QuotationDetail,
} from "../api/quotations";
import { createProforma } from "../api/proformas";
import { orderFromQuotation } from "../api/salesOrders";
import { getTaxes, taxesKey } from "../api/taxes";
import OrderLinks from "../components/OrderLinks";
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
      {data && (
        <p>
          <a className="button-link secondary" href={quotationPdfUrl(data.id)} target="_blank" rel="noreferrer">
            {t("quotations.printPdf")}
          </a>{" "}
          {!data.is_final && <span className="muted">{t("quotations.printsAsDraft")}</span>}
        </p>
      )}
      {data && (data.can_email || data.emails.length > 0) && <EmailPanel key={`email-${data.id}`} quotation={data} />}
      {data && (data.can_make_proforma || data.proformas.length > 0) && <ProformaLinks quotation={data} />}
      {data && (data.can_make_sales_order || data.sales_orders.length > 0) && (
        <OrderLinks orders={data.sales_orders} canMake={data.can_make_sales_order} make={() => orderFromQuotation(data.id)} />
      )}
      {data?.can_see_costing && (
        <p>
          <Link className="button-link" to={`/quotations/${data.id}/costing`}>
            {t("quoteCosting.open")}
          </Link>{" "}
          <span className="muted">{t("quoteCosting.internalOnly")}</span>
        </p>
      )}
      {data && (data.can_edit || (data.images ?? []).length > 0) && <Pictures quotation={data} />}
      {data && <Workflow key={`${data.id}-${data.status}`} quotation={data} />}
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
    discount_pct: quotation && Number(quotation.discount_pct) !== 0 ? quotation.discount_pct : "",
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
        discount_pct: values.discount_pct.trim(),
        lines: lines.map((l) => ({ ...l, min_order_qty: l.min_order_qty?.trim() ? l.min_order_qty : null })),
      };
      return quotation ? updateQuotation(quotation.id, input) : createQuotation(input);
    },
    onSuccess: (saved) => {
      queryClient.setQueryData([...quotationsKey, "one", String(saved.id)], saved);
      // The answer is the quotation as saved; only the lists need fetching again.
      void queryClient.invalidateQueries({ queryKey: [...quotationsKey, "list"] });
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
      <label>
        {t("quotations.discountPct")}
        <input inputMode="decimal" className="num" value={values.discount_pct} placeholder="0" onChange={(e) => set("discount_pct")(e.target.value)} />
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
      {Number(quotation.discount_total) !== 0 && (
        <p>
          {t("quotations.discountLine", { pct: quotation.discount_pct })}: <strong>−{formatDecimal(quotation.discount_total)}</strong>
        </p>
      )}
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

/** Product pictures for the customer (owner's request, 4 Nov 2026): up to three JPG or PNG
 * of at most 1 MB, added while the quotation is a draft, seen by the approver and emailed. */
function Pictures({ quotation }: { quotation: QuotationDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [tooBig, setTooBig] = useState("");
  const images = quotation.images ?? [];
  const refresh = (latest: QuotationDetail) => queryClient.setQueryData([...quotationsKey, "one", String(quotation.id)], latest);
  const upload = useMutation({ mutationFn: (file: File) => uploadQuotationImage(quotation.id, file), onSuccess: refresh });
  const remove = useMutation({ mutationFn: (imageId: number) => removeQuotationImage(quotation.id, imageId), onSuccess: refresh });
  return (
    <section className="panel" aria-label={t("quotations.pictures")}>
      <h2>{t("quotations.pictures")}</h2>
      <p className="muted">{t("quotations.picturesHelp")}</p>
      <div className="picture-row">
        {images.map((i) => (
          <figure key={i.id} className="picture">
            <a href={quotationImageUrl(quotation.id, i.id)} target="_blank" rel="noreferrer">
              <img src={quotationImageUrl(quotation.id, i.id)} alt={i.file_name} style={{ maxWidth: 220, maxHeight: 220, objectFit: "contain" }} />
            </a>
            <figcaption>
              {i.file_name}{" "}
              {quotation.can_edit && (
                <button type="button" className="small secondary" onClick={() => remove.mutate(i.id)}>
                  {t("vouchers.removeFile")}
                </button>
              )}
            </figcaption>
          </figure>
        ))}
      </div>
      {quotation.can_edit && images.length < MAX_QUOTATION_IMAGES && (
        <label>
          {t("quotations.addPicture")}
          <input
            type="file"
            accept="image/jpeg,image/png"
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (!file) return;
              if (file.size > MAX_QUOTATION_IMAGE_BYTES) {
                setTooBig(t("quotations.pictureTooBig", { name: file.name }));
                return;
              }
              setTooBig("");
              upload.mutate(file);
            }}
          />
        </label>
      )}
      {upload.isPending && <span role="status">{t("vouchers.uploading")}</span>}
      {tooBig && (
        <p className="form-error" role="alert">
          {tooBig}
        </p>
      )}
      <ErrorLine error={upload.error ?? remove.error} />
    </section>
  );
}

/** Approval by the Director, sending, the outcome and revisions (spec 5.1; P15-06). */
function Workflow({ quotation }: { quotation: QuotationDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [comment, setComment] = useState("");
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState<"accepted" | "lost">("accepted");
  const [outcomeReason, setOutcomeReason] = useState("");
  const [note, setNote] = useState("");
  const done = (latest: QuotationDetail) => {
    queryClient.setQueryData([...quotationsKey, "one", String(latest.id)], latest);
    // The answer is the quotation as it now is; only the lists need fetching again.
    void queryClient.invalidateQueries({ queryKey: [...quotationsKey, "list"] });
    if (latest.id !== quotation.id) {
      void queryClient.invalidateQueries({ queryKey: [...quotationsKey, "one", String(quotation.id)] });
      navigate(`/quotations/${latest.id}`);
    }
  };
  const act = useMutation({ mutationFn: (call: () => Promise<QuotationDetail>) => call(), onSuccess: done });
  const id = quotation.id;
  const review = quotation.review;
  const history = quotation.approval?.history ?? [];

  return (
    <section className="panel" aria-label={t("quotations.approval")}>
      <h2>{t("quotations.approval")}</h2>
      {quotation.approval?.waiting_with && (
        <p className="notice">{t("quotations.waitingWith", { role: quotation.approval.waiting_with })}</p>
      )}
      {!quotation.is_final && quotation.status !== "revised" && <p className="muted">{t("quotations.notApprovedYet")}</p>}
      {quotation.outcome && (
        <p>
          <strong>{t(`quotations.statuses.${quotation.status}`)}</strong>
          {quotation.outcome.reason_label && ` · ${quotation.outcome.reason_label}`}
          {quotation.outcome.note && ` · ${quotation.outcome.note}`} <span className="muted">({quotation.outcome.by})</span>
        </p>
      )}

      {review && (
        <div aria-label={t("quotations.reviewLabel")} role="group">
          <p>
            {t("quotations.overallMargin")}: <strong>{review.margin_pct === null ? "—" : `${review.margin_pct}%`}</strong>
            {review.min_margin_pct && <span className="muted"> ({t("quotations.minimum", { pct: review.min_margin_pct })})</span>} ·{" "}
            {t("quotations.valueLkr")}: <strong>{formatDecimal(review.value_lkr)}</strong>
          </p>
          {review.warnings.length > 0 && (
            <ul className="changes" aria-label={t("quotations.warnings")}>
              {review.warnings.map((w) => (
                <li key={w}>⚠ {w}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {quotation.can_submit && (
        <div className="inline-form">
          <label>
            {t("quotations.commentForDirector")}
            <input value={comment} maxLength={500} onChange={(e) => setComment(e.target.value)} />
          </label>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => submitQuotation(id, comment))}>
            {t("quotations.sendForApproval")}
          </button>
          <span className="muted">{t("quotations.saveFirst")}</span>
        </div>
      )}

      {quotation.can_approve && (
        <div className="inline-form">
          <label>
            {t("quotations.approverNote")}
            <input value={comment} maxLength={500} onChange={(e) => setComment(e.target.value)} />
          </label>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => approveQuotation(id, comment))}>
            {t("quotations.approve")}
          </button>
          <label>
            {t("quotations.returnReason")}
            <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => returnQuotation(id, reason))}>
            {t("quotations.returnToCreator")}
          </button>
        </div>
      )}

      {quotation.can_mark_sent && (
        <p>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => markQuotationSent(id))}>
            {t("quotations.markSent")}
          </button>
        </p>
      )}

      {quotation.can_record_outcome && (
        <div className="inline-form" role="group" aria-label={t("quotations.outcome")}>
          <label>
            {t("quotations.outcome")}
            <select value={outcome} onChange={(e) => setOutcome(e.target.value as "accepted" | "lost")}>
              <option value="accepted">{t("quotations.won")}</option>
              <option value="lost">{t("quotations.lost")}</option>
            </select>
          </label>
          <label>
            {t("quotations.why")}
            <select value={outcomeReason} onChange={(e) => setOutcomeReason(e.target.value)}>
              <option value="">—</option>
              {OUTCOME_REASONS.map((r) => (
                <option key={r} value={r}>
                  {t(`quotations.reasons.${r}`)}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t("quotations.note")}
            <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
          </label>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => recordOutcome(id, outcome, outcomeReason, note))}>
            {t("quotations.recordOutcome")}
          </button>
        </div>
      )}

      {quotation.can_revise && (
        <p>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => reviseQuotation(id))}>
            {t("quotations.revise")}
          </button>{" "}
          <span className="muted">{t("quotations.reviseHelp")}</span>
        </p>
      )}
      <ErrorLine error={act.error} />

      {history.length > 0 && (
        <ul className="changes" aria-label={t("quotations.approvalHistory")}>
          {history.map((h, i) => (
            <li key={i}>
              {h.action_label} · {h.by} · {h.at.slice(0, 16).replace("T", " ")}
              {h.reason && ` · ${h.reason}`}
            </li>
          ))}
        </ul>
      )}
      {quotation.revisions.length > 1 && (
        <p>
          {t("quotations.revisions")}:{" "}
          {quotation.revisions.map((r, i) => (
            <span key={r.id}>
              {i > 0 && " · "}
              {r.id === quotation.id ? (
                <strong>Rev {r.revision}</strong>
              ) : (
                <Link to={`/quotations/${r.id}`}>Rev {r.revision}</Link>
              )}{" "}
              <span className="muted">({t(`quotations.statuses.${r.status}`)})</span>
            </span>
          ))}
        </p>
      )}
    </section>
  );
}

/** Email the approved quotation to the customer with its PDF (spec 3B; P15-07). */
function EmailPanel({ quotation }: { quotation: QuotationDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState({ to: "", cc: "", subject: "", body: "" });
  const [from, setFrom] = useState("");
  const [pictures, setPictures] = useState<string[]>([]);
  const [withPictures, setWithPictures] = useState(true);
  const load = useMutation({
    mutationFn: () => getQuotationEmail(quotation.id),
    onSuccess: (draft) => {
      setMessage({ to: draft.to.join(", "), cc: draft.cc.join(", "), subject: draft.subject, body: draft.body });
      setPictures(draft.images ?? []);
      setWithPictures(true);
      setFrom(draft.ready ? draft.from : "");
      setOpen(true);
    },
  });
  const split = (value: string) =>
    value
      .split(/[,;]/)
      .map((a) => a.trim())
      .filter(Boolean);
  const send = useMutation({
    mutationFn: () =>
      sendQuotationEmail(quotation.id, {
        to: split(message.to),
        cc: split(message.cc),
        subject: message.subject,
        body: message.body,
        ...(pictures.length > 0 ? { include_images: withPictures } : {}),
      }),
    onSuccess: (latest) => {
      queryClient.setQueryData([...quotationsKey, "one", String(latest.id)], latest);
      void queryClient.invalidateQueries({ queryKey: [...quotationsKey, "list"] });
      setOpen(false);
    },
  });
  const set = (field: keyof typeof message) => (value: string) => setMessage((now) => ({ ...now, [field]: value }));

  return (
    <section className="panel" aria-label={t("quotations.email")}>
      <h2>{t("quotations.email")}</h2>
      {quotation.can_email && !open && (
        <button type="button" disabled={load.isPending} onClick={() => load.mutate()}>
          {t("quotations.emailToCustomer")}
        </button>
      )}
      {open && (
        <form
          className="form-grid"
          aria-label={t("quotations.emailForm")}
          onSubmit={(e) => {
            e.preventDefault();
            send.mutate();
          }}
        >
          {from ? <p className="muted wide">{t("quotations.emailFrom", { from })}</p> : <p className="form-error wide">{t("quotations.emailNotReady")}</p>}
          <label className="wide">
            {t("quotations.emailTo")}
            <input value={message.to} required onChange={(e) => set("to")(e.target.value)} />
          </label>
          <label className="wide">
            {t("quotations.emailCc")}
            <input value={message.cc} onChange={(e) => set("cc")(e.target.value)} />
          </label>
          <label className="wide">
            {t("quotations.emailSubject")}
            <input value={message.subject} maxLength={200} required onChange={(e) => set("subject")(e.target.value)} />
          </label>
          <label className="wide">
            {t("quotations.emailBody")}
            <textarea rows={8} value={message.body} required onChange={(e) => set("body")(e.target.value)} />
          </label>
          <p className="muted wide">{t("quotations.emailAttachment")}</p>
          {pictures.length > 0 && (
            <label className="wide checkbox">
              <input type="checkbox" checked={withPictures} onChange={(e) => setWithPictures(e.target.checked)} />{" "}
              {t("quotations.attachPictures", { count: pictures.length, names: pictures.join(", ") })}
            </label>
          )}
          <div className="wide">
            <button type="submit" disabled={send.isPending || !from}>
              {t("quotations.sendEmail")}
            </button>{" "}
            <button type="button" className="secondary" onClick={() => setOpen(false)}>
              {t("quotations.cancel")}
            </button>
          </div>
        </form>
      )}
      <ErrorLine error={load.error ?? send.error} />
      {quotation.emails.length > 0 && (
        <ul className="changes" aria-label={t("quotations.emailsSent")}>
          {quotation.emails.map((m, i) => (
            <li key={i}>
              {m.status === "sent" ? "✓" : "✗"} {m.sent_at.slice(0, 16).replace("T", " ")} · {m.to} · {m.by}
              {m.error && ` · ${m.error}`}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Proformas made from this quotation, and making one from an accepted quotation (P15-08). */
function ProformaLinks({ quotation }: { quotation: QuotationDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const make = useMutation({ mutationFn: () => createProforma(quotation.id), onSuccess: (made) => navigate(`/proformas/${made.id}`) });
  return (
    <section className="panel" aria-label={t("proformas.title")}>
      <h2>{t("proformas.title")}</h2>
      {quotation.proformas.length > 0 && (
        <ul className="changes">
          {quotation.proformas.map((p) => (
            <li key={p.id}>
              <Link to={`/proformas/${p.id}`}>{p.number}</Link> <span className="muted">({t(`proformas.statuses.${p.status}`)})</span>
            </li>
          ))}
        </ul>
      )}
      {quotation.can_make_proforma && (
        <button type="button" disabled={make.isPending} onClick={() => make.mutate()}>
          {t("proformas.make")}
        </button>
      )}
      <ErrorLine error={make.error} />
    </section>
  );
}
