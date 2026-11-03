import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import type { EmailDraft } from "../api/documentEmail";
import {
  BUCKETS,
  getStatement,
  getStatementEmail,
  receivablesKey,
  sendStatementEmail,
  setReminders,
  statementPath,
  statementPdfUrl,
  type Statement,
} from "../api/receivables";
import ExportLinks from "../components/ExportLinks";
import SendEmailForm from "../components/SendEmailForm";
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

/** A customer's statement of account (P2-08): its ledger for a period with a running balance,
 * its open invoices by age, credit status, printing, email and payment reminders. */
export default function StatementPage() {
  const { t } = useTranslation();
  const { id } = useParams();
  const customer = Number(id);
  const [params, setParams] = useSearchParams();
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const key = [...receivablesKey, "statement", customer, from, to];
  const statement = useQuery({ queryKey: key, queryFn: () => getStatement(customer, from, to) });
  const s = statement.data;
  const setDate = (name: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  };

  return (
    <main className="page">
      <p>
        <Link to="/receivables">{t("ar.backToList")}</Link>
      </p>
      <h1>
        {t("ar.statement")} {s ? `${s.customer.code} ${s.customer.name}` : ""}
      </h1>
      <div className="toolbar">
        <label>
          {t("ar.from")}
          <input type="date" value={from || s?.from || ""} onChange={(e) => setDate("from", e.target.value)} />
        </label>
        <label>
          {t("ar.to")}
          <input type="date" value={to || s?.to || ""} onChange={(e) => setDate("to", e.target.value)} />
        </label>
        <a className="button-link small secondary" href={statementPdfUrl(customer, from, to)} target="_blank" rel="noreferrer">
          {t("ar.printStatement")}
        </a>{" "}
        <ExportLinks path={statementPath(customer)} params={{ from, to }} label={t("ar.statement")} />
      </div>
      <ErrorLine error={statement.error} />
      {s && (
        <>
          <section className="panel" aria-label={t("ar.summary")}>
            {s.credit.on_hold && (
              <p className="form-error">
                {t("ar.onHold")}
                {s.credit.overdue !== "0.00" && ` ${t("ar.overdueNow", { amount: formatDecimal(s.credit.overdue) })}`}
                {s.credit.over_limit && ` ${t("ar.overLimit")}`}
              </p>
            )}
            <dl className="details">
              <dt>{t("ar.amountDue")}</dt>
              <dd>
                <strong>LKR {formatDecimal(s.closing)}</strong>
              </dd>
              <dt>{t("ar.overdue")}</dt>
              <dd>LKR {formatDecimal(s.overdue)}</dd>
              {s.advances_held !== "0.00" && (
                <>
                  <dt>{t("ar.advancesHeld")}</dt>
                  <dd>LKR {formatDecimal(s.advances_held)}</dd>
                </>
              )}
              <dt>{t("ar.creditLimit")}</dt>
              <dd>{s.customer.credit_limit === null ? t("ar.noLimit") : `LKR ${formatDecimal(s.customer.credit_limit)}`}</dd>
              <dt>{t("ar.terms")}</dt>
              <dd>{t("ar.termsDays", { days: s.customer.payment_terms_days })}</dd>
            </dl>
            <div className="table-wrap">
              <table aria-label={t("ar.byAge")}>
                <thead>
                  <tr>
                    {BUCKETS.map((b) => (
                      <th key={b} className="num">
                        {t(`ar.buckets.${b}`)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    {BUCKETS.map((b) => (
                      <td key={b} className="num">
                        {formatDecimal(s.buckets[b])}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
          <section className="panel" aria-label={t("ar.lines")}>
            <h2>{t("ar.lines")}</h2>
            <div className="table-wrap">
              <table aria-label={t("ar.lines")}>
                <thead>
                  <tr>
                    <th>{t("vouchers.date")}</th>
                    <th>{t("ar.reference")}</th>
                    <th>{t("quotations.description")}</th>
                    <th className="num">{t("ar.debit")}</th>
                    <th className="num">{t("ar.credit")}</th>
                    <th className="num">{t("ar.balance")}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>{s.from}</td>
                    <td />
                    <td>
                      <strong>{t("ar.opening")}</strong>
                    </td>
                    <td />
                    <td />
                    <td className="num">{formatDecimal(s.opening)}</td>
                  </tr>
                  {s.lines.map((line, i) => (
                    <tr key={i}>
                      <td>{line.date}</td>
                      <td className="mono">{line.reference}</td>
                      <td>{line.description}</td>
                      <td className="num">{line.debit !== "0.00" ? formatDecimal(line.debit) : ""}</td>
                      <td className="num">{line.credit !== "0.00" ? formatDecimal(line.credit) : ""}</td>
                      <td className="num">{formatDecimal(line.balance)}</td>
                    </tr>
                  ))}
                  <tr>
                    <td>{s.to}</td>
                    <td />
                    <td>
                      <strong>{t("ar.closing")}</strong>
                    </td>
                    <td />
                    <td />
                    <td className="num">
                      <strong>{formatDecimal(s.closing)}</strong>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
          {s.items.length > 0 && (
            <section className="panel" aria-label={t("ar.openInvoices")}>
              <h2>{t("ar.openInvoices")}</h2>
              <div className="table-wrap">
                <table aria-label={t("ar.openInvoices")}>
                  <thead>
                    <tr>
                      <th>{t("receipts.invoice")}</th>
                      <th>{t("vouchers.date")}</th>
                      <th>{t("receipts.due")}</th>
                      <th className="num">{t("ar.daysOverdue")}</th>
                      <th className="num">{t("receipts.total")}</th>
                      <th className="num">{t("receipts.open")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.items.map((item) => (
                      <tr key={item.invoice.id}>
                        <td>
                          <Link to={`/tax-invoices/${item.invoice.id}`} className="mono">
                            {item.invoice.number}
                          </Link>
                        </td>
                        <td>{item.invoice.invoice_date}</td>
                        <td>{item.invoice.due_date}</td>
                        <td className="num">{item.days_overdue || ""}</td>
                        <td className="num">{formatDecimal(item.invoice.total_amount)}</td>
                        <td className="num">{formatDecimal(item.open)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          <Reminders statement={s} />
          {s.can_email && <EmailStatement statement={s} from={from} to={to} queryKey={key} />}
        </>
      )}
    </main>
  );
}

function Reminders({ statement }: { statement: Statement }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const plan = statement.reminders;
  const [isOn, setIsOn] = useState(plan.is_on);
  const [every, setEvery] = useState(String(plan.every_days));
  const save = useMutation({
    mutationFn: () => setReminders(statement.customer.id, isOn, Number(every)),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: receivablesKey }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <section className="panel" aria-label={t("ar.reminders")}>
      <h2>{t("ar.reminders")}</h2>
      <p className="muted">
        {plan.is_on
          ? t("ar.remindersOn", { days: plan.every_days, to: plan.recipient, by: plan.set_by ?? "" })
          : t("ar.remindersOff")}
        {plan.last_sent_on && ` ${t("ar.lastReminder", { date: plan.last_sent_on })}`}
      </p>
      {plan.can_manage && (
        <form className="inline-form" aria-label={t("ar.reminderSettings")} onSubmit={submit}>
          <label>
            <input type="checkbox" checked={isOn} onChange={(e) => setIsOn(e.target.checked)} /> {t("ar.sendReminders")}
          </label>
          <label>
            {t("ar.everyDays")}
            <input type="number" min={1} max={90} value={every} onChange={(e) => setEvery(e.target.value)} />
          </label>
          <button type="submit" disabled={save.isPending}>
            {t("ar.saveReminders")}
          </button>
          <ErrorLine error={save.error} />
        </form>
      )}
    </section>
  );
}

function EmailStatement(props: { statement: Statement; from: string; to: string; queryKey: unknown[] }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const customer = props.statement.customer;
  const [email, setEmail] = useState<EmailDraft | null>(null);
  const load = useMutation({ mutationFn: () => getStatementEmail(customer.id, props.from, props.to), onSuccess: setEmail });

  return (
    <section className="panel" aria-label={t("ar.email")}>
      <h2>{t("ar.email")}</h2>
      {!email && (
        <button type="button" className="secondary" disabled={load.isPending} onClick={() => load.mutate()}>
          {t("ar.emailStatement")}
        </button>
      )}
      {email && (
        <SendEmailForm
          draft={email}
          attachmentName={`Statement-${customer.code}.pdf`}
          onSend={async (message) => {
            const latest = await sendStatementEmail(customer.id, props.from, props.to, message);
            queryClient.setQueryData(props.queryKey, latest);
          }}
          onCancel={() => setEmail(null)}
        />
      )}
      <ErrorLine error={load.error} />
      {props.statement.emails.length > 0 && (
        <ul className="changes" aria-label={t("ar.emailsSent")}>
          {props.statement.emails.map((m, i) => (
            <li key={i}>
              {m.sent_at.slice(0, 16).replace("T", " ")} · {m.to} · {m.reminder ? t("ar.reminder") : m.subject} · {m.by}
              {m.status === "failed" && ` · ${t("ar.failed")}: ${m.error}`}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
