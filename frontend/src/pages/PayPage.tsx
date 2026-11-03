import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import {
  accountFits,
  listPayAccounts,
  listToPay,
  paymentsKey,
  recordPayment,
  type PayAccount,
  type Payment,
  type PaymentMethod,
  type ToPayRow,
  whtCertificateUrl,
} from "../api/payments";
import { voucherPrintUrl, vouchersKey } from "../api/vouchers";
import { formatDecimal } from "../lib/decimal";

const today = () => new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD, local date

/** Record a payment against one approved voucher (spec 4.4, Cashier). The payee and the
 * most that can be paid come from the voucher; the server checks everything again. */
export default function PayPage() {
  const { t } = useTranslation();
  const [search] = useSearchParams();
  const id = Number(search.get("voucher"));
  const toPay = useQuery({ queryKey: [...paymentsKey, "to-pay"], queryFn: () => listToPay() });
  const accounts = useQuery({ queryKey: [...paymentsKey, "accounts"], queryFn: listPayAccounts });
  const [done, setDone] = useState<Payment | null>(null);
  const voucher = toPay.data?.find((v) => v.id === id);

  return (
    <main className="page">
      <p>
        <Link to="/payments">{t("payments.backToList")}</Link>
      </p>
      <h1>{t("payments.recordTitle")}</h1>
      {done && <Done payment={done} />}
      {!done && toPay.data && !voucher && (
        <p className="form-error" role="alert">
          {t("payments.notPayable")}
        </p>
      )}
      {!done && voucher && accounts.data && (
        <PayForm key={voucher.id} voucher={voucher} accounts={accounts.data} onDone={setDone} />
      )}
    </main>
  );
}

