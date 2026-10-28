import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can, canDo } from "../api/access";
import type { CurrentUser } from "../api/auth";
import {
  ACCOUNT_KINDS,
  accountsKey,
  addChequeBook,
  closeChequeBook,
  createAccount,
  getRegister,
  listAccounts,
  listCustodians,
  listDefaults,
  listLedgers,
  setDefault,
  spoilCheque,
  updateAccount,
  type AccountKind,
  type CompanyAccount,
  type LedgerChoice,
} from "../api/banking";
import { ApiError } from "../api/client";
import DataTable from "../components/DataTable";
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

function useRefresh() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: accountsKey });
}

export default function BankAccountsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [closed, setClosed] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const accounts = useQuery({ queryKey: [...accountsKey, closed], queryFn: () => listAccounts(closed) });
  const canManage = can(me.access, "banking", "manage");
  const canSpoil = canManage || canDo(me.access, "record_payment");
  const current = accounts.data?.find((a) => a.id === selected);

  return (
    <main className="page">
      <h1>{t("banking.title")}</h1>
      <p className="muted">{t("banking.help")}</p>
      <label className="check">
        <input type="checkbox" checked={closed} onChange={(e) => setClosed(e.target.checked)} />
        {t("banking.showClosed")}
      </label>

      {accounts.data && (
        <DataTable
          label={t("banking.title")}
          rows={accounts.data}
          rowKey={(a) => a.id}
          pageSize="all"
          searchable={false}
          columns={[
            {
              id: "code",
              header: t("divisions.code"),
              value: (a) => a.code,
              cell: (a) => (
                <button type="button" className="link-button" onClick={() => setSelected(a.id)}>
                  {a.code}
                </button>
              ),
            },
            { id: "name", header: t("divisions.name"), value: (a) => a.name },
            { id: "kind", header: t("banking.kind"), value: (a) => t(`banking.kinds.${a.kind}`) },
            {
              id: "number",
              header: t("banking.bankAndNumber"),
              value: (a) => (a.bank_name ? `${a.bank_name} ${a.account_number}` : ""),
            },
            { id: "currency", header: t("currencies.currency"), value: (a) => a.currency },
            {
              id: "default",
              header: t("banking.defaultFor"),
              value: (a) => a.default_for.join(", "),
            },
            {
              id: "status",
              header: t("users.status"),
              value: (a) => (a.is_active ? t("banking.open") : t("banking.closed")),
            },
          ]}
        />
      )}

      {current && <AccountPanel key={current.id} account={current} canManage={canManage} canSpoil={canSpoil} />}
      {canManage && <AddAccount />}
      <DivisionDefaults canManage={canManage} accounts={accounts.data ?? []} />
    </main>
  );
}

function AddAccount() {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const custodians = useQuery({ queryKey: [...accountsKey, "custodians"], queryFn: listCustodians });
  const ledgers = useQuery({ queryKey: [...accountsKey, "ledgers"], queryFn: listLedgers });
  const [kind, setKind] = useState<AccountKind>("current");
  const [values, setValues] = useState<Record<string, string>>({
    code: "",
    name: "",
    bank_name: "",
    branch: "",
    account_number: "",
    currency: "LKR",
    custodian: "",
    float_amount: "",
    division: "",
    ledger_account: "",
  });
  const set = (field: string) => (value: string) => setValues((now) => ({ ...now, [field]: value }));
  const isBank = kind === "current" || kind === "savings";
  const save = useMutation({
    mutationFn: () =>
      createAccount({
        code: values.code,
        name: values.name,
        kind,
        currency: values.currency,
        division: values.division,
        ledger_account: values.ledger_account ? Number(values.ledger_account) : null,
        ...(isBank
          ? { bank_name: values.bank_name, branch: values.branch, account_number: values.account_number }
          : {}),
        ...(kind === "petty_cash"
          ? { custodian: values.custodian ? Number(values.custodian) : null, float_amount: values.float_amount }
          : {}),
      }),
    onSuccess: () => {
      refresh();
      setValues((now) => ({ ...now, code: "", name: "", account_number: "", float_amount: "", ledger_account: "" }));
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const text = (field: string, label: string, required = false) => (
    <label key={field}>
      {label}
      <input value={values[field]} required={required} onChange={(e) => set(field)(e.target.value)} />
    </label>
  );

  return (
    <section className="panel" aria-label={t("banking.add")}>
      <h2>{t("banking.add")}</h2>
      <form className="form-grid" onSubmit={submit}>
        <label>
          {t("banking.kind")}
          <select value={kind} onChange={(e) => setKind(e.target.value as AccountKind)}>
            {ACCOUNT_KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`banking.kinds.${k}`)}
              </option>
            ))}
          </select>
        </label>
        {text("code", t("divisions.code"), true)}
        {text("name", t("divisions.name"), true)}
        {text("currency", t("currencies.currency"), true)}
        {isBank && text("bank_name", t("payees.bankName"), true)}
        {isBank && text("branch", t("payees.branch"))}
        {isBank && text("account_number", t("payees.accountNumber"), true)}
        {kind === "petty_cash" && (
          <>
            <label>
              {t("banking.custodian")}
              <select value={values.custodian} required onChange={(e) => set("custodian")(e.target.value)}>
                <option value="">—</option>
                {custodians.data?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            {text("float_amount", t("banking.float"), true)}
          </>
        )}
        {text("division", t("banking.divisionOptional"))}
        <LedgerSelect
          value={values.ledger_account}
          choices={ledgers.data ?? []}
          onChange={set("ledger_account")}
        />
        <div className="wide">
          <button type="submit" disabled={save.isPending}>
            {t("banking.add")}
          </button>
        </div>
      </form>
      <ErrorLine error={save.error} />
    </section>
  );
}

