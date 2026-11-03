import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import {
  approveCreditNote,
  cnKey,
  CN_KINDS,
  createCreditNote,
  creditNotePdfUrl,
  deleteCreditNote,
  getCreditNote,
  invoiceForCredit,
  rejectCreditNote,
  returnCreditNote,
  submitCreditNote,
  updateCreditNote,
  type CNDetail,
  type CNInvoiceLine,
  type CNKind,
} from "../api/creditNotes";
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

const today = () => new Date().toLocaleDateString("en-CA");
const plain = (value: string | null) => (value ? formatQuantity(value).replace(/,/g, "") : "");

/** One credit note (P2-06): made from an issued invoice, approved by the Director or a person
 * given the right, then numbered and posted. */
export default function CreditNotePage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const [search] = useSearchParams();
  const isNew = id === "new";
  const invoiceId = Number(search.get("invoice"));
  const note = useQuery({ queryKey: [...cnKey, "one", id], queryFn: () => getCreditNote(Number(id)), enabled: !isNew });
  const invoice = useQuery({ queryKey: [...cnKey, "invoice", invoiceId], queryFn: () => invoiceForCredit(invoiceId), enabled: isNew && invoiceId > 0 });
  const data = note.data;

  return (
    <main className="page">
      <p>
        <Link to="/credit-notes">{t("cn.backToList")}</Link>
      </p>
      <h1>{isNew ? t("cn.new") : data ? (data.number ? `${t("cn.one")} ${data.number}` : t("cn.draftNo", { id: data.id })) : t("cn.one")}</h1>
      {isNew && invoice.data && (
        <>
          <p className="muted">
            {t("cn.against", { number: invoice.data.number, date: invoice.data.invoice_date })} · {invoice.data.customer}
          </p>
          <NoteForm invoiceId={invoice.data.id} lines={invoice.data.lines} />
        </>
      )}
      {data && (
        <>
          <p className="muted">
            {t(`cn.statuses.${data.status}`)} · {data.customer.name} · <Link to={`/tax-invoices/${data.invoice.id}`}>{data.invoice.number}</Link>
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
          {data.can_edit ? (
            <NoteForm key={`${data.id}-${data.total_amount}-${data.reason}`} note={data} lines={data.lines} />
          ) : (
            <ReadOnly note={data} />
          )}
          <Actions note={data} />
        </>
      )}
      <ErrorLine error={note.error ?? invoice.error} />
    </main>
  );
}