function PayForm(props: { voucher: ToPayRow; accounts: PayAccount[]; onDone: (p: Payment) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { voucher, accounts } = props;
  const [method, setMethod] = useState<PaymentMethod>(voucher.methods[0]);
  const foreign = voucher.foreign?.currency ?? null;
  const fitting = accounts.filter((a) => accountFits(a, method, foreign));
  const preferred = fitting.find((a) => a.id === voucher.suggested_account) ?? fitting[0];
  const [accountId, setAccountId] = useState<string>(preferred ? String(preferred.id) : "");
  const account = fitting.find((a) => String(a.id) === accountId);
  // P2-12: with withholding tax the Cashier enters what the payee receives.
  const toReceive = voucher.to_receive ?? voucher.remaining;
  const [amount, setAmount] = useState(toReceive);
  const [date, setDate] = useState(today());
  const [cheque, setCheque] = useState<string | null>(null);
  const [chequeDate, setChequeDate] = useState("");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const chequeNumber = cheque ?? account?.next_cheque ?? "";

  const save = useMutation({
    mutationFn: () =>
      recordPayment({
        voucher: voucher.id,
        account: Number(accountId),
        method,
        amount,
        payment_date: date,
        reference: method === "cheque" ? "" : reference,
        cheque_number: method === "cheque" ? chequeNumber || null : null,
        cheque_date: method === "cheque" && chequeDate ? chequeDate : null,
        notes,
      }),
    onSuccess: (payment) => {
      void queryClient.invalidateQueries({ queryKey: paymentsKey });
      void queryClient.invalidateQueries({ queryKey: vouchersKey });
      props.onDone(payment);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const changeMethod = (next: PaymentMethod) => {
    setMethod(next);
    const first = accounts.find((a) => accountFits(a, next, foreign) && a.id === voucher.suggested_account) ??
      accounts.find((a) => accountFits(a, next, foreign));
    setAccountId(first ? String(first.id) : "");
    setCheque(null);
  };

  return (
    <form className="panel form-grid" aria-label={t("payments.recordTitle")} onSubmit={submit}>
      <p className="wide">
        <strong className="mono">{voucher.number}</strong> · {voucher.voucher_type.name} ·{" "}
        {voucher.payee?.name ?? voucher.transfer_to} · {voucher.division}
        <br />
        {t("payments.summary", {
          approved: formatDecimal(voucher.total_amount),
          paid: formatDecimal(voucher.paid),
          remaining: formatDecimal(voucher.remaining),
        })}
        {Number(voucher.wht_total ?? 0) > 0 && (
          <>
            <br />
            {t("payments.whtSummary", { wht: formatDecimal(voucher.wht_total ?? "0"), receive: formatDecimal(toReceive) })}
          </>
        )}
      </p>
      <label>
        {t("payments.method")}
        <select value={method} onChange={(e) => changeMethod(e.target.value as PaymentMethod)}>
          {voucher.methods.map((m) => (
            <option key={m} value={m}>
              {t(`payments.methods.${m}`)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("payments.account")}
        <select value={accountId} required onChange={(e) => {
          setAccountId(e.target.value);
          setCheque(null);
          // From an account in the invoices' currency, the amount is in that currency (P2-11).
          const chosen = fitting.find((a) => String(a.id) === e.target.value);
          setAmount(chosen && chosen.currency !== "LKR" && voucher.foreign ? voucher.foreign.left : toReceive);
        }}>
          <option value="">—</option>
          {fitting.map((a) => (
            <option key={a.id} value={a.id}>
              {a.code} {a.name}
              {a.currency !== "LKR" ? ` (${a.currency})` : ""}
            </option>
          ))}
        </select>
      </label>
      {fitting.length === 0 && (
        <p className="wide form-error">{t("payments.noAccount")}</p>
      )}
      <label>
        {account && account.currency !== "LKR" ? t("payments.amountIn", { currency: account.currency }) : t("payments.amount")}
        <input inputMode="decimal" className="num" required value={amount} onChange={(e) => setAmount(e.target.value)} />
      </label>
      {account && account.currency !== "LKR" && voucher.foreign && (
        <p className="muted wide">
          {t("payments.foreignNote", { currency: voucher.foreign.currency, left: formatDecimal(voucher.foreign.left) })}
        </p>
      )}
      <label>
        {t("payments.date")}
        <input type="date" required value={date} max={today()} onChange={(e) => setDate(e.target.value)} />
      </label>
      {method === "cheque" ? (
        <>
          <label>
            {t("payments.chequeNumber")}
            <input value={chequeNumber} onChange={(e) => setCheque(e.target.value)} />
          </label>
          <label>
            {t("payments.chequeDate")}
            <input type="date" value={chequeDate} onChange={(e) => setChequeDate(e.target.value)} />
          </label>
        </>
      ) : (
        method !== "cash" && (
          <label>
            {t("payments.reference")}
            <input required maxLength={50} value={reference} onChange={(e) => setReference(e.target.value)} />
          </label>
        )
      )}
      <label className="wide">
        {t("payments.notes")}
        <input maxLength={300} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <div className="wide">
        <button type="submit" disabled={save.isPending || !accountId}>
          {t("payments.save")}
        </button>
      </div>
      {save.error && (
        <p className="wide form-error" role="alert">
          {save.error instanceof ApiError && save.error.detail ? save.error.detail : t("common.error")}
        </p>
      )}
    </form>
  );
}

function Done({ payment }: { payment: Payment }) {
  const { t } = useTranslation();
  return (
    <section className="panel notice" role="status" aria-label={t("payments.saved")}>
      <h2>{t("payments.saved")}</h2>
      <p>
        {t("payments.savedText", {
          number: payment.number,
          amount: formatDecimal(payment.amount),
          voucher: payment.voucher.number,
          entry: payment.journal_entry,
        })}
      </p>
      {payment.wht_certificate && (
        <p>
          {t("payments.whtKept", { amount: formatDecimal(payment.wht_amount ?? "0"), number: payment.wht_certificate })}{" "}
          <a href={whtCertificateUrl(payment.id)} target="_blank" rel="noopener noreferrer">
            {t("payments.whtCertificate")}
          </a>
        </p>
      )}
      <div className="row-actions">
        <button type="button" onClick={() => window.open(voucherPrintUrl(payment.voucher.id, "A4"), "_blank", "noopener")}>
          {t("payments.print")}
        </button>
        <Link className="button-link secondary" to="/payments">
          {t("payments.backToList")}
        </Link>
      </div>
    </section>
  );
}
