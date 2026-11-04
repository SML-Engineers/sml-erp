import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { ApiError } from "../api/client";
import type { EmailDraft } from "../api/documentEmail";
import {
  addCardLink,
  deleteInvoice,
  getInvoice,
  getInvoiceEmail,
  invoicePdfUrl,
  invoicesKey,
  issueInvoice,
  sendInvoiceEmail,
  updateInvoice,
  type InvoiceDetail,
} from "../api/taxInvoices";
import SendEmailForm from "../components/SendEmailForm";
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

/** One tax invoice (P2-05): the draft's dates and terms, its lines and taxes, issuing by the
 * Accountant, the PDF in the Inland Revenue's layout and the email to the customer. */
export default function TaxInvoicePage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const invoice = useQuery({ queryKey: [...invoicesKey, "one", id], queryFn: () => getInvoice(Number(id)) });
  const data = invoice.data;

  return (
    <main className="page">
      <p>
        <Link to="/tax-invoices">{t("ti.backToList")}</Link>
      </p>
      <h1>{data ? (data.number ? `${t("ti.one")} ${data.number}` : t("ti.draftNo", { id: data.id })) : t("ti.one")}</h1>
      {data && (
        <>
          <p className="muted">
            {t(`ti.statuses.${data.status}`)} · {data.customer.name} ·{" "}
            {data.order ? <Link to={`/sales-orders/${data.order.id}`}>{data.order.number}</Link> : t("ti.fromQuickBooks")}
            {data.journal_entry && (
              <>
                {" · "}
                {t("mj.postedAs")}{" "}
                <Link to={`/journal?entry=${data.journal_entry.id}&q=${encodeURIComponent(data.journal_entry.number)}`} className="mono">
                  {data.journal_entry.number}
                </Link>
              </>
            )}
          </p>
          {data.status === "draft" && <p className="notice">{t("ti.draftNotice")}</p>}
          {data.can_edit ? <HeaderForm key={`${data.id}-${data.total_amount}-${data.invoice_date}`} invoice={data} /> : <Header invoice={data} />}
          <Lines invoice={data} />
          <Actions invoice={data} />
          <CreditNotes invoice={data} />
          <Payments invoice={data} />
          {data.tracking && <Tracking invoice={data} />}
        </>
      )}
      <ErrorLine error={invoice.error} />
    </main>
  );
}

function useDone() {
  const queryClient = useQueryClient();
  return (latest: InvoiceDetail) => {
    queryClient.setQueryData([...invoicesKey, "one", String(latest.id)], latest);
    void queryClient.invalidateQueries({ queryKey: [...invoicesKey, "list"] });
  };
}

function HeaderForm({ invoice }: { invoice: InvoiceDetail }) {
  const { t } = useTranslation();
  const done = useDone();
  const [values, setValues] = useState({
    invoice_date: invoice.invoice_date,
    supply_date: invoice.supply_date,
    place_of_supply: invoice.place_of_supply,
    terms: invoice.terms,
    notes: invoice.notes,
  });
  const save = useMutation({ mutationFn: () => updateInvoice(invoice.id, values), onSuccess: done });
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return (
    <form className="panel form-grid" aria-label={t("ti.form")} onSubmit={submit}>
      <label>
        {t("ti.invoiceDate")}
        <input type="date" value={values.invoice_date} required onChange={(e) => setValues({ ...values, invoice_date: e.target.value })} />
      </label>
      <label>
        {t("ti.supplyDate")}
        <input type="date" value={values.supply_date} required onChange={(e) => setValues({ ...values, supply_date: e.target.value })} />
      </label>
      <label className="wide">
        {t("ti.placeOfSupply")}
        <input value={values.place_of_supply} maxLength={200} onChange={(e) => setValues({ ...values, place_of_supply: e.target.value })} />
      </label>
      <label className="wide">
        {t("ti.terms")}
        <input value={values.terms} maxLength={200} onChange={(e) => setValues({ ...values, terms: e.target.value })} />
      </label>
      <label className="wide">
        {t("ti.notes")}
        <input value={values.notes} maxLength={2000} onChange={(e) => setValues({ ...values, notes: e.target.value })} />
      </label>
      <p className="wide muted">
        {t("ti.customerTin")}: {invoice.customer_tin || "–"} · {t("ti.dueDate")}: {invoice.due_date}
      </p>
      <div className="wide">
        <button type="submit" disabled={save.isPending}>
          {t("vouchers.saveDraft")}
        </button>
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function Header({ invoice }: { invoice: InvoiceDetail }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("ti.form")}>
      <dl className="details">
        <dt>{t("ti.invoiceDate")}</dt>
        <dd>{invoice.invoice_date}</dd>
        <dt>{t("ti.supplyDate")}</dt>
        <dd>{invoice.supply_date}</dd>
        <dt>{t("ti.placeOfSupply")}</dt>
        <dd>{invoice.place_of_supply || "–"}</dd>
        <dt>{t("ti.terms")}</dt>
        <dd>{invoice.terms || "–"}</dd>
        <dt>{t("ti.dueDate")}</dt>
        <dd>{invoice.due_date}</dd>
        <dt>{t("ti.customerTin")}</dt>
        <dd>{invoice.customer_tin || "–"}</dd>
        {invoice.issued_by && (
          <>
            <dt>{t("ti.issuedBy")}</dt>
            <dd>{invoice.issued_by}</dd>
          </>
        )}
      </dl>
      {invoice.notes && <p>{invoice.notes}</p>}
    </section>
  );
}

