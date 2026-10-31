import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import {
  advancesKey,
  getAdvanceOptions,
  listAdvances,
  RECEIPT_METHODS,
  recordAdvance,
  type ReceiptMethod,
} from "../api/advances";
import { can, canDo } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import DataTable from "../components/DataTable";
import SearchSelect from "../components/SearchSelect";
import { formatDecimal } from "../lib/decimal";

function today(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

/** Customer advances (spec 5.2): the Cashier records, the Accountant approves. */
export default function AdvancesPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const waiting = params.get("waiting") ?? "";
  const status = params.get("status") ?? "";
  const rows = useQuery({ queryKey: [...advancesKey, "list", status, waiting], queryFn: () => listAdvances({ status, waiting }) });
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const recorder = canDo(me.access, "record_receipt") && can(me.access, "payments", "enter");

  return (
    <main className="page">
      <h1>{t("advances.title")}</h1>
      <p className="muted">{t("advances.help")}</p>
      {recorder && <NewAdvance />}
      <div className="toolbar">
        <label>
          {t("vouchers.status")}
          <select value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">{t("advances.allStatuses")}</option>
            {["awaiting_approval", "approved", "rejected"].map((s) => (
              <option key={s} value={s}>
                {t(`advances.statuses.${s}`)}
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
          label={t("advances.title")}
          rows={rows.data}
          rowKey={(r) => r.id}
          searchable={false}
          emptyText={t("advances.none")}
          columns={[
            {
              id: "number",
              header: t("advances.number"),
              value: (r) => r.number,
              cell: (r) => (
                <Link to={`/advances/${r.id}`} className="mono">
                  {r.number}
                </Link>
              ),
            },
            { id: "date", header: t("vouchers.date"), value: (r) => r.receipt_date },
            { id: "customer", header: t("quotations.customer"), value: (r) => r.customer.name },
            { id: "quotation", header: t("quotations.quotation"), value: (r) => r.quotation?.label ?? "" },
            { id: "division", header: t("vouchers.division"), value: (r) => r.division },
            {
              id: "amount",
              header: t("advances.amount"),
              value: (r) => r.amount,
              cell: (r) => `${r.currency} ${formatDecimal(r.amount)}`,
            },
            { id: "lkr", header: t("advances.amountLkr"), value: (r) => r.amount_lkr, money: true },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`advances.statuses.${r.status}`) },
          ]}
        />
      )}
    </main>
  );
}

function NewAdvance() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const options = useQuery({ queryKey: [...advancesKey, "options"], queryFn: getAdvanceOptions });
  const [values, setValues] = useState({
    customer: "",
    proforma: "",
    quotation: "",
    division: "",
    account: "",
    method: "transfer" as ReceiptMethod,
    amount: "",
    receipt_date: today(),
    reference: "",
    notes: "",
  });
  const set = (field: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [field]: value }));
  const customer = options.data?.customers.find((c) => String(c.id) === values.customer);
  const account = options.data?.accounts.find((a) => String(a.id) === values.account);
  const cashAccounts = ["cash", "petty_cash"];
  const accounts = (options.data?.accounts ?? []).filter((a) =>
    values.method === "cash" ? cashAccounts.includes(a.kind) : !cashAccounts.includes(a.kind),
  );

  const save = useMutation({
    mutationFn: () =>
      recordAdvance({
        customer: Number(values.customer),
        quotation: values.quotation ? Number(values.quotation) : null,
        proforma: values.proforma ? Number(values.proforma) : null,
        division: values.quotation || values.proforma ? "" : values.division,
        account: Number(values.account),
        method: values.method,
        amount: values.amount,
        receipt_date: values.receipt_date,
        reference: values.reference,
        notes: values.notes,
      }),
    onSuccess: (made) => {
      void queryClient.invalidateQueries({ queryKey: advancesKey });
      navigate(`/advances/${made.id}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("advances.new")} onSubmit={submit}>
      <h2 className="wide">{t("advances.new")}</h2>
      <div className="wide">
        <SearchSelect
          label={t("quotations.customer")}
          options={(options.data?.customers ?? []).map((c) => ({ value: String(c.id), label: `${c.code} ${c.name}` }))}
          value={values.customer}
          onChange={(value) => setValues((now) => ({ ...now, customer: value, quotation: "", proforma: "" }))}
        />
      </div>
      {customer && customer.proformas.length > 0 && (
        <label>
          {t("advances.againstProforma")}
          <select value={values.proforma} onChange={(e) => setValues((now) => ({ ...now, proforma: e.target.value, quotation: "" }))}>
            <option value="">{t("advances.noProforma")}</option>
            {customer.proformas.map((p) => (
              <option key={p.id} value={p.id}>
                {p.number} ({p.currency} {formatDecimal(p.total_amount)})
              </option>
            ))}
          </select>
        </label>
      )}
      {!values.proforma && (
      <label>
        {t("advances.againstQuotation")}
        <select value={values.quotation} onChange={(e) => set("quotation")(e.target.value)}>
          <option value="">{t("advances.noQuotation")}</option>
          {customer?.quotations.map((q) => (
            <option key={q.id} value={q.id}>
              {q.label} ({q.currency} {formatDecimal(q.total_amount)})
            </option>
          ))}
        </select>
      </label>
      )}
      {!values.quotation && !values.proforma && (
        <label>
          {t("vouchers.division")}
          <select value={values.division} onChange={(e) => set("division")(e.target.value)}>
            <option value="">—</option>
            {options.data?.divisions.map((d) => (
              <option key={d.code} value={d.code}>
                {d.code} {d.name}
              </option>
            ))}
          </select>
        </label>
      )}
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
      <label>
        {t("advances.account")}
        <select value={values.account} required onChange={(e) => set("account")(e.target.value)}>
          <option value="">—</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.code} {a.name} ({a.currency})
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("advances.amountIn", { currency: account?.currency ?? "" })}
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
      <label className="wide">
        {t("customers.field.notes")}
        <textarea rows={2} value={values.notes} onChange={(e) => set("notes")(e.target.value)} />
      </label>
      <div className="wide">
        <button type="submit" disabled={save.isPending}>
          {t("advances.record")}
        </button>{" "}
        <span className="muted">{t("advances.recordHelp")}</span>
        {save.error ? (
          <p className="form-error" role="alert">
            {save.error instanceof ApiError && save.error.detail ? save.error.detail : t("common.error")}
          </p>
        ) : null}
      </div>
    </form>
  );
}
