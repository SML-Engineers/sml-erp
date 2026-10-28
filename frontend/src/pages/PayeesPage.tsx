import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can, canDo } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import {
  PAYEE_CATEGORIES,
  acknowledgeBankChange,
  addBankAccount,
  createPayee,
  listBankAccounts,
  listPayees,
  payeesKey,
  updateBankAccount,
  updatePayee,
  type BankAccount,
  type Payee,
  type PayeeChange,
} from "../api/payees";
import DataTable from "../components/DataTable";

function warningsOf(error: unknown): string[] {
  if (!(error instanceof ApiError) || error.status !== 409) return [];
  return (error.body as { warnings?: string[] } | null)?.warnings ?? [];
}

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error || warningsOf(error).length) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

const FIELDS = [
  "name",
  "vat_no",
  "tin",
  "address",
  "phone",
  "email",
  "contact_person",
  "contact_phone",
] as const;

export default function PayeesPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [inactive, setInactive] = useState(false);
  const [selected, setSelected] = useState<number | "new" | null>(null);
  const payees = useQuery({
    queryKey: [...payeesKey, search, inactive],
    queryFn: () => listPayees(search, inactive),
  });
  const canEnter = can(me.access, "payees", "enter");
  const current = typeof selected === "number" ? payees.data?.find((p) => p.id === selected) : undefined;

  return (
    <main className="page">
      <h1>{t("payees.title")}</h1>
      <p className="muted">{t("payees.help")}</p>
      <div className="toolbar">
        <label className="inline-form">
          {t("table.search")}
          <input
            type="search"
            value={search}
            placeholder={t("payees.searchHint")}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label className="check">
          <input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} />
          {t("payees.showInactive")}
        </label>
        {canEnter && (
          <button type="button" onClick={() => setSelected("new")}>
            {t("payees.add")}
          </button>
        )}
      </div>

      {selected === "new" && <PayeeForm me={me} onDone={(id) => setSelected(id)} />}
      {current && <PayeeForm key={current.id} me={me} payee={current} onDone={() => setSelected(null)} />}
      {current && <BankAccounts me={me} payee={current} />}

      {payees.data && (
        <DataTable
          label={t("payees.title")}
          rows={payees.data}
          rowKey={(p) => p.id}
          searchable={false}
          columns={[
            { id: "code", header: t("divisions.code"), value: (p) => p.code },
            {
              id: "name",
              header: t("divisions.name"),
              value: (p) => p.name,
              cell: (p) => (
                <button type="button" className="link-button" onClick={() => setSelected(p.id)}>
                  {p.name}
                </button>
              ),
            },
            { id: "category", header: t("payees.category"), value: (p) => t(`payees.categories.${p.category}`) },
            { id: "vat", header: t("payees.field.vat_no"), value: (p) => p.vat_no },
            {
              id: "bank",
              header: t("payees.bank"),
              value: (p) => p.default_account?.bank_name ?? "",
              cell: (p) => (
                <>
                  {p.default_account ? `${p.default_account.bank_name} ${p.default_account.account_number}` : "—"}
                  {p.bank_change_pending && <span className="tag warning">{t("payees.bankChanged")}</span>}
                </>
              ),
            },
            {
              id: "status",
              header: t("users.status"),
              value: (p) => (p.is_active ? t("users.active") : t("users.inactive")),
            },
          ]}
        />
      )}
    </main>
  );
}

