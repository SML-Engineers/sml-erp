import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can } from "../api/access";
import {
  chartExportUrl,
  chartKey,
  createDetailType,
  createLedgerAccount,
  deleteDetailType,
  deleteLedgerAccount,
  importChart,
  listAccountTypes,
  listDetailTypes,
  listLedgerAccounts,
  mergeLedgerAccount,
  updateDetailType,
  updateLedgerAccount,
  type AccountType,
  type ChartImportResult,
  type LedgerAccount,
} from "../api/accounts";
import { listDivisions } from "../api/admin";
import { getTaxes, taxesKey } from "../api/taxes";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import DataTable from "../components/DataTable";

type Selection =
  | { kind: "account"; id: number }
  | { kind: "new" }
  | { kind: "import" }
  | { kind: "detail-types" }
  | null;

function errorText(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    const errors = (error.body as { errors?: string[] } | null)?.errors;
    if (errors?.length) return [error.detail, ...errors].filter(Boolean).join("\n");
    if (error.detail) return error.detail;
  }
  return fallback;
}

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error pre-line" role="alert">
      {errorText(error, t("common.error"))}
    </p>
  );
}

function useRefresh() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: chartKey });
}

/** The ids of an account's sub-accounts at every depth. */
function descendants(accounts: LedgerAccount[], id: number): Set<number> {
  const found = new Set<number>();
  let frontier = [id];
  while (frontier.length) {
    const next = accounts.filter((a) => a.parent !== null && frontier.includes(a.parent)).map((a) => a.id);
    frontier = next.filter((n) => !found.has(n));
    frontier.forEach((n) => found.add(n));
  }
  return found;
}

const label = (a: LedgerAccount) => (a.number ? `${a.number} ${a.full_name}` : a.full_name);

export default function ChartOfAccountsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [inactive, setInactive] = useState(false);
  const [typeFilter, setTypeFilter] = useState("");
  const [selected, setSelected] = useState<Selection>(null);
  const accounts = useQuery({
    queryKey: [...chartKey, "accounts", inactive],
    queryFn: () => listLedgerAccounts(inactive),
  });
  const types = useQuery({ queryKey: [...chartKey, "types"], queryFn: listAccountTypes });
  const canManage = can(me.access, "accounting", "manage");
  const rows = (accounts.data ?? []).filter((a) => !typeFilter || a.account_type === typeFilter);
  const current =
    selected?.kind === "account" ? accounts.data?.find((a) => a.id === selected.id) : undefined;

  return (
    <main className="page">
      <h1>{t("chart.title")}</h1>
      <p className="muted">{t("chart.help")}</p>
      <div className="toolbar">
        <label>
          {t("chart.type")}
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
            <option value="">{t("chart.allTypes")}</option>
            {types.data?.map((type) => (
              <option key={type.code} value={type.code}>
                {type.label}
              </option>
            ))}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} />
          {t("chart.showInactive")}
        </label>
        {canManage && (
          <>
            <button type="button" onClick={() => setSelected({ kind: "new" })}>
              {t("chart.new")}
            </button>
            <button type="button" className="secondary" onClick={() => setSelected({ kind: "detail-types" })}>
              {t("chart.detailTypes")}
            </button>
            <button type="button" className="secondary" onClick={() => setSelected({ kind: "import" })}>
              {t("chart.import")}
            </button>
          </>
        )}
        <a className="button-link secondary" href={chartExportUrl}>
          {t("chart.export")}
        </a>
      </div>

      {accounts.data && (
        <DataTable
          label={t("chart.title")}
          rows={rows}
          rowKey={(a) => a.id}
          pageSize="all"
          columns={[
            { id: "number", header: t("chart.number"), value: (a) => a.number, sortable: false },
            {
              id: "name",
              header: t("chart.name"),
              value: (a) => a.full_name,
              sortable: false,
              cell: (a) => (
                <span style={{ paddingLeft: `${a.depth * 1.25}rem` }}>
                  <button type="button" className="link-button" onClick={() => setSelected({ kind: "account", id: a.id })}>
                    {a.name}
                  </button>
                  {a.system_role && <span className="tag">{t("chart.system")}</span>}
                </span>
              ),
            },
            { id: "type", header: t("chart.type"), value: (a) => a.account_type_label, sortable: false },
            { id: "detail", header: t("chart.detailType"), value: (a) => a.detail_type.name },
            { id: "division", header: t("chart.division"), value: (a) => a.default_division ?? "" },
            {
              id: "status",
              header: t("users.status"),
              value: (a) =>
                a.merged_into
                  ? t("chart.mergedInto", { name: a.merged_into.name })
                  : a.is_active
                    ? t("chart.active")
                    : t("chart.inactive"),
            },
          ]}
        />
      )}
      <ErrorLine error={accounts.error} />

      {selected?.kind === "new" && canManage && types.data && accounts.data && (
        <AccountForm types={types.data} accounts={accounts.data} onSaved={(a) => setSelected({ kind: "account", id: a.id })} />
      )}
      {current && types.data && accounts.data && (
        <AccountPanel
          key={current.id}
          account={current}
          accounts={accounts.data}
          types={types.data}
          canManage={canManage}
          onGone={() => setSelected(null)}
        />
      )}
      {selected?.kind === "detail-types" && canManage && types.data && <DetailTypesPanel types={types.data} />}
      {selected?.kind === "import" && canManage && <ImportPanel />}
    </main>
  );
}

