import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can, canDo } from "../api/access";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import {
  INCOTERMS,
  addContact,
  createCustomer,
  customersExportUrl,
  customersKey,
  importCustomers,
  listContacts,
  listCustomers,
  listPickerCurrencies,
  setCreditTerms,
  setCustomerActive,
  updateContact,
  updateCustomer,
  type Contact,
  type Customer,
  type CustomerChange,
  type CustomerImportResult,
} from "../api/customers";
import DataTable from "../components/DataTable";
import { formatDecimal } from "../lib/decimal";

function warningsOf(error: unknown): string[] {
  if (!(error instanceof ApiError) || error.status !== 409) return [];
  return (error.body as { warnings?: string[] } | null)?.warnings ?? [];
}

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error || warningsOf(error).length) return null;
  let text = t("common.error");
  if (error instanceof ApiError) {
    const rows = (error.body as { errors?: string[] } | null)?.errors;
    text = rows?.length ? [error.detail, ...rows].filter(Boolean).join("\n") : (error.detail ?? text);
  }
  return (
    <p className="form-error pre-line" role="alert">
      {text}
    </p>
  );
}

const TEXT_FIELDS = ["name", "vat_no", "tin", "phone", "email", "country", "port_of_destination"] as const;
const LONG_FIELDS = ["billing_address", "delivery_address", "notes"] as const;

/** Customers and their contacts (spec 5.4, 5.5): used on quotations, proformas and orders. */
export default function CustomersPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [inactive, setInactive] = useState(false);
  const [selected, setSelected] = useState<number | "new" | "import" | null>(null);
  const customers = useQuery({
    queryKey: [...customersKey, search, inactive],
    queryFn: () => listCustomers(search, inactive),
  });
  const canEnter = can(me.access, "sales", "enter");
  const current = typeof selected === "number" ? customers.data?.find((c) => c.id === selected) : undefined;

  return (
    <main className="page">
      <h1>{t("customers.title")}</h1>
      <p className="muted">{t("customers.help")}</p>
      <div className="toolbar">
        <label className="inline-form">
          {t("table.search")}
          <input type="search" value={search} placeholder={t("customers.searchHint")} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <label className="check">
          <input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} />
          {t("customers.showInactive")}
        </label>
        {canEnter && (
          <button type="button" onClick={() => setSelected("new")}>
            {t("customers.add")}
          </button>
        )}
        <a className="button-link secondary" href={customersExportUrl(inactive)}>
          {t("customers.export")}
        </a>
        {canEnter && (
          <button type="button" className="secondary" onClick={() => setSelected("import")}>
            {t("customers.import")}
          </button>
        )}
      </div>

      {selected === "import" && <ImportPanel onClose={() => setSelected(null)} />}
      {selected === "new" && <CustomerForm me={me} onDone={(id) => setSelected(id)} />}
      {current && <CustomerForm key={current.id} me={me} customer={current} onDone={() => setSelected(null)} />}
      {current && canDo(me.access, "set_credit_terms") && <CreditTerms key={`terms-${current.id}`} customer={current} />}
      {current && <Contacts key={`contacts-${current.id}`} me={me} customer={current} />}

      {customers.data && (
        <DataTable
          label={t("customers.title")}
          rows={customers.data}
          rowKey={(c) => c.id}
          searchable={false}
          emptyText={t("customers.none")}
          columns={[
            { id: "code", header: t("customers.code"), value: (c) => c.code },
            {
              id: "name",
              header: t("customers.field.name"),
              value: (c) => c.name,
              cell: (c) => (
                <button type="button" className="link-button" onClick={() => setSelected(c.id)}>
                  {c.name}
                </button>
              ),
            },
            { id: "contact", header: t("customers.mainContact"), value: (c) => c.main_contact?.name ?? "" },
            { id: "phone", header: t("customers.field.phone"), value: (c) => c.phone || c.main_contact?.phone || "" },
            { id: "currency", header: t("customers.currency"), value: (c) => c.currency },
            {
              id: "export",
              header: t("customers.exportCustomer"),
              value: (c) => (c.is_export ? c.country : ""),
            },
            {
              id: "status",
              header: t("users.status"),
              value: (c) => (c.is_active ? t("users.active") : t("users.inactive")),
            },
          ]}
        />
      )}
      <ErrorLine error={customers.error} />
    </main>
  );
}