function AccountPanel(props: { account: CompanyAccount; canManage: boolean; canSpoil: boolean }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const { account } = props;
  const [reason, setReason] = useState("");
  const toggle = useMutation({
    mutationFn: () => updateAccount(account.id, { is_active: !account.is_active, reason }),
    onSuccess: refresh,
  });
  const title = `${account.code} ${account.name}`;

  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      <p>
        {t(`banking.kinds.${account.kind}`)}
        {account.bank_name && ` · ${account.bank_name}, ${account.branch} · ${account.account_number}`}
        {` · ${account.currency}`}
        {account.custodian && ` · ${t("banking.custodian")}: ${account.custodian.name}`}
        {account.float_amount && ` · ${t("banking.float")}: ${formatDecimal(account.float_amount)}`}
      </p>
      <p>
        {t("banking.ledger")}:{" "}
        {account.ledger_account
          ? `${account.ledger_account.number} ${account.ledger_account.name}`.trim()
          : t("banking.noLedger")}
      </p>
      {account.in_use && <p className="muted">{t("banking.inUse")}</p>}
      {props.canManage && !(account.in_use && account.ledger_account) && <LedgerLink account={account} />}
      {props.canManage && (
        <div className="inline-form">
          <label>
            {t("access.reason")}
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="button" className={account.is_active ? "danger" : "secondary"} onClick={() => toggle.mutate()}>
            {account.is_active ? t("banking.close") : t("banking.reopen")}
          </button>
        </div>
      )}
      <ErrorLine error={toggle.error} />
      {account.kind === "current" && (
        <ChequeBooks account={account} canManage={props.canManage} canSpoil={props.canSpoil} />
      )}
    </section>
  );
}

function LedgerSelect(props: { value: string; choices: LedgerChoice[]; onChange: (value: string) => void; own?: number }) {
  const { t } = useTranslation();
  return (
    <label>
      {t("banking.ledger")}
      <select value={props.value} onChange={(e) => props.onChange(e.target.value)}>
        <option value="">{t("banking.noLedger")}</option>
        {props.choices
          .filter((c) => !c.linked_to || c.id === props.own)
          .map((c) => (
            <option key={c.id} value={c.id}>
              {`${c.number} ${c.name}`.trim()}
            </option>
          ))}
      </select>
    </label>
  );
}

/** Link the account to its Bank-type ledger account (fixed once the account is used). */
function LedgerLink({ account }: { account: CompanyAccount }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const ledgers = useQuery({ queryKey: [...accountsKey, "ledgers"], queryFn: listLedgers });
  const [value, setValue] = useState(account.ledger_account ? String(account.ledger_account.id) : "");
  const save = useMutation({
    mutationFn: () => updateAccount(account.id, { ledger_account: value ? Number(value) : null }),
    onSuccess: refresh,
  });
  return (
    <form
      className="inline-form"
      aria-label={t("banking.saveLedger")}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <LedgerSelect value={value} choices={ledgers.data ?? []} onChange={setValue} own={account.ledger_account?.id} />
      <button type="submit" className="secondary" disabled={save.isPending}>
        {t("banking.saveLedger")}
      </button>
      <p className="muted">{t("banking.ledgerHelp")}</p>
      <ErrorLine error={save.error} />
    </form>
  );
}