// --- Add and edit ------------------------------------------------------------------------

function AccountForm(props: {
  types: AccountType[];
  accounts: LedgerAccount[];
  account?: LedgerAccount;
  onSaved?: (account: LedgerAccount) => void;
}) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const { account, accounts, types } = props;
  const divisions = useQuery({ queryKey: [...chartKey, "divisions"], queryFn: listDivisions });
  const taxes = useQuery({ queryKey: taxesKey, queryFn: getTaxes });
  const [values, setValues] = useState({
    account_type: account?.account_type ?? types[0]?.code ?? "",
    detail_type: account ? String(account.detail_type.id) : "",
    name: account?.name ?? "",
    number: account?.number ?? "",
    parent: account?.parent ? String(account.parent) : "",
    description: account?.description ?? "",
    default_division: account?.default_division ?? "",
    default_tax_code: account?.default_tax_code ?? "",
    reason: "",
  });
  const set = (field: keyof typeof values) => (value: string) =>
    setValues((now) => ({
      ...now,
      [field]: value,
      // a new type has its own detail types and possible parents
      ...(field === "account_type" ? { detail_type: "", parent: "" } : {}),
    }));
  const type = types.find((x) => x.code === values.account_type);
  const details = (type?.detail_types ?? []).filter(
    (d) => d.is_active || String(d.id) === values.detail_type,
  );
  const excluded = useMemo(
    () => (account ? new Set([account.id, ...descendants(accounts, account.id)]) : new Set<number>()),
    [account, accounts],
  );
  const parents = accounts.filter(
    (a) => a.account_type === values.account_type && a.is_active && !a.merged_into && !excluded.has(a.id),
  );
  const save = useMutation({
    mutationFn: () => {
      const change = {
        account_type: values.account_type,
        detail_type: values.detail_type ? Number(values.detail_type) : null,
        name: values.name,
        number: values.number,
        parent: values.parent ? Number(values.parent) : null,
        description: values.description,
        default_division: values.default_division || null,
        default_tax_code: values.default_tax_code || null,
        reason: values.reason,
      };
      return account ? updateLedgerAccount(account.id, change) : createLedgerAccount(change);
    },
    onSuccess: (saved) => {
      refresh();
      props.onSaved?.(saved);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const typeLocked = Boolean(account?.system_role);
  return (
    <form className="form-grid" aria-label={account ? t("chart.edit") : t("chart.new")} onSubmit={submit}>
      <label>
        {t("chart.type")}
        <select
          value={values.account_type}
          disabled={typeLocked}
          onChange={(e) => set("account_type")(e.target.value)}
        >
          {types.map((x) => (
            <option key={x.code} value={x.code}>
              {x.label} ({x.section_label})
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("chart.detailType")}
        <select value={values.detail_type} required onChange={(e) => set("detail_type")(e.target.value)}>
          <option value="">—</option>
          {details.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("chart.name")}
        <input value={values.name} required maxLength={100} onChange={(e) => set("name")(e.target.value)} />
      </label>
      <label>
        {t("chart.numberOptional")}
        <input value={values.number} maxLength={20} onChange={(e) => set("number")(e.target.value)} />
      </label>
      <label>
        {t("chart.subAccountOf")}
        <select value={values.parent} onChange={(e) => set("parent")(e.target.value)}>
          <option value="">{t("chart.topLevel")}</option>
          {parents.map((a) => (
            <option key={a.id} value={a.id}>
              {label(a)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("chart.defaultDivision")}
        <select value={values.default_division} onChange={(e) => set("default_division")(e.target.value)}>
          <option value="">{t("chart.noDivision")}</option>
          {divisions.data?.map((d) => (
            <option key={d.code} value={d.code}>
              {d.code} {d.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("chart.defaultTaxCode")}
        <select value={values.default_tax_code} onChange={(e) => set("default_tax_code")(e.target.value)}>
          <option value="">{t("chart.noTaxCode")}</option>
          {taxes.data?.codes
            .filter((c) => c.is_active || c.code === values.default_tax_code)
            .map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} – {c.name}
              </option>
            ))}
        </select>
      </label>
      <label className="wide">
        {t("chart.description")}
        <input value={values.description} maxLength={500} onChange={(e) => set("description")(e.target.value)} />
      </label>
      {account && (
        <label>
          {t("access.reason")}
          <input value={values.reason} onChange={(e) => set("reason")(e.target.value)} />
        </label>
      )}
      <div className="wide">
        <button type="submit" disabled={save.isPending}>
          {account ? t("chart.save") : t("chart.add")}
        </button>
      </div>
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function AccountPanel(props: {
  account: LedgerAccount;
  accounts: LedgerAccount[];
  types: AccountType[];
  canManage: boolean;
  onGone: () => void;
}) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const { account, accounts } = props;
  const [reason, setReason] = useState("");
  const [into, setInto] = useState("");
  const toggle = useMutation({
    mutationFn: () => updateLedgerAccount(account.id, { is_active: !account.is_active, reason }),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => deleteLedgerAccount(account.id, reason),
    onSuccess: () => {
      refresh();
      props.onGone();
    },
  });
  const merge = useMutation({
    mutationFn: () => mergeLedgerAccount(account.id, Number(into), reason),
    onSuccess: refresh,
  });
  const below = useMemo(() => descendants(accounts, account.id), [accounts, account.id]);
  const targets = accounts.filter(
    (a) =>
      a.account_type === account.account_type &&
      a.id !== account.id &&
      a.is_active &&
      !a.merged_into &&
      !below.has(a.id),
  );
  const hasChildren = below.size > 0;
  const title = label(account);
  const editable = props.canManage && !account.merged_into;

  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      <p>
        {account.account_type_label} · {account.detail_type.name}
        {account.default_division && ` · ${account.default_division}`}
        {account.company_account && ` · ${t("chart.ledgerOf", { code: account.company_account })}`}
      </p>
      {account.description && <p>{account.description}</p>}
      {account.system_role && <p className="muted">{t("chart.systemHelp")}</p>}
      {account.in_use && <p className="muted">{t("chart.inUse")}</p>}
      {account.merged_into && (
        <p className="notice">{t("chart.mergedHelp", { name: account.merged_into.name })}</p>
      )}

      {editable && (
        <>
          <AccountForm types={props.types} accounts={accounts} account={account} />
          <h3>{t("chart.actions")}</h3>
          <div className="inline-form">
            <label>
              {t("access.reason")}
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            {!account.system_role && (
              <button
                type="button"
                className={account.is_active ? "danger" : "secondary"}
                onClick={() => toggle.mutate()}
              >
                {account.is_active ? t("chart.makeInactive") : t("chart.makeActive")}
              </button>
            )}
            {!account.system_role && !account.in_use && !hasChildren && (
              <button type="button" className="danger" onClick={() => remove.mutate()}>
                {t("chart.delete")}
              </button>
            )}
          </div>
          {!account.system_role && (
            <form
              className="inline-form"
              aria-label={t("chart.merge")}
              onSubmit={(e) => {
                e.preventDefault();
                merge.mutate();
              }}
            >
              <label>
                {t("chart.mergeInto")}
                <select value={into} required onChange={(e) => setInto(e.target.value)}>
                  <option value="">—</option>
                  {targets.map((a) => (
                    <option key={a.id} value={a.id}>
                      {label(a)}
                    </option>
                  ))}
                </select>
              </label>
              <button type="submit" className="secondary" disabled={merge.isPending}>
                {t("chart.merge")}
              </button>
            </form>
          )}
          <p className="muted">{t("chart.mergeHelp")}</p>
          <ErrorLine error={toggle.error ?? remove.error ?? merge.error} />
        </>
      )}
    </section>
  );
}

// --- Detail types ------------------------------------------------------------------------

function DetailTypesPanel({ types }: { types: AccountType[] }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [type, setType] = useState(types[0]?.code ?? "");
  const [name, setName] = useState("");
  const [names, setNames] = useState<Record<number, string>>({});
  const details = useQuery({ queryKey: [...chartKey, "detail-types"], queryFn: listDetailTypes });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: chartKey });
  const add = useMutation({
    mutationFn: () => createDetailType(type, name),
    onSuccess: () => {
      refresh();
      setName("");
    },
  });
  const change = useMutation({
    mutationFn: (args: { id: number; name?: string; is_active?: boolean }) =>
      updateDetailType(args.id, { name: args.name, is_active: args.is_active }),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: deleteDetailType, onSuccess: refresh });
  const rows = (details.data ?? []).filter((d) => d.account_type === type);

  return (
    <section className="panel" aria-label={t("chart.detailTypes")}>
      <h2>{t("chart.detailTypes")}</h2>
      <p className="muted">{t("chart.detailTypesHelp")}</p>
      <label>
        {t("chart.type")}
        <select value={type} onChange={(e) => setType(e.target.value)}>
          {types.map((x) => (
            <option key={x.code} value={x.code}>
              {x.label}
            </option>
          ))}
        </select>
      </label>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("chart.name")}</th>
              <th className="num">{t("chart.accountsUsing")}</th>
              <th>{t("users.status")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.id}>
                <td>
                  <input
                    aria-label={t("chart.renameDetail", { name: d.name })}
                    value={names[d.id] ?? d.name}
                    onChange={(e) => setNames((now) => ({ ...now, [d.id]: e.target.value }))}
                  />
                </td>
                <td className="num">{d.accounts}</td>
                <td>{d.is_active ? t("chart.active") : t("chart.inactive")}</td>
                <td className="row-actions">
                  {names[d.id] !== undefined && names[d.id] !== d.name && (
                    <button type="button" className="small" onClick={() => change.mutate({ id: d.id, name: names[d.id] })}>
                      {t("chart.rename")}
                    </button>
                  )}
                  <button
                    type="button"
                    className="small secondary"
                    onClick={() => change.mutate({ id: d.id, is_active: !d.is_active })}
                  >
                    {d.is_active ? t("chart.makeInactive") : t("chart.makeActive")}
                  </button>
                  {d.accounts === 0 && (
                    <button type="button" className="small danger" onClick={() => remove.mutate(d.id)}>
                      {t("chart.delete")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form
        className="inline-form"
        aria-label={t("chart.addDetail")}
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate();
        }}
      >
        <label>
          {t("chart.newDetailName")}
          <input value={name} required onChange={(e) => setName(e.target.value)} />
        </label>
        <button type="submit" disabled={add.isPending}>
          {t("chart.addDetail")}
        </button>
      </form>
      <ErrorLine error={add.error ?? change.error ?? remove.error} />
    </section>
  );
}

// --- Import ------------------------------------------------------------------------------

function ImportPanel() {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const [file, setFile] = useState<File | null>(null);
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<ChartImportResult | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) => importChart(file!, reason, dryRun),
    onSuccess: (data) => {
      setResult(data);
      if (!data.dry_run) refresh();
    },
    onError: () => setResult(null),
  });

  return (
    <section className="panel" aria-label={t("chart.import")}>
      <h2>{t("chart.import")}</h2>
      <p className="muted">{t("chart.importHelp")}</p>
      <div className="form-grid">
        <label>
          {t("factory.file")}
          <input
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setResult(null);
            }}
          />
        </label>
        <label>
          {t("access.reason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <div className="wide row-actions">
          <button type="button" className="secondary" disabled={!file || run.isPending} onClick={() => run.mutate(true)}>
            {t("factory.check")}
          </button>
          <button type="button" disabled={!file || run.isPending} onClick={() => run.mutate(false)}>
            {t("factory.doImport")}
          </button>
        </div>
      </div>
      {result && (
        <p className="notice" role="status">
          {t(result.dry_run ? "chart.checked" : "chart.imported", { ...result })}
        </p>
      )}
      <ErrorLine error={run.error} />
    </section>
  );
}
