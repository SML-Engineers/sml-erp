import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { can } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import {
  createSupplierStatement,
  importStatementFile,
  listSupplierStatements,
  payablesKey,
  type StatementLine,
  type SupplierStatementSummary,
} from "../api/payables";
import { listPayees } from "../api/payees";
import DataTable from "../components/DataTable";
import SearchSelect from "../components/SearchSelect";
import { formatDecimal } from "../lib/decimal";

function today(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

const EMPTY: StatementLine = { date: "", reference: "", description: "", debit: "", credit: "" };

/** Supplier statements (P2-10): typed in or imported, then checked against our records. */
export default function SupplierStatementsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const rows = useQuery({ queryKey: [...payablesKey, "statements"], queryFn: listSupplierStatements });
  const canEnter = can(me.access, "vouchers", "enter") || can(me.access, "accounting", "enter");

  return (
    <main className="page">
      <p>
        <Link to="/payables">{t("ap.backToAging")}</Link>
      </p>
      <h1>{t("ap.statements")}</h1>
      <p className="muted">{t("ap.statementsHelp")}</p>
      {canEnter && <NewStatement />}
      {rows.data && (
        <DataTable<SupplierStatementSummary>
          label={t("ap.statements")}
          rows={rows.data}
          rowKey={(r) => r.id}
          emptyText={t("ap.noStatements")}
          columns={[
            {
              id: "supplier",
              header: t("ap.supplier"),
              value: (r) => `${r.supplier.code} ${r.supplier.name}`,
              cell: (r) => <Link to={`/supplier-statements/${r.id}`}>{`${r.supplier.code} ${r.supplier.name}`}</Link>,
            },
            { id: "date", header: t("ap.statementDate"), value: (r) => r.statement_date },
            {
              id: "closing",
              header: t("ap.theirBalance"),
              value: (r) => r.closing_balance,
              cell: (r) => `${r.currency} ${formatDecimal(r.closing_balance)}`,
            },
            { id: "status", header: t("vouchers.status"), value: (r) => t(`ap.statuses.${r.status}`) },
          ]}
        />
      )}
    </main>
  );
}

function NewStatement() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const suppliers = useQuery({ queryKey: ["payees", "picker"], queryFn: () => listPayees("", false) });
  const [values, setValues] = useState({ supplier: "", statement_date: today(), from_date: "", closing_balance: "", notes: "" });
  const [lines, setLines] = useState<StatementLine[]>([{ ...EMPTY }]);
  const set = (field: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [field]: value }));
  const setLine = (i: number, field: keyof StatementLine, value: string) =>
    setLines((now) => now.map((line, n) => (n === i ? { ...line, [field]: value } : line)));

  const load = useMutation({
    mutationFn: (file: File) => importStatementFile(file),
    onSuccess: (read) => setLines(read.lines.map((l) => ({ ...l, date: String(l.date) }))),
  });
  const save = useMutation({
    mutationFn: () =>
      createSupplierStatement({
        supplier: Number(values.supplier),
        statement_date: values.statement_date,
        from_date: values.from_date || null,
        closing_balance: values.closing_balance.replace(/,/g, ""),
        notes: values.notes,
        lines: lines.filter((l) => l.date || l.reference || l.debit || l.credit),
      }),
    onSuccess: (made) => {
      void queryClient.invalidateQueries({ queryKey: payablesKey });
      navigate(`/supplier-statements/${made.id}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const error = save.error ?? load.error;
  return (
    <form className="panel form-grid" aria-label={t("ap.newStatement")} onSubmit={submit}>
      <h2 className="wide">{t("ap.newStatement")}</h2>
      <div className="wide">
        <SearchSelect
          label={t("ap.supplier")}
          options={(suppliers.data ?? []).map((s) => ({ value: String(s.id), label: `${s.code} ${s.name}` }))}
          value={values.supplier}
          onChange={set("supplier")}
        />
      </div>
      <label>
        {t("ap.fromDate")}
        <input type="date" value={values.from_date} onChange={(e) => set("from_date")(e.target.value)} />
      </label>
      <label>
        {t("ap.statementDate")}
        <input type="date" required value={values.statement_date} onChange={(e) => set("statement_date")(e.target.value)} />
      </label>
      <label>
        {t("ap.theirBalance")}
        <input inputMode="decimal" className="num" required value={values.closing_balance} onChange={(e) => set("closing_balance")(e.target.value)} />
      </label>
      <label>
        {t("ap.importFile")}
        <input
          type="file"
          accept=".xlsx,.csv"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) load.mutate(file);
          }}
        />
      </label>
      <p className="muted wide">{t("ap.importHelp")}</p>
      <div className="wide table-wrap">
        <table aria-label={t("ap.lines")}>
          <thead>
            <tr>
              <th>{t("vouchers.date")}</th>
              <th>{t("ar.reference")}</th>
              <th>{t("quotations.description")}</th>
              <th className="num">{t("ar.debit")}</th>
              <th className="num">{t("ar.credit")}</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line, i) => (
              <tr key={i}>
                <td>
                  <input type="date" aria-label={t("ap.lineField", { n: i + 1, field: t("vouchers.date") })} value={line.date} onChange={(e) => setLine(i, "date", e.target.value)} />
                </td>
                <td>
                  <input aria-label={t("ap.lineField", { n: i + 1, field: t("ar.reference") })} value={line.reference} maxLength={60} onChange={(e) => setLine(i, "reference", e.target.value)} />
                </td>
                <td>
                  <input aria-label={t("ap.lineField", { n: i + 1, field: t("quotations.description") })} value={line.description} maxLength={300} onChange={(e) => setLine(i, "description", e.target.value)} />
                </td>
                <td>
                  <input inputMode="decimal" className="num" aria-label={t("ap.lineField", { n: i + 1, field: t("ar.debit") })} value={line.debit} onChange={(e) => setLine(i, "debit", e.target.value)} />
                </td>
                <td>
                  <input inputMode="decimal" className="num" aria-label={t("ap.lineField", { n: i + 1, field: t("ar.credit") })} value={line.credit} onChange={(e) => setLine(i, "credit", e.target.value)} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button type="button" className="secondary" onClick={() => setLines((now) => [...now, { ...EMPTY }])}>
          {t("ap.addLine")}
        </button>
      </div>
      <label className="wide">
        {t("customers.field.notes")}
        <textarea rows={2} value={values.notes} onChange={(e) => set("notes")(e.target.value)} />
      </label>
      <div className="wide">
        <button type="submit" disabled={save.isPending || !values.supplier}>
          {t("ap.saveAndCompare")}
        </button>
        {error ? (
          <p className="form-error" role="alert">
            {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
          </p>
        ) : null}
      </div>
    </form>
  );
}
