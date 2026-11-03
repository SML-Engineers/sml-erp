import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { can, canDo } from "../api/access";
import { RECEIPT_METHODS, type ReceiptMethod } from "../api/advances";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import {
  getReceiptOptions,
  listReceipts,
  RECEIPT_STATUSES,
  receiptsKey,
  recordReceipt,
  type OpenInvoice,
} from "../api/receipts";
import DataTable from "../components/DataTable";
import SearchSelect from "../components/SearchSelect";
import { compareDecimal, formatDecimal, isDecimal, sumDecimal } from "../lib/decimal";

function today(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

const negate = (value: string) => (value.startsWith("-") ? value.slice(1) : `-${value}`);
const clean = (value: string) => value.replace(/,/g, "").trim();

/** Customer receipts (P2-07): the Cashier records money received for tax invoices, the
 * Accountant approves and it is posted. */
export default function ReceiptsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const waiting = params.get("waiting") ?? "";
  const status = params.get("status") ?? "";
  const rows = useQuery({
    queryKey: [...receiptsKey, "list", status, waiting],
    queryFn: () => listReceipts({ status, waiting }),
  });
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const recorder = canDo(me.access, "record_receipt") && can(me.access, "payments", "enter");

  return (
    <main className="page">
      <h1>{t("receipts.title")}</h1>
      <p className="muted">{t("receipts.help")}</p>
      {recorder && <NewReceipt />}
      <div className="toolbar">
        <label>
          {t("vouchers.status")}
          <select value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">{t("advances.allStatuses")}</option>
            {RECEIPT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`receipts.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          <input type="checkbox" checked={waiting === "me"} onChange={(e) => set("waiting", e.target.checked ? "me" : "")} />{" "}
          {t("quotations.waitingForMe")}
        </label>
      </div>
      {rows.data && (
        <DataTable
          label={t("receipts.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("receipts.none")}
          columns={[
            {
              id: "number",
              header: t("advances.number"),
              value: (r) => r.number,
              cell: (r) => (
                <Link to={`/receipts/${r.id}`} className="mono">
                  {r.number}
                </Link>
              ),
            },
            { id: "date", header: t("vouchers.date"), value: (r) => r.receipt_date },
            { id: "customer", header: t("quotations.customer"), value: (r) => r.customer.name },
            {
              id: "method",
              header: t("advances.method"),
              value: (r) => `${t(`advances.methods.${r.method}`)} ${r.reference}`.trim(),
            },
            { id: "amount", header: t("advances.amountLkr"), value: (r) => r.amount, money: true },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`receipts.statuses.${r.status}`) },
          ]}
        />
      )}
    </main>
  );
}

function NewReceipt() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const options = useQuery({ queryKey: [...receiptsKey, "options"], queryFn: getReceiptOptions });
  const [values, setValues] = useState({
    customer: "",
    account: "",
    method: "transfer" as ReceiptMethod,
    amount: "",
    receipt_date: today(),
    reference: "",
    cheque_date: "",
    cheque_bank: "",
    notes: "",
  });
  const [paying, setPaying] = useState<Record<number, string>>({});
  const set = (field: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [field]: value }));
  const customer = options.data?.customers.find((c) => String(c.id) === values.customer);
  const invoices: OpenInvoice[] = customer?.invoices ?? [];
  const cashAccounts = ["cash", "petty_cash"];
  const accounts = (options.data?.accounts ?? []).filter((a) =>
    values.method === "cash" ? cashAccounts.includes(a.kind) : !cashAccounts.includes(a.kind),
  );
  const cheque = values.method === "cheque";
  const amounts = invoices.map((i) => clean(paying[i.id] ?? "")).filter((v) => v !== "");
  const allValid = amounts.every((v) => isDecimal(v));
  const allocated = allValid ? sumDecimal(amounts) : "";
  const amount = clean(values.amount);
  const balanced = allValid && isDecimal(amount) && amounts.length > 0 && compareDecimal(allocated, amount) === 0;

  /** Spread the amount over the invoices, oldest first. */
  function fillOldestFirst() {
    if (!isDecimal(amount)) return;
    let left = amount;
    const next: Record<number, string> = {};
    for (const invoice of invoices) {
      if (compareDecimal(left, "0") <= 0) break;
      const pay = compareDecimal(left, invoice.open_amount) < 0 ? left : invoice.open_amount;
      next[invoice.id] = pay;
      left = sumDecimal([left, negate(pay)]);
    }
    setPaying(next);
  }

  const save = useMutation({
    mutationFn: () =>
      recordReceipt({
        customer: Number(values.customer),
        method: values.method,
        account: cheque || !values.account ? null : Number(values.account),
        amount,
        receipt_date: values.receipt_date,
        reference: values.reference,
        cheque_date: cheque && values.cheque_date ? values.cheque_date : null,
        cheque_bank: cheque ? values.cheque_bank : "",
        notes: values.notes,
        allocations: invoices
          .filter((i) => clean(paying[i.id] ?? "") !== "")
          .map((i) => ({ invoice: i.id, amount: clean(paying[i.id]) })),
      }),
    onSuccess: (made) => {
      void queryClient.invalidateQueries({ queryKey: receiptsKey });
      navigate(`/receipts/${made.id}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("receipts.new")} onSubmit={submit}>
      <h2 className="wide">{t("receipts.new")}</h2>
      <div className="wide">
        <SearchSelect
          label={t("quotations.customer")}
          options={(options.data?.customers ?? []).map((c) => ({ value: String(c.id), label: `${c.code} ${c.name}` }))}
          value={values.customer}
          onChange={(value) => {
            setValues((now) => ({ ...now, customer: value }));
            setPaying({});
          }}
        />
        {options.data && options.data.customers.length === 0 && <p className="muted">{t("receipts.nothingOpen")}</p>}
      </div>
      <label>
        {t("advances.method")}
        <select value={values.method} onChange={(e) => setValues((now) => ({ ...now, method: e.target.value as ReceiptMethod, account: "" }))}>
          {RECEIPT_METHODS.map((m) => (
            <option key={m} value={m}>
              {t(`advances.methods.${m}`)}
            </option>
          ))}
        </select>
      </label>
      {cheque ? (
        <>
          <label>
            {t("receipts.chequeDate")}
            <input type="date" value={values.cheque_date} onChange={(e) => set("cheque_date")(e.target.value)} />
          </label>
          <label>
            {t("receipts.chequeBank")}
            <input value={values.cheque_bank} maxLength={100} onChange={(e) => set("cheque_bank")(e.target.value)} />
          </label>
          <p className="muted wide">{t("receipts.chequeHelp")}</p>
        </>
      ) : (
        <label>
          {t("advances.account")}
          <select value={values.account} required onChange={(e) => set("account")(e.target.value)}>
            <option value="">—</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} {a.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        {t("advances.amountIn", { currency: "LKR" })}
        <input inputMode="decimal" className="num" value={values.amount} required onChange={(e) => set("amount")(e.target.value)} />
      </label>
      <label>
        {t("advances.receiptDate")}
        <input type="date" value={values.receipt_date} required onChange={(e) => set("receipt_date")(e.target.value)} />
      </label>
      {values.method !== "cash" && (
        <label>
          {t("advances.reference")}
          <input value={values.reference} maxLength={50} onChange={(e) => set("reference")(e.target.value)} />
        </label>
      )}
      {customer && (
        <div className="wide table-wrap">
          <table aria-label={t("receipts.invoices")}>
            <thead>
              <tr>
                <th>{t("receipts.invoice")}</th>
                <th>{t("vouchers.date")}</th>
                <th>{t("receipts.due")}</th>
                <th>{t("vouchers.division")}</th>
                <th className="num">{t("receipts.total")}</th>
                <th className="num">{t("receipts.open")}</th>
                <th className="num">{t("receipts.pay")}</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((i) => (
                <tr key={i.id}>
                  <td className="mono">{i.number}</td>
                  <td>{i.invoice_date}</td>
                  <td>{i.due_date}</td>
                  <td>{i.division}</td>
                  <td className="num">{formatDecimal(i.total_amount)}</td>
                  <td className="num">{formatDecimal(i.open_amount)}</td>
                  <td className="num">
                    <input
                      inputMode="decimal"
                      className="num"
                      aria-label={t("receipts.payOn", { number: i.number })}
                      value={paying[i.id] ?? ""}
                      onChange={(e) => setPaying((now) => ({ ...now, [i.id]: e.target.value }))}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            <button type="button" className="secondary" onClick={fillOldestFirst} disabled={!isDecimal(amount)}>
              {t("receipts.fill")}
            </button>{" "}
            <span className={balanced ? "muted" : "form-error"}>
              {t("receipts.allocated", { allocated: formatDecimal(allocated || "0.00"), amount: formatDecimal(amount || "0.00") })}
            </span>
          </p>
        </div>
      )}
      <label className="wide">
        {t("customers.field.notes")}
        <textarea rows={2} value={values.notes} onChange={(e) => set("notes")(e.target.value)} />
      </label>
      <div className="wide">
        <button type="submit" disabled={save.isPending || !balanced}>
          {t("advances.record")}
        </button>{" "}
        <span className="muted">{t("receipts.recordHelp")}</span>
        {save.error ? (
          <p className="form-error" role="alert">
            {save.error instanceof ApiError && save.error.detail ? save.error.detail : t("common.error")}
          </p>
        ) : null}
      </div>
    </form>
  );
}