function NoteForm({ note, invoiceId, lines }: { note?: CNDetail; invoiceId?: number; lines: CNInvoiceLine[] }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [values, setValues] = useState({
    kind: note?.kind ?? ("price" as CNKind),
    reason: note?.reason ?? "",
    credit_date: note?.credit_date ?? today(),
  });
  const [amounts, setAmounts] = useState<Record<number, { amount: string; quantity: string }>>(
    Object.fromEntries(lines.map((l) => [l.id, { amount: l.credit_amount ?? "", quantity: plain(l.credit_quantity) === "0" ? "" : plain(l.credit_quantity) }])),
  );
  const save = useMutation({
    mutationFn: () => {
      const input = {
        ...values,
        invoice: invoiceId,
        lines: lines.map((l) => ({ invoice_line: l.id, amount: amounts[l.id]?.amount ?? "", quantity: amounts[l.id]?.quantity ?? "" })),
      };
      return note ? updateCreditNote(note.id, input) : createCreditNote(input);
    },
    onSuccess: (saved) => {
      queryClient.setQueryData([...cnKey, "one", String(saved.id)], saved);
      void queryClient.invalidateQueries({ queryKey: [...cnKey, "list"] });
      if (!note) navigate(`/credit-notes/${saved.id}`);
    },
  });
  const set = (lineId: number, change: Partial<{ amount: string; quantity: string }>) =>
    setAmounts((now) => ({ ...now, [lineId]: { ...(now[lineId] ?? { amount: "", quantity: "" }), ...change } }));

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("cn.form")} onSubmit={submit}>
      <label>
        {t("cn.kind")}
        <select value={values.kind} onChange={(e) => setValues({ ...values, kind: e.target.value as CNKind })}>
          {CN_KINDS.map((k) => (
            <option key={k} value={k}>
              {t(`cn.kinds.${k}`)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("vouchers.date")}
        <input type="date" value={values.credit_date} required onChange={(e) => setValues({ ...values, credit_date: e.target.value })} />
      </label>
      <label className="wide">
        {t("cn.reason")}
        <input value={values.reason} maxLength={1000} required onChange={(e) => setValues({ ...values, reason: e.target.value })} />
      </label>
      <div className="wide table-wrap">
        <table aria-label={t("cn.lines")}>
          <thead>
            <tr>
              <th>{t("ti.productCode")}</th>
              <th>{t("quotations.description")}</th>
              <th className="num">{t("cn.invoiced")}</th>
              <th className="num">{t("cn.left")}</th>
              <th className="num">{t("cn.qtyReturned")}</th>
              <th className="num">{t("cn.amount")}</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.id}>
                <td>{l.product_code}</td>
                <td>
                  {l.description}
                  <div className="muted">{l.tax_code ?? t("ti.noTax")}</div>
                </td>
                <td className="num">
                  {formatQuantity(l.quantity)} · {formatDecimal(l.net)}
                </td>
                <td className="num">
                  {formatQuantity(l.left_quantity)} · {formatDecimal(l.left_amount)}
                </td>
                <td className="num">
                  <input
                    inputMode="decimal"
                    className="num"
                    size={8}
                    aria-label={t("cn.qtyOf", { n: l.line_no })}
                    value={amounts[l.id]?.quantity ?? ""}
                    onChange={(e) => set(l.id, { quantity: e.target.value })}
                  />
                </td>
                <td className="num">
                  <input
                    inputMode="decimal"
                    className="num"
                    size={12}
                    aria-label={t("cn.amountOf", { n: l.line_no })}
                    value={amounts[l.id]?.amount ?? ""}
                    onChange={(e) => set(l.id, { amount: e.target.value })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {note && <Totals note={note} />}
      <div className="wide">
        <p className="muted">{t("cn.formHelp")}</p>
        <button type="submit" disabled={save.isPending}>
          {note ? t("vouchers.saveDraft") : t("cn.makeDraft")}
        </button>
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function Totals({ note }: { note: CNDetail }) {
  const { t } = useTranslation();
  return (
    <p className="wide" aria-label={t("cn.totals")}>
      {t("ti.subtotal")}: <strong>{formatDecimal(note.subtotal)}</strong>
      {note.taxes.map((x) => (
        <span key={`${x.label}-${x.rate}`}>
          {" · "}
          {x.label} {x.rate}%: <strong>{formatDecimal(x.amount)}</strong>
        </span>
      ))}
      {" · "}
      {t("cn.total")}: <strong>{formatDecimal(note.total_amount)}</strong>
    </p>
  );
}

function ReadOnly({ note }: { note: CNDetail }) {
  const { t } = useTranslation();
  const on = note.lines.filter((l) => l.credit_amount);
  return (
    <section className="panel" aria-label={t("cn.details")}>
      <p>
        {t(`cn.kinds.${note.kind}`)} · {note.credit_date} · {note.reason}
      </p>
      <div className="table-wrap">
        <table aria-label={t("cn.lines")}>
          <thead>
            <tr>
              <th>{t("ti.productCode")}</th>
              <th>{t("quotations.description")}</th>
              <th className="num">{t("cn.qtyReturned")}</th>
              <th className="num">{t("cn.amount")}</th>
            </tr>
          </thead>
          <tbody>
            {on.map((l) => (
              <tr key={l.id}>
                <td>{l.product_code}</td>
                <td>{l.description}</td>
                <td className="num">{l.credit_quantity && l.credit_quantity !== "0.000" ? formatQuantity(l.credit_quantity) : ""}</td>
                <td className="num">{formatDecimal(l.credit_amount ?? "0")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Totals note={note} />
      {note.amount_in_words && <p className="muted">{note.amount_in_words}</p>}
    </section>
  );
}

function Actions({ note }: { note: CNDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const done = (latest: CNDetail) => {
    queryClient.setQueryData([...cnKey, "one", String(latest.id)], latest);
    void queryClient.invalidateQueries({ queryKey: [...cnKey, "list"] });
    setText("");
  };
  const act = useMutation({ mutationFn: (call: () => Promise<CNDetail>) => call(), onSuccess: done });
  const remove = useMutation({
    mutationFn: () => deleteCreditNote(note.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: cnKey });
      navigate("/credit-notes");
    },
  });

  return (
    <section className="panel" aria-label={t("cn.actions")}>
      <p>
        <a className="button-link secondary" href={creditNotePdfUrl(note.id)} target="_blank" rel="noreferrer">
          {note.status === "approved" ? t("cn.pdf") : t("cn.preview")}
        </a>
      </p>
      {note.can_edit && (
        <p>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => submitCreditNote(note.id))}>
            {t("mj.send")}
          </button>{" "}
          <button type="button" className="secondary" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {t("cn.delete")}
          </button>{" "}
          <span className="muted">{t("cn.sendHelp")}</span>
        </p>
      )}
      {note.can_approve && (
        <div className="inline-form">
          <label>
            {t("salesOrders.comment")}
            <input value={text} maxLength={500} onChange={(e) => setText(e.target.value)} />
          </label>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => approveCreditNote(note.id, text))}>
            {t("cn.approve")}
          </button>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => returnCreditNote(note.id, text))}>
            {t("salesOrders.sendBack")}
          </button>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => rejectCreditNote(note.id, text))}>
            {t("mj.reject")}
          </button>
        </div>
      )}
      <ErrorLine error={act.error ?? remove.error} />
      {note.approval && note.approval.history.length > 0 && (
        <ul className="changes" aria-label={t("salesOrders.approvalHistory")}>
          {note.approval.history.map((h, i) => (
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