function ChequeBooks(props: { account: CompanyAccount; canManage: boolean; canSpoil: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { account } = props;
  const registerKey = [...accountsKey, account.id, "cheques"];
  const register = useQuery({ queryKey: registerKey, queryFn: () => getRegister(account.id) });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: accountsKey });
  };
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [digits, setDigits] = useState("6");
  const [spoilNumber, setSpoilNumber] = useState("");
  const [reason, setReason] = useState("");
  const add = useMutation({
    mutationFn: () =>
      addChequeBook(account.id, { first_number: Number(first), last_number: Number(last), digits: Number(digits) }),
    onSuccess: () => {
      refresh();
      setFirst("");
      setLast("");
    },
  });
  const close = useMutation({
    mutationFn: (bookId: number) => closeChequeBook(account.id, bookId, reason),
    onSuccess: refresh,
  });
  const spoil = useMutation({
    mutationFn: () => spoilCheque(account.id, Number(spoilNumber), reason),
    onSuccess: () => {
      refresh();
      setSpoilNumber("");
    },
  });

  return (
    <div aria-label={t("banking.chequeBooks")} role="group">
      <h3>{t("banking.chequeBooks")}</h3>
      {register.data && (
        <p>
          {t("banking.nextCheque")}: <strong className="mono">{register.data.next ?? t("banking.noLeaves")}</strong>
        </p>
      )}
      {account.cheque_books.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("banking.range")}</th>
                <th className="num">{t("banking.used")}</th>
                <th className="num">{t("banking.left")}</th>
                <th>{t("users.status")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {account.cheque_books.map((b) => (
                <tr key={b.id}>
                  <td className="mono">
                    {b.first}–{b.last}
                  </td>
                  <td className="num">{b.summary.used}</td>
                  <td className="num">{b.summary.left}</td>
                  <td>{b.is_active ? t("banking.open") : t("banking.closed")}</td>
                  <td>
                    {props.canManage && b.is_active && (
                      <button type="button" className="small secondary" onClick={() => close.mutate(b.id)}>
                        {t("banking.closeBook")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(props.canManage || props.canSpoil) && (
        <label className="inline-form">
          {t("access.reason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      )}
      {props.canManage && (
        <form
          className="inline-form"
          aria-label={t("banking.addBook")}
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <label>
            {t("banking.firstNumber")}
            <input inputMode="numeric" value={first} required onChange={(e) => setFirst(e.target.value)} />
          </label>
          <label>
            {t("banking.lastNumber")}
            <input inputMode="numeric" value={last} required onChange={(e) => setLast(e.target.value)} />
          </label>
          <label>
            {t("banking.digits")}
            <input type="number" min={1} max={12} value={digits} onChange={(e) => setDigits(e.target.value)} />
          </label>
          <button type="submit" disabled={add.isPending}>
            {t("banking.addBook")}
          </button>
        </form>
      )}
      {props.canSpoil && (
        <form
          className="inline-form"
          aria-label={t("banking.spoil")}
          onSubmit={(e) => {
            e.preventDefault();
            spoil.mutate();
          }}
        >
          <label>
            {t("banking.chequeNumber")}
            <input inputMode="numeric" value={spoilNumber} required onChange={(e) => setSpoilNumber(e.target.value)} />
          </label>
          <button type="submit" className="secondary" disabled={spoil.isPending}>
            {t("banking.spoil")}
          </button>
        </form>
      )}
      {register.data && register.data.used.length > 0 && (
        <details>
          <summary>{t("banking.register", { count: register.data.used.length })}</summary>
          <ul className="changes">
            {register.data.used.map((leaf) => (
              <li key={leaf.id}>
                <span className="mono">{leaf.number}</span> {t(`banking.leaf.${leaf.status}`)}
                {leaf.reason && ` — ${leaf.reason}`}
              </li>
            ))}
          </ul>
        </details>
      )}
      <ErrorLine error={add.error ?? close.error ?? spoil.error} />
    </div>
  );
}

function DivisionDefaults({ canManage, accounts }: { canManage: boolean; accounts: CompanyAccount[] }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const defaults = useQuery({ queryKey: [...accountsKey, "defaults"], queryFn: listDefaults });
  const save = useMutation({
    mutationFn: ({ division, account }: { division: string; account: number | null }) => setDefault(division, account),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: accountsKey }),
  });
  const banks = accounts.filter((a) => (a.kind === "current" || a.kind === "savings") && a.is_active);

  return (
    <section className="panel" aria-label={t("banking.defaults")}>
      <h2>{t("banking.defaults")}</h2>
      <p className="muted">{t("banking.defaultsHelp")}</p>
      <div className="form-grid">
        {defaults.data?.map((row) => (
          <label key={row.division}>
            {row.division}
            <select
              value={row.account?.id ?? ""}
              disabled={!canManage}
              onChange={(e) =>
                save.mutate({ division: row.division, account: e.target.value ? Number(e.target.value) : null })
              }
            >
              <option value="">{t("banking.noDefault")}</option>
              {banks.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.code} {a.name}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
      <ErrorLine error={save.error} />
    </section>
  );
}