function PayeeForm(props: { me: CurrentUser; payee?: Payee; onDone: (id: number | null) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { payee, me } = props;
  const canEnter = can(me.access, "payees", "enter");
  const canManage = can(me.access, "payees", "manage");
  const [values, setValues] = useState<Record<string, string>>(() => {
    const start: Record<string, string> = {};
    for (const field of FIELDS) start[field] = payee?.[field] ?? "";
    start.category = payee?.category ?? "supplier";
    start.payment_terms_days = String(payee?.payment_terms_days ?? 30);
    start.notes = payee?.notes ?? "";
    return start;
  });
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const set = (field: string) => (value: string) => {
    setValues((now) => ({ ...now, [field]: value }));
    setConfirmed(false);
  };
  const change = (): PayeeChange => ({
    ...values,
    category: values.category as Payee["category"],
    payment_terms_days: Number(values.payment_terms_days),
    reason,
    confirm_duplicates: confirmed,
  });
  const done = (saved: Payee) => {
    void queryClient.invalidateQueries({ queryKey: payeesKey });
    props.onDone(payee ? null : saved.id);
  };
  const save = useMutation({
    mutationFn: () => (payee ? updatePayee(payee.id, change()) : createPayee(change())),
    onSuccess: done,
  });
  const toggle = useMutation({
    mutationFn: () => updatePayee(payee!.id, { is_active: !payee!.is_active, reason }),
    onSuccess: done,
  });
  const warnings = warningsOf(save.error);

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const title = payee ? `${payee.code} ${payee.name}` : t("payees.add");
  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      {payee?.bank_change_pending && (
        <p className="notice warning-text" role="status">
          {t("payees.bankChangedNotice", { by: payee.bank_changed_by ?? "", at: payee.bank_changed_at?.slice(0, 10) })}
        </p>
      )}
      <form className="form-grid" onSubmit={submit}>
        {FIELDS.map((field) => (
          <label key={field} className={field === "address" ? "wide" : undefined}>
            {t(`payees.field.${field}`)}
            <input
              value={values[field]}
              type={field === "email" ? "email" : "text"}
              required={field === "name"}
              disabled={!canEnter}
              onChange={(e) => set(field)(e.target.value)}
            />
          </label>
        ))}
        <label>
          {t("payees.category")}
          <select value={values.category} disabled={!canEnter} onChange={(e) => set("category")(e.target.value)}>
            {PAYEE_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {t(`payees.categories.${c}`)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("payees.field.payment_terms_days")}
          <input
            type="number"
            min={0}
            max={365}
            value={values.payment_terms_days}
            disabled={!canEnter}
            onChange={(e) => set("payment_terms_days")(e.target.value)}
          />
        </label>
        <label className="wide">
          {t("payees.field.notes")}
          <textarea rows={2} value={values.notes} disabled={!canEnter} onChange={(e) => set("notes")(e.target.value)} />
        </label>
        {canEnter && (
          <>
            <label className="wide">
              {t("access.reason")}
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            {warnings.length > 0 && (
              <div className="wide notice warning-text" role="alert">
                <ul>
                  {warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
                <label className="check">
                  <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                  {t("payees.confirmDuplicate")}
                </label>
              </div>
            )}
            <div className="wide row-actions">
              <button type="submit" disabled={save.isPending || (warnings.length > 0 && !confirmed)}>
                {t("divisions.save")}
              </button>
              {payee && canManage && (
                <button
                  type="button"
                  className={payee.is_active ? "danger" : "secondary"}
                  onClick={() => toggle.mutate()}
                >
                  {payee.is_active ? t("divisions.deactivate") : t("divisions.reactivate")}
                </button>
              )}
              <button type="button" className="secondary" onClick={() => props.onDone(null)}>
                {t("access.cancel")}
              </button>
            </div>
          </>
        )}
      </form>
      <ErrorLine error={save.error ?? toggle.error} />
    </section>
  );
}

function BankAccounts({ me, payee }: { me: CurrentUser; payee: Payee }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = [...payeesKey, payee.id, "bank"];
  const accounts = useQuery({ queryKey: key, queryFn: () => listBankAccounts(payee.id) });
  const canChange = canDo(me.access, "change_bank_details");
  const canAcknowledge = can(me.access, "payees", "manage");
  const [editing, setEditing] = useState<BankAccount | null>(null);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: payeesKey });
  };
  const acknowledge = useMutation({ mutationFn: () => acknowledgeBankChange(payee.id), onSuccess: refresh });

  return (
    <section className="panel" aria-label={t("payees.bankAccounts")}>
      <h2>{t("payees.bankAccounts")}</h2>
      {payee.bank_change_pending && canAcknowledge && (
        <button type="button" className="secondary small" onClick={() => acknowledge.mutate()}>
          {t("payees.acknowledge")}
        </button>
      )}
      {accounts.data && accounts.data.length === 0 && <p className="muted">{t("payees.noAccounts")}</p>}
      {accounts.data && accounts.data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("payees.bankName")}</th>
                <th>{t("payees.branch")}</th>
                <th>{t("payees.accountName")}</th>
                <th>{t("payees.accountNumber")}</th>
                <th>SWIFT</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {accounts.data.map((a) => (
                <tr key={a.id} className={a.is_active ? undefined : "muted"}>
                  <td>
                    {a.bank_name}
                    {a.is_default && <span className="tag">{t("payees.default")}</span>}
                    {!a.is_active && <span className="tag">{t("payees.closed")}</span>}
                  </td>
                  <td>{a.branch}</td>
                  <td>{a.account_name}</td>
                  <td className="mono">{a.account_number}</td>
                  <td>{a.swift_code}</td>
                  <td>
                    {canChange && (
                      <button type="button" className="small secondary" onClick={() => setEditing(a)}>
                        {t("divisions.edit")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canChange ? (
        <AccountForm
          key={editing?.id ?? "new"}
          payeeId={payee.id}
          account={editing}
          onDone={() => {
            setEditing(null);
            refresh();
          }}
        />
      ) : (
        <p className="muted">{t("payees.bankOnlyAccountant")}</p>
      )}
      <ErrorLine error={acknowledge.error} />
    </section>
  );
}

function AccountForm(props: { payeeId: number; account: BankAccount | null; onDone: () => void }) {
  const { t } = useTranslation();
  const { account } = props;
  const [values, setValues] = useState({
    bank_name: account?.bank_name ?? "",
    branch: account?.branch ?? "",
    account_name: account?.account_name ?? "",
    account_number: account?.account_number ?? "",
    swift_code: account?.swift_code ?? "",
  });
  const [isDefault, setIsDefault] = useState(account?.is_default ?? false);
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () =>
      account
        ? updateBankAccount(props.payeeId, account.id, { ...values, is_default: isDefault, reason })
        : addBankAccount(props.payeeId, { ...values, is_default: isDefault, reason }),
    onSuccess: props.onDone,
  });
  const close = useMutation({
    mutationFn: () => updateBankAccount(props.payeeId, account!.id, { is_active: !account!.is_active, reason }),
    onSuccess: props.onDone,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const fields: [keyof typeof values, string][] = [
    ["bank_name", t("payees.bankName")],
    ["branch", t("payees.branch")],
    ["account_name", t("payees.accountName")],
    ["account_number", t("payees.accountNumber")],
    ["swift_code", "SWIFT / BIC"],
  ];
  const title = account ? t("payees.editAccount") : t("payees.addAccount");
  return (
    <form className="form-grid account-form" onSubmit={submit} aria-label={title}>
      <h3 className="wide">{title}</h3>
      {fields.map(([field, label]) => (
        <label key={field}>
          {label}
          <input
            value={values[field]}
            required={field !== "branch" && field !== "swift_code"}
            onChange={(e) => setValues((now) => ({ ...now, [field]: e.target.value }))}
          />
        </label>
      ))}
      <label className="check">
        <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)} />
        {t("payees.makeDefault")}
      </label>
      <label className="wide">
        {t("access.reason")}
        <input value={reason} required={!!account} onChange={(e) => setReason(e.target.value)} />
      </label>
      <div className="wide row-actions">
        <button type="submit" disabled={save.isPending}>
          {t("divisions.save")}
        </button>
        {account && (
          <>
            <button type="button" className="secondary" onClick={() => close.mutate()}>
              {account.is_active ? t("payees.closeAccount") : t("payees.reopenAccount")}
            </button>
            <button type="button" className="secondary" onClick={props.onDone}>
              {t("access.cancel")}
            </button>
          </>
        )}
      </div>
      <p className="wide muted">{t("payees.bankChangeHelp")}</p>
      <div className="wide">
        <ErrorLine error={save.error ?? close.error} />
      </div>
    </form>
  );
}