function CustomerForm(props: { me: CurrentUser; customer?: Customer; onDone: (id: number | null) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { customer, me } = props;
  const canEnter = can(me.access, "sales", "enter");
  const canDeactivate = can(me.access, "sales", "approve");
  const currencies = useQuery({ queryKey: ["currencies", "picker"], queryFn: listPickerCurrencies });
  const currencyOptions: { code: string; name: string }[] = currencies.data ?? [{ code: customer?.currency ?? "LKR", name: "" }];
  const [values, setValues] = useState<Record<string, string>>(() => {
    const start: Record<string, string> = {};
    for (const field of [...TEXT_FIELDS, ...LONG_FIELDS]) start[field] = customer?.[field] ?? "";
    start.currency = customer?.currency ?? "LKR";
    start.payment_terms_days = String(customer?.payment_terms_days ?? 30);
    start.credit_limit = customer?.credit_limit ?? "";
    start.incoterm = customer?.incoterm ?? "";
    return start;
  });
  const [isExport, setIsExport] = useState(customer?.is_export ?? false);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const set = (field: string) => (value: string) => {
    setValues((now) => ({ ...now, [field]: value }));
    setConfirmed(false);
  };
  const change = (): CustomerChange => ({
    ...values,
    payment_terms_days: Number(values.payment_terms_days),
    credit_limit: values.credit_limit.trim() === "" ? null : values.credit_limit.trim(),
    is_export: isExport,
    reason,
    confirm_duplicates: confirmed,
  });
  const done = (saved: Customer) => {
    void queryClient.invalidateQueries({ queryKey: customersKey });
    props.onDone(customer ? null : saved.id);
  };
  const save = useMutation({
    mutationFn: () => (customer ? updateCustomer(customer.id, change()) : createCustomer(change())),
    onSuccess: done,
  });
  const toggle = useMutation({
    mutationFn: () => setCustomerActive(customer!.id, !customer!.is_active, reason),
    onSuccess: done,
  });
  const warnings = warningsOf(save.error);

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const title = customer ? `${customer.code} ${customer.name}` : t("customers.add");
  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      {customer?.credit_limit && (
        <p className="muted">
          {t("customers.creditLimitShown", { amount: formatDecimal(customer.credit_limit), currency: customer.currency })}
        </p>
      )}
      <form className="form-grid" onSubmit={submit}>
        {(["name", "vat_no", "tin", "phone", "email"] as const).map((field) => (
          <label key={field}>
            {t(`customers.field.${field}`)}
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
          {t("customers.currency")}
          <select value={values.currency} disabled={!canEnter} onChange={(e) => set("currency")(e.target.value)}>
            {currencyOptions.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name ? `${c.code} – ${c.name}` : c.code}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("customers.field.payment_terms_days")}
          <input
            type="number"
            min={0}
            max={365}
            value={values.payment_terms_days}
            disabled
            onChange={(e) => set("payment_terms_days")(e.target.value)}
          />
        </label>
        <label>
          {t("customers.field.credit_limit")}
          <input
            inputMode="decimal"
            className="num"
            value={values.credit_limit}
            placeholder={t("customers.noLimit")}
            disabled
            onChange={(e) => set("credit_limit")(e.target.value)}
          />
        </label>
        <p className="muted wide">{t("customers.termsByAccountant")}</p>
        <label className="wide">
          {t("customers.field.billing_address")}
          <textarea rows={2} value={values.billing_address} disabled={!canEnter} onChange={(e) => set("billing_address")(e.target.value)} />
        </label>
        <label className="wide">
          {t("customers.field.delivery_address")}
          <textarea
            rows={2}
            value={values.delivery_address}
            placeholder={t("customers.sameAsBilling")}
            disabled={!canEnter}
            onChange={(e) => set("delivery_address")(e.target.value)}
          />
        </label>
        <label className="check wide">
          <input type="checkbox" checked={isExport} disabled={!canEnter} onChange={(e) => setIsExport(e.target.checked)} />
          {t("customers.exportCustomer")}
        </label>
        {isExport && (
          <>
            <label>
              {t("customers.field.country")}
              <input value={values.country} required disabled={!canEnter} onChange={(e) => set("country")(e.target.value)} />
            </label>
            <label>
              {t("customers.field.incoterm")}
              <select value={values.incoterm} disabled={!canEnter} onChange={(e) => set("incoterm")(e.target.value)}>
                <option value="">—</option>
                {INCOTERMS.map((term) => (
                  <option key={term} value={term}>
                    {t(`customers.incoterms.${term}`)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t("customers.field.port_of_destination")}
              <input value={values.port_of_destination} disabled={!canEnter} onChange={(e) => set("port_of_destination")(e.target.value)} />
            </label>
          </>
        )}
        <label className="wide">
          {t("customers.field.notes")}
          <textarea rows={2} value={values.notes} disabled={!canEnter} onChange={(e) => set("notes")(e.target.value)} />
        </label>
        {(canEnter || canDeactivate) && (
          <>
            {customer && (
              <label className="wide">
                {t("access.reason")}
                <input value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
            )}
            {warnings.length > 0 && (
              <div className="wide notice warning-text" role="alert">
                <ul>
                  {warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
                <label className="check">
                  <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                  {t("customers.confirmDuplicate")}
                </label>
              </div>
            )}
            <div className="wide row-actions">
              {canEnter && (
                <button type="submit" disabled={save.isPending || (warnings.length > 0 && !confirmed)}>
                  {t("divisions.save")}
                </button>
              )}
              {customer && canDeactivate && (
                <button type="button" className={customer.is_active ? "danger" : "secondary"} onClick={() => toggle.mutate()}>
                  {customer.is_active ? t("divisions.deactivate") : t("divisions.reactivate")}
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

function Contacts({ me, customer }: { me: CurrentUser; customer: Customer }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = [...customersKey, customer.id, "contacts"];
  const contacts = useQuery({ queryKey: key, queryFn: () => listContacts(customer.id) });
  const canEnter = can(me.access, "sales", "enter");
  const [editing, setEditing] = useState<Contact | null>(null);
  const refresh = () => {
    setEditing(null);
    void queryClient.invalidateQueries({ queryKey: customersKey });
  };
  const change = useMutation({
    mutationFn: ({ contact, values }: { contact: Contact; values: Partial<Contact> }) =>
      updateContact(customer.id, contact.id, values),
    onSuccess: refresh,
  });

  return (
    <section className="panel" aria-label={t("customers.contacts")}>
      <h2>{t("customers.contacts")}</h2>
      {contacts.data?.length === 0 && <p className="muted">{t("customers.noContacts")}</p>}
      {contacts.data && contacts.data.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("customers.contacts")}>
            <thead>
              <tr>
                <th>{t("customers.contact.name")}</th>
                <th>{t("customers.contact.position")}</th>
                <th>{t("customers.contact.phone")}</th>
                <th>{t("customers.contact.email")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {contacts.data.map((c) => (
                <tr key={c.id} className={c.is_active ? undefined : "muted"}>
                  <td>
                    {c.name}
                    {c.is_main && <span className="tag">{t("customers.main")}</span>}
                    {!c.is_active && <span className="tag">{t("customers.left")}</span>}
                  </td>
                  <td>{c.position}</td>
                  <td>{c.phone}</td>
                  <td>{c.email}</td>
                  <td>
                    {canEnter && (
                      <div className="row-actions">
                        <button type="button" className="small secondary" onClick={() => setEditing(c)}>
                          {t("divisions.edit")}
                        </button>
                        {c.is_active && !c.is_main && (
                          <button type="button" className="small secondary" onClick={() => change.mutate({ contact: c, values: { is_main: true } })}>
                            {t("customers.makeMain")}
                          </button>
                        )}
                        <button
                          type="button"
                          className="small secondary"
                          onClick={() => change.mutate({ contact: c, values: { is_active: !c.is_active } })}
                        >
                          {c.is_active ? t("customers.hasLeft") : t("customers.isBack")}
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {canEnter && <ContactForm key={editing?.id ?? "new"} customerId={customer.id} contact={editing} onDone={refresh} />}
      <ErrorLine error={change.error} />
    </section>
  );
}

function ContactForm(props: { customerId: number; contact: Contact | null; onDone: () => void }) {
  const { t } = useTranslation();
  const { contact } = props;
  const [values, setValues] = useState({
    name: contact?.name ?? "",
    position: contact?.position ?? "",
    phone: contact?.phone ?? "",
    email: contact?.email ?? "",
  });
  const save = useMutation({
    mutationFn: () => (contact ? updateContact(props.customerId, contact.id, values) : addContact(props.customerId, values)),
    onSuccess: () => {
      setValues({ name: "", position: "", phone: "", email: "" });
      props.onDone();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  const title = contact ? t("customers.editContact") : t("customers.addContact");
  return (
    <form className="form-grid" onSubmit={submit} aria-label={title}>
      <h3 className="wide">{title}</h3>
      {(["name", "position", "phone", "email"] as const).map((field) => (
        <label key={field}>
          {t(`customers.contact.${field}`)}
          <input
            value={values[field]}
            type={field === "email" ? "email" : "text"}
            required={field === "name"}
            onChange={(e) => setValues((now) => ({ ...now, [field]: e.target.value }))}
          />
        </label>
      ))}
      <div className="wide row-actions">
        <button type="submit" disabled={save.isPending}>
          {t("divisions.save")}
        </button>
        {contact && (
          <button type="button" className="secondary" onClick={props.onDone}>
            {t("access.cancel")}
          </button>
        )}
      </div>
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function ImportPanel({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<CustomerImportResult | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) => importCustomers(file!, reason, dryRun),
    onSuccess: (data) => {
      setResult(data);
      if (!data.dry_run) void queryClient.invalidateQueries({ queryKey: customersKey });
    },
    onError: () => setResult(null),
  });
  const counts = result ? { created: String(result.created), updated: String(result.updated) } : null;

  return (
    <section className="panel" aria-label={t("customers.import")}>
      <h2>{t("customers.import")}</h2>
      <p className="muted">{t("customers.importHelp")}</p>
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
          <button type="button" className="secondary" onClick={onClose}>
            {t("access.cancel")}
          </button>
        </div>
      </div>
      {result && counts && (
        <p className="notice" role="status">
          {t(result.dry_run ? "customers.checked" : "customers.imported", counts)}
        </p>
      )}
      <ErrorLine error={run.error} />
    </section>
  );
}

/** The credit limit and payment terms, changed only by the Accountant or the Director (owner,
 * 3 Nov 2026), so nobody lifts a credit hold by changing them. */
function CreditTerms({ customer }: { customer: Customer }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [limit, setLimit] = useState(customer.credit_limit ?? "");
  const [days, setDays] = useState(String(customer.payment_terms_days));
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => {
      const amount = limit.replace(/,/g, "").trim();
      return setCreditTerms(customer.id, amount === "" ? null : amount, Number(days), reason);
    },
    onSuccess: () => {
      setReason("");
      void queryClient.invalidateQueries({ queryKey: customersKey });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <section className="panel" aria-label={t("customers.creditTerms")}>
      <h2>{t("customers.creditTerms")}</h2>
      <form className="form-grid" onSubmit={submit}>
        <label>
          {t("customers.field.credit_limit")}
          <input inputMode="decimal" className="num" value={limit} placeholder={t("customers.noLimit")} onChange={(e) => setLimit(e.target.value)} />
        </label>
        <label>
          {t("customers.field.payment_terms_days")}
          <input type="number" min={0} max={365} required value={days} onChange={(e) => setDays(e.target.value)} />
        </label>
        <label className="wide">
          {t("access.reason")}
          <input value={reason} required onChange={(e) => setReason(e.target.value)} />
        </label>
        <div className="wide">
          <button type="submit" disabled={save.isPending}>
            {t("customers.saveTerms")}
          </button>
        </div>
      </form>
      <ErrorLine error={save.error} />
    </section>
  );
}