function Lines({ invoice }: { invoice: InvoiceDetail }) {
  const { t } = useTranslation();
  const before = invoice.taxes.filter((x) => !x.on_tax);
  const after = invoice.taxes.filter((x) => x.on_tax);
  return (
    <section className="panel" aria-label={t("ti.lines")}>
      <div className="table-wrap">
        <table aria-label={t("ti.lines")}>
          <thead>
            <tr>
              <th>{t("ti.productCode")}</th>
              <th>{t("quotations.description")}</th>
              <th>{t("ti.deliveryNote")}</th>
              <th className="num">{t("ti.rate")}</th>
              <th className="num">{t("ti.qty")}</th>
              <th className="num">{t("ti.amount")}</th>
            </tr>
          </thead>
          <tbody>
            {invoice.lines.map((l) => (
              <tr key={l.line_no}>
                <td>{l.product_code}</td>
                <td>
                  {l.description}
                  <div className="muted">
                    {l.tax_code ?? t("ti.noTax")} · {l.account.number} {l.account.name}
                  </div>
                </td>
                <td>
                  <Link to={`/delivery-notes/${l.delivery_note.id}`}>{l.delivery_note.number}</Link>
                </td>
                <td className="num">{formatDecimal(l.rate)}</td>
                <td className="num">
                  {formatQuantity(l.quantity)} {l.unit === "pcs" ? "" : l.unit}
                </td>
                <td className="num">{formatDecimal(l.amount)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={5}>{t("ti.subtotal")}</th>
              <th className="num">{formatDecimal(invoice.subtotal)}</th>
            </tr>
            {invoice.discount_total !== "0.00" && (
              <tr>
                <td colSpan={5}>{t("ti.discount")}</td>
                <td className="num">-{formatDecimal(invoice.discount_total)}</td>
              </tr>
            )}
            {before.map((x) => (
              <tr key={`b-${x.label}-${x.rate}`}>
                <td colSpan={5}>
                  {x.label} {x.rate}%
                </td>
                <td className="num">{formatDecimal(x.amount)}</td>
              </tr>
            ))}
            {after.map((x) => (
              <tr key={`a-${x.label}-${x.rate}`}>
                <td colSpan={5}>
                  {x.label} {x.rate}%
                </td>
                <td className="num">{formatDecimal(x.amount)}</td>
              </tr>
            ))}
            <tr>
              <th colSpan={5}>
                {t("ti.totalWithVat")}
                {invoice.currency && invoice.currency !== "LKR" ? ` (${invoice.currency})` : ""}
              </th>
              <th className="num">{formatDecimal(invoice.total_amount)}</th>
            </tr>
          </tfoot>
        </table>
      </div>
      {invoice.amount_in_words && <p className="muted">{invoice.amount_in_words}</p>}
      {invoice.currency && invoice.currency !== "LKR" && invoice.total_lkr && (
        <p className="muted">
          {t("ti.inLkr", {
            currency: invoice.currency,
            rate: invoice.exchange_rate ?? "",
            date: invoice.rate_date ?? "",
            amount: formatDecimal(invoice.total_lkr),
          })}
        </p>
      )}
    </section>
  );
}

function Actions({ invoice }: { invoice: InvoiceDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const done = useDone();
  const [email, setEmail] = useState<EmailDraft | null>(null);
  const issue = useMutation({ mutationFn: () => issueInvoice(invoice.id), onSuccess: done });
  const remove = useMutation({
    mutationFn: () => deleteInvoice(invoice.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: invoicesKey });
      navigate("/tax-invoices");
    },
  });
  const load = useMutation({ mutationFn: () => getInvoiceEmail(invoice.id), onSuccess: setEmail });

  return (
    <section className="panel" aria-label={t("ti.actions")}>
      {invoice.opening ? (
        <p className="muted">{t("ti.openingNote")}</p>
      ) : (
        <p>
          <a className="button-link secondary" href={invoicePdfUrl(invoice.id)} target="_blank" rel="noreferrer">
            {invoice.status === "draft" ? t("ti.preview") : t("ti.pdf")}
          </a>
        </p>
      )}
      {invoice.can_issue && (
        <p>
          <button type="button" disabled={issue.isPending} onClick={() => issue.mutate()}>
            {t("ti.issue")}
          </button>{" "}
          <span className="muted">{t("ti.issueHelp")}</span>
        </p>
      )}
      {invoice.status === "draft" && !invoice.can_issue && <p className="muted">{t("ti.accountantIssues")}</p>}
      {invoice.can_edit && (
        <p>
          <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {t("ti.delete")}
          </button>
        </p>
      )}
      {invoice.can_email && !email && (
        <button type="button" disabled={load.isPending} onClick={() => load.mutate()}>
          {t("quotations.emailToCustomer")}
        </button>
      )}
      {email && (
        <SendEmailForm
          draft={email}
          attachmentName={`Tax-invoice-${invoice.number}.pdf`}
          onSend={async (message) => done(await sendInvoiceEmail(invoice.id, message))}
          onCancel={() => setEmail(null)}
        />
      )}
      {invoice.emails.length > 0 && (
        <ul className="changes" aria-label={t("ti.emails")}>
          {invoice.emails.map((m, i) => (
            <li key={i}>
              {m.sent_at.slice(0, 16).replace("T", " ")} · {m.to} · {m.status === "sent" ? t("ti.emailSent") : `${t("ti.emailFailed")}: ${m.error}`}
            </li>
          ))}
        </ul>
      )}
      <ErrorLine error={issue.error ?? remove.error ?? load.error} />
    </section>
  );
}

/** Where the invoice stands and what happened to it (P2-27): emailed, viewed by the customer
 * through its link, OnePay card links sent, payments and deposits. */
function Tracking({ invoice }: { invoice: InvoiceDetail }) {
  const { t } = useTranslation();
  const done = useDone();
  const today = new Date().toLocaleDateString("en-CA");
  const [form, setForm] = useState({ url: "", amount: "", sent_on: today, note: "" });
  const [open, setOpen] = useState(false);
  const save = useMutation({
    mutationFn: () => addCardLink(invoice.id, form),
    onSuccess: (got) => {
      done(got);
      setOpen(false);
      setForm({ url: "", amount: "", sent_on: today, note: "" });
    },
  });
  const tr = invoice.tracking!;
  return (
    <section className="panel" aria-label={t("ti.tracking")}>
      <h2>
        {t("ti.tracking")} · <span className={tr.state === "overdue" ? "danger-text" : undefined}>{t(`ti.states.${tr.state}`)}</span>
      </h2>
      <p className="muted">{tr.viewed ? t("ti.viewedYes") : t("ti.viewedNo")}</p>
      <ol aria-label={t("ti.history")}>
        {tr.events.map((e, i) => (
          <li key={i}>
            {e.at.slice(0, 10)} · {e.text}
            {e.url && (
              <>
                {" · "}
                <a href={e.url} target="_blank" rel="noreferrer">
                  {t("ti.link")}
                </a>
              </>
            )}
          </li>
        ))}
      </ol>
      {invoice.can_email && !open && tr.state !== "paid" && (
        <button type="button" className="secondary" onClick={() => setOpen(true)}>
          {t("ti.recordCardLink")}
        </button>
      )}
      {open && (
        <div className="form-grid" role="form" aria-label={t("ti.recordCardLink")}>
          <p className="muted wide">{t("ti.cardLinkHelp")}</p>
          <label className="wide">
            {t("ti.cardLinkUrl")}
            <input inputMode="url" placeholder="https://" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
          </label>
          <label>
            {t("ti.cardLinkAmount", { currency: invoice.currency })}
            <input inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          </label>
          <label>
            {t("ti.cardLinkSent")}
            <input type="date" value={form.sent_on} onChange={(e) => setForm({ ...form, sent_on: e.target.value })} />
          </label>
          <label className="wide">
            {t("ti.cardLinkNote")}
            <input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          </label>
          <div className="wide">
            <button type="button" disabled={save.isPending} onClick={() => save.mutate()}>
              {t("ti.save")}
            </button>{" "}
            <button type="button" className="secondary" onClick={() => setOpen(false)}>
              {t("quotations.cancel")}
            </button>
          </div>
        </div>
      )}
      <ErrorLine error={save.error} />
    </section>
  );
}

/** Credit notes against the invoice (P2-06), and a link to make one. */
function CreditNotes({ invoice }: { invoice: InvoiceDetail }) {
  const { t } = useTranslation();
  const notes = invoice.credit_notes ?? [];
  if (notes.length === 0 && !invoice.can_credit) return null;
  return (
    <section className="panel" aria-label={t("cn.title")}>
      <h2>{t("cn.title")}</h2>
      {notes.length > 0 && (
        <ul>
          {notes.map((n) => (
            <li key={n.id}>
              <Link to={`/credit-notes/${n.id}`} className="mono">
                {n.number || t("cn.draftNo", { id: n.id })}
              </Link>{" "}
              · {n.credit_date} · {formatDecimal(n.total_amount)} · {t(`cn.statuses.${n.status}`)}
            </li>
          ))}
        </ul>
      )}
      {invoice.can_credit && (
        <Link className="button-link" to={`/credit-notes/new?invoice=${invoice.id}`}>
          {t("cn.new")}
        </Link>
      )}
    </section>
  );
}

/** What has been paid on an issued invoice (P2-07): receipts, advances set off, and what is
 * still open. */
function Payments({ invoice }: { invoice: InvoiceDetail }) {
  const { t } = useTranslation();
  const figures = invoice.settlement;
  if (!figures) return null;
  const receipts = invoice.receipts ?? [];
  const setOffs = invoice.set_offs ?? [];
  return (
    <section className="panel" aria-label={t("receipts.paid")}>
      <h2>{t("receipts.paid")}</h2>
      <dl className="details">
        <dt>{t("receipts.total")}</dt>
        <dd>{formatDecimal(figures.total)}</dd>
        {figures.credited !== "0.00" && (
          <>
            <dt>{t("cn.title")}</dt>
            <dd>{formatDecimal(figures.credited)}</dd>
          </>
        )}
        <dt>{t("receipts.received")}</dt>
        <dd>{formatDecimal(figures.received)}</dd>
        {figures.pending !== "0.00" && (
          <>
            <dt>{t("receipts.pending")}</dt>
            <dd>{formatDecimal(figures.pending)}</dd>
          </>
        )}
        {figures.set_off !== "0.00" && (
          <>
            <dt>{t("receipts.advancesSetOff")}</dt>
            <dd>{formatDecimal(figures.set_off)}</dd>
          </>
        )}
        <dt>
          <strong>{t("receipts.open")}</strong>
        </dt>
        <dd>
          <strong>{formatDecimal(figures.open)}</strong>
        </dd>
      </dl>
      {(receipts.length > 0 || setOffs.length > 0) && (
        <ul>
          {receipts.map((r) => (
            <li key={`r${r.id}`}>
              <Link to={`/receipts/${r.id}`} className="mono">
                {r.number}
              </Link>{" "}
              · {r.receipt_date} · {formatDecimal(r.amount)} · {t(`receipts.statuses.${r.status}`)}
            </li>
          ))}
          {setOffs.map((s, i) => (
            <li key={`s${i}`}>
              <Link to={`/advances/${s.advance.id}`} className="mono">
                {s.advance.number}
              </Link>{" "}
              · {s.set_off_date} · {formatDecimal(s.amount)} · {t("receipts.advanceSetOff")}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
