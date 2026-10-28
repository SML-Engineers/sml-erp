import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can } from "../api/access";
import { chartKey, listLedgerAccounts } from "../api/accounts";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import {
  addTaxRate,
  calculateTax,
  createCode,
  createComponent,
  deleteCode,
  getTaxes,
  removeTaxRate,
  taxesKey,
  updateCode,
  updateComponent,
  type TaxBase,
  type TaxCode,
  type TaxComponent,
  type TaxKind,
  type TaxOverview,
  type TaxUse,
} from "../api/taxes";
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

function useSave() {
  const queryClient = useQueryClient();
  return (data: TaxOverview) => queryClient.setQueryData(taxesKey, data);
}

type Selection = { kind: "component"; id: number } | { kind: "code"; id: number | null } | { kind: "new-tax" } | null;

/** Accounts → Taxes (P0-20): taxes with their dated rates, and the tax codes made of them. */
export default function TaxesPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const data = useQuery({ queryKey: taxesKey, queryFn: getTaxes });
  const canManage = can(me.access, "accounting", "manage");
  const [selected, setSelected] = useState<Selection>(null);
  const overview = data.data;
  const component = selected?.kind === "component" ? overview?.components.find((c) => c.id === selected.id) : undefined;
  const code =
    selected?.kind === "code" && selected.id !== null ? overview?.codes.find((c) => c.id === selected.id) : undefined;

  return (
    <main className="page">
      <h1>{t("taxes.title")}</h1>
      <p className="muted">{t("taxes.help")}</p>
      {overview && (
        <>
          <section className="panel" aria-label={t("taxes.components")}>
            <h2>{t("taxes.components")}</h2>
            <div className="table-wrap">
              <table aria-label={t("taxes.components")}>
                <thead>
                  <tr>
                    <th>{t("taxes.code")}</th>
                    <th>{t("taxes.name")}</th>
                    <th>{t("taxes.kind")}</th>
                    <th className="num">{t("taxes.currentRate")}</th>
                    <th>{t("users.status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.components.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <button type="button" className="link-button" onClick={() => setSelected({ kind: "component", id: c.id })}>
                          {c.code}
                        </button>
                      </td>
                      <td>{c.name}</td>
                      <td>{t(`taxes.kinds.${c.kind}`)}</td>
                      <td className="num">{c.current_rate === null ? t("taxes.noRate") : `${c.current_rate}%`}</td>
                      <td>{c.is_active ? t("taxes.active") : t("taxes.off")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {canManage && (
              <button type="button" className="secondary" onClick={() => setSelected({ kind: "new-tax" })}>
                {t("taxes.addTax")}
              </button>
            )}
          </section>

          <section className="panel" aria-label={t("taxes.codes")}>
            <h2>{t("taxes.codes")}</h2>
            <p className="muted">{t("taxes.codesHelp")}</p>
            <div className="table-wrap">
              <table aria-label={t("taxes.codes")}>
                <thead>
                  <tr>
                    <th>{t("taxes.code")}</th>
                    <th>{t("taxes.name")}</th>
                    <th>{t("taxes.makeUp")}</th>
                    <th>{t("users.status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.codes.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <button type="button" className="link-button" onClick={() => setSelected({ kind: "code", id: c.id })}>
                          {c.code}
                        </button>
                      </td>
                      <td>{c.name}</td>
                      <td>
                        <MakeUp code={c} />
                      </td>
                      <td>{c.is_active ? t("taxes.active") : t("taxes.off")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {canManage && (
              <button type="button" className="secondary" onClick={() => setSelected({ kind: "code", id: null })}>
                {t("taxes.addCode")}
              </button>
            )}
          </section>

          {selected?.kind === "new-tax" && canManage && <NewTax />}
          {component && <ComponentPanel key={component.id} component={component} canManage={canManage} />}
          {selected?.kind === "code" && (selected.id === null || code) && (
            <CodePanel
              key={selected.id ?? "new"}
              code={code}
              components={overview.components}
              canManage={canManage}
              onGone={() => setSelected(null)}
            />
          )}
          <Calculator codes={overview.codes} />
        </>
      )}
      <ErrorLine error={data.error} />
    </main>
  );
}

function MakeUp({ code }: { code: TaxCode }) {
  const { t } = useTranslation();
  if (!code.components.length) return <>{t("taxes.noTax")}</>;
  return (
    <>
      {code.components
        .map((part, index) =>
          index > 0 && part.base === "net_and_tax" ? `${part.code} (${t("taxes.onNetAndTax")})` : part.code,
        )
        .join(" → ")}
    </>
  );
}

function NewTax() {
  const { t } = useTranslation();
  const save = useSave();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<TaxKind>("charged");
  const create = useMutation({ mutationFn: () => createComponent({ code, name, kind }), onSuccess: save });
  return (
    <form
      className="panel form-grid"
      aria-label={t("taxes.addTax")}
      onSubmit={(e) => {
        e.preventDefault();
        create.mutate();
      }}
    >
      <h2 className="wide">{t("taxes.addTax")}</h2>
      <label>
        {t("taxes.code")}
        <input value={code} required maxLength={20} onChange={(e) => setCode(e.target.value)} />
      </label>
      <label>
        {t("taxes.name")}
        <input value={name} required onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        {t("taxes.kind")}
        <select value={kind} onChange={(e) => setKind(e.target.value as TaxKind)}>
          <option value="charged">{t("taxes.kinds.charged")}</option>
          <option value="withheld">{t("taxes.kinds.withheld")}</option>
        </select>
      </label>
      <div className="wide">
        <button type="submit" disabled={create.isPending}>
          {t("taxes.addTax")}
        </button>
      </div>
      <div className="wide">
        <ErrorLine error={create.error} />
      </div>
    </form>
  );
}

function ComponentPanel({ component, canManage }: { component: TaxComponent; canManage: boolean }) {
  const { t } = useTranslation();
  const save = useSave();
  const accounts = useQuery({ queryKey: [...chartKey, "accounts", false], queryFn: () => listLedgerAccounts(false), enabled: canManage });
  const [from, setFrom] = useState("");
  const [rate, setRate] = useState("");
  const [reason, setReason] = useState("");
  const [name, setName] = useState(component.name);
  const [sales, setSales] = useState(component.sales_account ? String(component.sales_account.id) : "");
  const [purchases, setPurchases] = useState(component.purchase_account ? String(component.purchase_account.id) : "");
  const add = useMutation({ mutationFn: () => addTaxRate(component.id, from, rate, reason), onSuccess: save });
  const remove = useMutation({ mutationFn: (id: number) => removeTaxRate(component.id, id, reason), onSuccess: save });
  const update = useMutation({
    mutationFn: (change: { is_active?: boolean }) =>
      updateComponent(component.id, {
        name,
        sales_account: sales ? Number(sales) : null,
        purchase_account: purchases ? Number(purchases) : null,
        reason,
        ...change,
      }),
    onSuccess: save,
  });
  const title = `${component.code} – ${component.name}`;
  const accountOptions = (accounts.data ?? []).map((a) => (
    <option key={a.id} value={a.id}>
      {`${a.number} ${a.full_name}`.trim()}
    </option>
  ));

  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      {component.in_use && <p className="muted">{t("taxes.inUse")}</p>}
      <h3>{t("taxes.rates")}</h3>
      {component.rates.length === 0 && <p className="form-error">{t("taxes.enterRate")}</p>}
      <div className="table-wrap">
        <table aria-label={t("taxes.ratesOf", { code: component.code })}>
          <thead>
            <tr>
              <th>{t("taxes.from")}</th>
              <th className="num">{t("taxes.rate")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {component.rates.map((r) => (
              <tr key={r.id}>
                <td>{r.effective_from}</td>
                <td className="num">{r.rate}%</td>
                <td>
                  {canManage && !(r.in_force && component.in_use) && (
                    <button type="button" className="small secondary" onClick={() => remove.mutate(r.id)}>
                      {t("taxes.removeRate")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canManage && (
        <>
          <label className="inline-form">
            {t("access.reason")}
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <form
            className="inline-form"
            aria-label={t("taxes.addRate")}
            onSubmit={(e) => {
              e.preventDefault();
              add.mutate();
            }}
          >
            <label>
              {t("taxes.from")}
              <input type="date" value={from} required onChange={(e) => setFrom(e.target.value)} />
            </label>
            <label>
              {t("taxes.ratePercent")}
              <input inputMode="decimal" value={rate} required onChange={(e) => setRate(e.target.value)} />
            </label>
            <button type="submit" disabled={add.isPending}>
              {t("taxes.addRate")}
            </button>
          </form>
          <form
            className="form-grid"
            aria-label={t("taxes.editTax")}
            onSubmit={(e) => {
              e.preventDefault();
              update.mutate({});
            }}
          >
            <label>
              {t("taxes.name")}
              <input value={name} required onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              {t("taxes.salesAccount")}
              <select value={sales} onChange={(e) => setSales(e.target.value)}>
                <option value="">—</option>
                {accountOptions}
              </select>
            </label>
            <label>
              {t("taxes.purchaseAccount")}
              <select value={purchases} onChange={(e) => setPurchases(e.target.value)}>
                <option value="">{t("taxes.partOfCost")}</option>
                {accountOptions}
              </select>
            </label>
            <div className="wide row-actions">
              <button type="submit" disabled={update.isPending}>
                {t("taxes.save")}
              </button>
              <button type="button" className="secondary" onClick={() => update.mutate({ is_active: !component.is_active })}>
                {component.is_active ? t("taxes.switchOff") : t("taxes.switchOn")}
              </button>
            </div>
          </form>
        </>
      )}
      <ErrorLine error={add.error ?? remove.error ?? update.error} />
    </section>
  );
}

const USES: TaxUse[] = ["both", "sales", "purchases"];

function CodePanel(props: { code?: TaxCode; components: TaxComponent[]; canManage: boolean; onGone: () => void }) {
  const { t } = useTranslation();
  const save = useSave();
  const { code } = props;
  const [values, setValues] = useState({
    code: code?.code ?? "",
    name: code?.name ?? "",
    use: code?.use ?? ("both" as TaxUse),
  });
  const [parts, setParts] = useState<{ component: number; base: TaxBase }[]>(
    code?.components.map((p) => ({ component: p.component, base: p.base })) ?? [],
  );
  const [reason, setReason] = useState("");
  const charged = props.components.filter((c) => c.kind === "charged");
  const locked = Boolean(code?.in_use) || !props.canManage;
  const saveCode = useMutation({
    mutationFn: () => {
      const change = { ...values, components: parts, reason };
      return code ? updateCode(code.id, change) : createCode(change);
    },
    onSuccess: save,
  });
  const toggle = useMutation({
    mutationFn: () => updateCode(code!.id, { is_active: !code!.is_active, reason }),
    onSuccess: save,
  });
  const remove = useMutation({
    mutationFn: () => deleteCode(code!.id, reason),
    onSuccess: (data) => {
      save(data);
      props.onGone();
    },
  });
  const title = code ? `${code.code} – ${code.name}` : t("taxes.addCode");

  function submit(event: FormEvent) {
    event.preventDefault();
    saveCode.mutate();
  }

  return (
    <section className="panel" aria-label={title}>
      <h2>{title}</h2>
      {code?.in_use && <p className="muted">{t("taxes.codeInUse")}</p>}
      <form className="form-grid" aria-label={t("taxes.codeForm")} onSubmit={submit}>
        <label>
          {t("taxes.code")}
          <input
            value={values.code}
            required
            disabled={!props.canManage || Boolean(code?.in_use)}
            onChange={(e) => setValues((v) => ({ ...v, code: e.target.value }))}
          />
        </label>
        <label>
          {t("taxes.name")}
          <input value={values.name} required disabled={!props.canManage} onChange={(e) => setValues((v) => ({ ...v, name: e.target.value }))} />
        </label>
        <label>
          {t("taxes.use")}
          <select value={values.use} disabled={!props.canManage} onChange={(e) => setValues((v) => ({ ...v, use: e.target.value as TaxUse }))}>
            {USES.map((u) => (
              <option key={u} value={u}>
                {t(`taxes.uses.${u}`)}
              </option>
            ))}
          </select>
        </label>
        <div className="wide" role="group" aria-label={t("taxes.taxesInCode")}>
          <p>{t("taxes.taxesInCode")}</p>
          {parts.length === 0 && <p className="muted">{t("taxes.noTax")}</p>}
          {parts.map((part, index) => (
            <div className="inline-form" key={index}>
              <label>
                {t("taxes.taxNumber", { n: String(index + 1) })}
                <select
                  value={part.component}
                  disabled={locked}
                  onChange={(e) =>
                    setParts((now) => now.map((p, i) => (i === index ? { ...p, component: Number(e.target.value) } : p)))
                  }
                >
                  {charged.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.code}
                    </option>
                  ))}
                </select>
              </label>
              {index > 0 && (
                <label>
                  {t("taxes.chargedOn")}
                  <select
                    value={part.base}
                    disabled={locked}
                    onChange={(e) =>
                      setParts((now) => now.map((p, i) => (i === index ? { ...p, base: e.target.value as TaxBase } : p)))
                    }
                  >
                    <option value="net">{t("taxes.onNet")}</option>
                    <option value="net_and_tax">{t("taxes.onNetAndTax")}</option>
                  </select>
                </label>
              )}
              {!locked && (
                <button type="button" className="small secondary" onClick={() => setParts((now) => now.filter((_, i) => i !== index))}>
                  {t("taxes.removeTax")}
                </button>
              )}
            </div>
          ))}
          {!locked && charged.length > 0 && (
            <button
              type="button"
              className="small secondary"
              onClick={() => setParts((now) => [...now, { component: charged[0].id, base: "net" }])}
            >
              {t("taxes.addTaxToCode")}
            </button>
          )}
        </div>
        {props.canManage && (
          <>
            <label>
              {t("access.reason")}
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            <div className="wide row-actions">
              <button type="submit" disabled={saveCode.isPending}>
                {t("taxes.save")}
              </button>
              {code && (
                <button type="button" className="secondary" onClick={() => toggle.mutate()}>
                  {code.is_active ? t("taxes.switchOff") : t("taxes.switchOn")}
                </button>
              )}
              {code && !code.in_use && (
                <button type="button" className="danger" onClick={() => remove.mutate()}>
                  {t("taxes.delete")}
                </button>
              )}
            </div>
          </>
        )}
      </form>
      <ErrorLine error={saveCode.error ?? toggle.error ?? remove.error} />
    </section>
  );
}

function Calculator({ codes }: { codes: TaxCode[] }) {
  const { t } = useTranslation();
  const [code, setCode] = useState(codes[0]?.code ?? "");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");
  const calc = useMutation({ mutationFn: () => calculateTax(code, amount, date || undefined) });

  return (
    <section className="panel" aria-label={t("taxes.calculator")}>
      <h2>{t("taxes.calculator")}</h2>
      <form
        className="inline-form"
        aria-label={t("taxes.calculator")}
        onSubmit={(e) => {
          e.preventDefault();
          calc.mutate();
        }}
      >
        <label>
          {t("taxes.code")}
          <select value={code} onChange={(e) => setCode(e.target.value)}>
            {codes.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("taxes.amount")}
          <input inputMode="decimal" value={amount} required onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label>
          {t("taxes.onDate")}
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <button type="submit" className="secondary">
          {t("taxes.calculate")}
        </button>
      </form>
      {calc.data && (
        <table aria-label={t("taxes.result")}>
          <tbody>
            <tr>
              <td>{t("taxes.net")}</td>
              <td className="num">{formatDecimal(calc.data.net)}</td>
            </tr>
            {calc.data.lines.map((line) => (
              <tr key={line.code}>
                <td>
                  {line.code} {line.rate}%
                </td>
                <td className="num">{formatDecimal(line.amount)}</td>
              </tr>
            ))}
            <tr>
              <th>{t("taxes.gross")}</th>
              <th className="num">{formatDecimal(calc.data.gross)}</th>
            </tr>
          </tbody>
        </table>
      )}
      <ErrorLine error={calc.error} />
    </section>
  );
}
