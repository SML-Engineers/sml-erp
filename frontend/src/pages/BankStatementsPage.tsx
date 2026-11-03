import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import {
  deleteStatement,
  getStatement,
  importStatement,
  listStatements,
  listTemplates,
  previewStatement,
  saveTemplate,
  statementsKey,
  type Preview,
  type StatementLine,
  type StatementTemplate,
} from "../api/bankStatements";
import { ApiError } from "../api/client";
import { listPayAccounts } from "../api/payments";
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

function Lines({ lines, label }: { lines: StatementLine[]; label: string }) {
  const { t } = useTranslation();
  return (
    <div className="table-wrap">
      <table aria-label={label}>
        <thead>
          <tr>
            <th>{t("bs.date")}</th>
            <th>{t("bs.description")}</th>
            <th className="num">{t("bs.out")}</th>
            <th className="num">{t("bs.in")}</th>
            <th className="num">{t("bs.balance")}</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line, i) => (
            <tr key={i} className={line.already ? "muted" : undefined}>
              <td>{line.date}</td>
              <td>
                {line.description}
                {line.reference && <span className="muted"> {line.reference}</span>}
                {line.already && <div>{t("bs.already")}</div>}
              </td>
              <td className="num">{Number(line.money_out) ? formatDecimal(line.money_out) : ""}</td>
              <td className="num">{Number(line.money_in) ? formatDecimal(line.money_in) : ""}</td>
              <td className="num">{line.balance ? formatDecimal(line.balance) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Bank statements (P2-15): import a bank's file with its template, check it, keep it. */
export default function BankStatementsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const rows = useQuery({ queryKey: [...statementsKey, "list"], queryFn: listStatements });
  const [open, setOpen] = useState<number | null>(null);
  const remove = useMutation({
    mutationFn: (id: number) => deleteStatement(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: statementsKey }),
  });
  return (
    <main className="page">
      <h1>{t("bs.title")}</h1>
      <p className="muted">{t("bs.help")}</p>
      <ImportForm />
      {rows.data && rows.data.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("bs.imported")}>
            <thead>
              <tr>
                <th>{t("bs.account")}</th>
                <th>{t("bs.period")}</th>
                <th className="num">{t("bs.opening")}</th>
                <th className="num">{t("bs.closing")}</th>
                <th className="num">{t("bs.lineCount")}</th>
                <th>{t("bs.importedBy")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.data.map((s) => (
                <tr key={s.id}>
                  <td>
                    {s.account.code} <span className="muted">{s.file_name}</span>
                  </td>
                  <td>
                    {s.from_date} – {s.to_date}
                  </td>
                  <td className="num">{s.opening_balance ? formatDecimal(s.opening_balance) : ""}</td>
                  <td className="num">{s.closing_balance ? formatDecimal(s.closing_balance) : ""}</td>
                  <td className="num">
                    {s.line_count}
                    {s.skipped > 0 && <div className="muted">{t("bs.skipped", { count: s.skipped })}</div>}
                  </td>
                  <td>{s.imported_by}</td>
                  <td>
                    <button type="button" className="small secondary" onClick={() => setOpen(open === s.id ? null : s.id)}>
                      {t("bs.show")}
                    </button>{" "}
                    <button type="button" className="small secondary" disabled={remove.isPending} onClick={() => remove.mutate(s.id)}>
                      {t("bs.delete")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ErrorLine error={rows.error ?? remove.error} />
      {open !== null && <OneStatement id={open} />}
      <Templates />
    </main>
  );
}

function OneStatement({ id }: { id: number }) {
  const { t } = useTranslation();
  const found = useQuery({ queryKey: [...statementsKey, "one", id], queryFn: () => getStatement(id) });
  if (!found.data) return <ErrorLine error={found.error} />;
  return (
    <section className="panel" aria-label={t("bs.lines")}>
      <h2>
        {found.data.account.code} {found.data.from_date} – {found.data.to_date}
      </h2>
      <Lines lines={found.data.lines ?? []} label={t("bs.lines")} />
    </section>
  );
}

function ImportForm() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const accounts = useQuery({ queryKey: ["payments", "accounts"], queryFn: listPayAccounts });
  const templates = useQuery({ queryKey: [...statementsKey, "templates"], queryFn: listTemplates });
  const banks = (accounts.data ?? []).filter((a) => a.kind === "current" || a.kind === "savings");
  const [account, setAccount] = useState("");
  const [template, setTemplate] = useState("");
  const [opening, setOpening] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const read = useMutation({
    mutationFn: () => previewStatement({ account, template, opening, file: file! }),
    onSuccess: (data) => setPreview(data),
  });
  const save = useMutation({
    mutationFn: () => importStatement({ account, template, opening, file: file! }),
    onSuccess: () => {
      setPreview(null);
      setFile(null);
      void queryClient.invalidateQueries({ queryKey: statementsKey });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    read.mutate();
  };
  return (
    <form className="panel form-grid" aria-label={t("bs.import")} onSubmit={submit}>
      <h2 className="wide">{t("bs.import")}</h2>
      <label>
        {t("bs.account")}
        <select value={account} required onChange={(e) => setAccount(e.target.value)}>
          <option value="">—</option>
          {banks.map((a) => (
            <option key={a.id} value={a.id}>
              {a.code} {a.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("bs.template")}
        <select value={template} required onChange={(e) => setTemplate(e.target.value)}>
          <option value="">—</option>
          {(templates.data ?? [])
            .filter((x) => x.is_active)
            .map((x) => (
              <option key={x.id} value={x.id}>
                {x.bank_name} ({x.file_kind.toUpperCase()}){x.checked ? "" : ` – ${t("bs.notChecked")}`}
              </option>
            ))}
        </select>
      </label>
      <label>
        {t("bs.openingIfAsked")}
        <input inputMode="decimal" value={opening} onChange={(e) => setOpening(e.target.value)} />
      </label>
      <label>
        {t("bs.file")}
        <input type="file" accept=".pdf,.xlsx,.csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <div className="wide row-actions">
        <button type="submit" className="secondary" disabled={read.isPending || !file}>
          {t("bs.read")}
        </button>
        {preview && preview.problems.length === 0 && (
          <button type="button" disabled={save.isPending} onClick={() => save.mutate()}>
            {t("bs.save")}
          </button>
        )}
      </div>
      <ErrorLine error={read.error ?? save.error} />
      {preview && (
        <div className="wide">
          {preview.problems.map((p) => (
            <p key={p} className="form-error">
              {p}
            </p>
          ))}
          {preview.opening && <p>{t("bs.openingWas", { amount: formatDecimal(preview.opening) })}</p>}
          <Lines lines={preview.lines} label={t("bs.preview")} />
        </div>
      )}
    </form>
  );
}

const EMPTY: Partial<StatementTemplate> = {
  code: "",
  bank_name: "",
  file_kind: "excel",
  date_format: "%d/%m/%Y",
  date_column: "Date",
  description_column: "Description",
  reference_column: "",
  out_column: "Debit",
  in_column: "Credit",
  amount_column: "",
  balance_column: "Balance",
  checked: false,
};

const COLUMNS = ["date_column", "description_column", "reference_column", "out_column", "in_column", "amount_column", "balance_column"] as const;

function Templates() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const templates = useQuery({ queryKey: [...statementsKey, "templates"], queryFn: listTemplates });
  const [editing, setEditing] = useState<Partial<StatementTemplate> | null>(null);
  const save = useMutation({
    mutationFn: () => saveTemplate(editing?.id ?? null, editing!),
    onSuccess: () => {
      setEditing(null);
      void queryClient.invalidateQueries({ queryKey: statementsKey });
    },
  });
  const set = (change: Partial<StatementTemplate>) => setEditing((now) => ({ ...now, ...change }));
  return (
    <section className="panel" aria-label={t("bs.templates")}>
      <h2>{t("bs.templates")}</h2>
      <p className="muted">{t("bs.templatesHelp")}</p>
      <ul className="plain-list">
        {templates.data?.map((x) => (
          <li key={x.id}>
            <button type="button" className="link-button" onClick={() => setEditing(x)}>
              {x.code}
            </button>{" "}
            {x.bank_name} · {x.file_kind.toUpperCase()} · {x.checked ? t("bs.checked") : t("bs.notChecked")}
            {!x.is_active && ` · ${t("bs.inactive")}`}
          </li>
        ))}
      </ul>
      <button type="button" className="secondary" onClick={() => setEditing({ ...EMPTY })}>
        {t("bs.newTemplate")}
      </button>
      {editing && (
        <form
          className="form-grid"
          aria-label={t("bs.templateForm")}
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          {editing.id === undefined && (
            <label>
              {t("bs.code")}
              <input value={editing.code ?? ""} required maxLength={20} onChange={(e) => set({ code: e.target.value })} />
            </label>
          )}
          <label>
            {t("bs.bank")}
            <input value={editing.bank_name ?? ""} required onChange={(e) => set({ bank_name: e.target.value })} />
          </label>
          <label>
            {t("bs.kind")}
            <select value={editing.file_kind} onChange={(e) => set({ file_kind: e.target.value as StatementTemplate["file_kind"] })}>
              <option value="excel">Excel</option>
              <option value="csv">CSV</option>
              <option value="pdf">PDF</option>
            </select>
          </label>
          <label>
            {t("bs.dateFormat")}
            <input value={editing.date_format ?? ""} onChange={(e) => set({ date_format: e.target.value })} />
          </label>
          {editing.file_kind !== "pdf" &&
            COLUMNS.map((name) => (
              <label key={name}>
                {t(`bs.columns.${name}`)}
                <input value={(editing[name] as string) ?? ""} onChange={(e) => set({ [name]: e.target.value } as Partial<StatementTemplate>)} />
              </label>
            ))}
          <label className="check">
            <input type="checkbox" checked={editing.checked ?? false} onChange={(e) => set({ checked: e.target.checked })} />
            {t("bs.checkedLabel")}
          </label>
          <label className="check">
            <input type="checkbox" checked={editing.is_active ?? true} onChange={(e) => set({ is_active: e.target.checked })} />
            {t("bs.active")}
          </label>
          <div className="wide row-actions">
            <button type="submit" disabled={save.isPending}>
              {t("bs.saveTemplate")}
            </button>
            <button type="button" className="secondary" onClick={() => setEditing(null)}>
              {t("common.cancel")}
            </button>
          </div>
          <ErrorLine error={save.error} />
        </form>
      )}
    </section>
  );
}
