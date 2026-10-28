import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can } from "../../api/access";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";
import {
  createCurrency,
  currencyKeys,
  enterRate,
  importRates,
  listCurrencies,
  listRates,
  updateCurrency,
  type Currency,
  type ExchangeRate,
  type RateImportResult,
} from "../../api/currencies";
import DataTable from "../../components/DataTable";
import { formatDecimal } from "../../lib/decimal";

type Tab = "currencies" | "rates";

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

const localToday = () => new Date().toLocaleDateString("en-CA");

function useRefresh() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: ["settings"] });
}

export default function CurrenciesPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("currencies");
  const tabs: Tab[] = ["currencies", "rates"];
  return (
    <main className="page">
      <h1>{t("currencies.title")}</h1>
      <p className="muted">{t("currencies.help")}</p>
      <div className="tabs" role="tablist" aria-label={t("currencies.title")}>
        {tabs.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={tab === name}
            className={tab === name ? "tab active" : "tab"}
            onClick={() => setTab(name)}
          >
            {t(`currencies.tab.${name}`)}
          </button>
        ))}
      </div>
      {tab === "currencies" && <CurrenciesTab canManage={can(me.access, "settings", "manage")} />}
      {tab === "rates" && <RatesTab canEnter={can(me.access, "accounting", "enter")} />}
    </main>
  );
}

// --- Currencies --------------------------------------------------------------------------

function CurrenciesTab({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const list = useQuery({ queryKey: currencyKeys.list, queryFn: listCurrencies });
  const [reason, setReason] = useState("");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [symbol, setSymbol] = useState("");
  const [places, setPlaces] = useState("2");
  const toggle = useMutation({
    mutationFn: (c: Currency) => updateCurrency(c.code, { is_active: !c.is_active, reason }),
    onSuccess: refresh,
  });
  const add = useMutation({
    mutationFn: () => createCurrency({ code, name, symbol, decimal_places: Number(places) }),
    onSuccess: () => {
      refresh();
      setCode("");
      setName("");
      setSymbol("");
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <>
      {canManage && (
        <section className="panel" aria-label={t("currencies.add")}>
          <h2>{t("currencies.add")}</h2>
          <form className="inline-form" onSubmit={submit}>
            <label>
              {t("currencies.code")}
              <input className="code-input" value={code} maxLength={3} required onChange={(e) => setCode(e.target.value.toUpperCase())} />
            </label>
            <label>
              {t("divisions.name")}
              <input value={name} required onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              {t("currencies.symbol")}
              <input className="code-input" value={symbol} maxLength={8} onChange={(e) => setSymbol(e.target.value)} />
            </label>
            <label>
              {t("currencies.decimals")}
              <input type="number" min={0} max={4} value={places} onChange={(e) => setPlaces(e.target.value)} />
            </label>
            <button type="submit" disabled={add.isPending}>
              {t("currencies.add")}
            </button>
          </form>
          <label className="inline-form">
            {t("access.reason")}
            <input value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <p className="muted">{t("currencies.switchHelp")}</p>
          <ErrorLine error={add.error ?? toggle.error} />
        </section>
      )}
      {list.data && (
        <DataTable
          label={t("currencies.tab.currencies")}
          rows={list.data}
          rowKey={(c) => c.id}
          pageSize="all"
          columns={[
            {
              id: "code",
              header: t("currencies.code"),
              value: (c) => c.code,
              cell: (c) => (
                <>
                  {c.code}
                  {c.is_base && <span className="tag">{t("currencies.base")}</span>}
                </>
              ),
            },
            { id: "name", header: t("divisions.name"), value: (c) => c.name },
            { id: "symbol", header: t("currencies.symbol"), value: (c) => c.symbol },
            { id: "decimals", header: t("currencies.decimals"), value: (c) => c.decimal_places },
            {
              id: "latest",
              header: t("currencies.latest"),
              value: (c) => c.latest_rate?.rate ?? "",
              cell: (c) =>
                c.latest_rate ? `${formatDecimal(c.latest_rate.rate)} (${c.latest_rate.date})` : "—",
            },
            {
              id: "status",
              header: t("users.status"),
              value: (c) => (c.is_active ? t("currencies.on") : t("currencies.off")),
            },
            ...(canManage
              ? [
                  {
                    id: "toggle",
                    header: "",
                    sortable: false,
                    value: () => "",
                    cell: (c: Currency) =>
                      c.is_base ? null : (
                        <button
                          type="button"
                          className="small secondary"
                          aria-label={t(c.is_active ? "currencies.switchOffOne" : "currencies.switchOnOne", { code: c.code })}
                          onClick={() => toggle.mutate(c)}
                        >
                          {c.is_active ? t("currencies.switchOff") : t("currencies.switchOn")}
                        </button>
                      ),
                  },
                ]
              : []),
          ]}
        />
      )}
    </>
  );
}

// --- Exchange rates ----------------------------------------------------------------------

function RatesTab({ canEnter }: { canEnter: boolean }) {
  const { t } = useTranslation();
  const currencies = useQuery({ queryKey: currencyKeys.list, queryFn: listCurrencies });
  const [filter, setFilter] = useState("");
  const rates = useQuery({
    queryKey: [...currencyKeys.rates, filter],
    queryFn: () => listRates(filter),
  });
  const foreign = currencies.data?.filter((c) => !c.is_base && c.is_active) ?? [];

  return (
    <>
      {canEnter && foreign.length > 0 && <RateForm currencies={foreign} />}
      {canEnter && <ImportPanel />}
      <section className="panel">
        <h2>{t("currencies.rates")}</h2>
        <label className="inline-form">
          {t("currencies.currency")}
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">{t("table.all")}</option>
            {currencies.data
              ?.filter((c) => !c.is_base)
              .map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code}
                </option>
              ))}
          </select>
        </label>
        {rates.data && <RateTable rows={rates.data} />}
      </section>
    </>
  );
}

function RateForm({ currencies }: { currencies: Currency[] }) {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const [currency, setCurrency] = useState(currencies[0].code);
  const [date, setDate] = useState(localToday());
  const [rate, setRate] = useState("");
  const [buying, setBuying] = useState("");
  const [selling, setSelling] = useState("");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => enterRate({ currency, date, rate, buying, selling, reason }),
    onSuccess: () => {
      refresh();
      setRate("");
      setBuying("");
      setSelling("");
      setReason("");
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <section className="panel" aria-label={t("currencies.enterRate")}>
      <h2>{t("currencies.enterRate")}</h2>
      <form className="inline-form" onSubmit={submit}>
        <label>
          {t("currencies.currency")}
          <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {currencies.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} {c.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("currencies.date")}
          <input type="date" value={date} max={localToday()} required onChange={(e) => setDate(e.target.value)} />
        </label>
        <label>
          {t("currencies.rate")}
          <input inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} />
        </label>
        <label>
          {t("currencies.buying")}
          <input inputMode="decimal" value={buying} onChange={(e) => setBuying(e.target.value)} />
        </label>
        <label>
          {t("currencies.selling")}
          <input inputMode="decimal" value={selling} onChange={(e) => setSelling(e.target.value)} />
        </label>
        <label>
          {t("access.reason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <button type="submit" disabled={save.isPending}>
          {t("currencies.saveRate")}
        </button>
      </form>
      <p className="muted">{t("currencies.rateHelp")}</p>
      <ErrorLine error={save.error} />
    </section>
  );
}

function RateTable({ rows }: { rows: ExchangeRate[] }) {
  const { t } = useTranslation();
  return (
    <DataTable
      label={t("currencies.rates")}
      rows={rows}
      rowKey={(r) => r.id}
      columns={[
        { id: "date", header: t("currencies.date"), value: (r) => r.date },
        { id: "currency", header: t("currencies.currency"), value: (r) => r.currency },
        { id: "rate", header: t("currencies.rate"), value: (r) => r.rate, cell: (r) => formatDecimal(r.rate) },
        { id: "buying", header: t("currencies.buying"), value: (r) => r.buying ?? "", cell: (r) => formatDecimal(r.buying) || "—" },
        { id: "selling", header: t("currencies.selling"), value: (r) => r.selling ?? "", cell: (r) => formatDecimal(r.selling) || "—" },
        { id: "source", header: t("currencies.source"), value: (r) => t(`currencies.sources.${r.source}`) },
        {
          id: "used",
          header: "",
          sortable: false,
          value: (r) => (r.used ? t("currencies.used") : ""),
          cell: (r) => (r.used ? <span className="tag">{t("currencies.used")}</span> : null),
        },
      ]}
    />
  );
}

function ImportPanel() {
  const { t } = useTranslation();
  const refresh = useRefresh();
  const [file, setFile] = useState<File | null>(null);
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<RateImportResult | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) => importRates(file!, reason, dryRun),
    onSuccess: (data) => {
      setResult(data);
      if (!data.dry_run) refresh();
    },
    onError: () => setResult(null),
  });
  return (
    <section className="panel" aria-label={t("currencies.import")}>
      <h2>{t("currencies.import")}</h2>
      <p className="muted">{t("currencies.importHelp")}</p>
      <div className="inline-form">
        <label>
          {t("currencies.csvFile")}
          <input
            type="file"
            accept=".csv,text/csv"
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
        <button type="button" className="secondary" disabled={!file || run.isPending} onClick={() => run.mutate(true)}>
          {t("factory.check")}
        </button>
        <button type="button" disabled={!file || run.isPending} onClick={() => run.mutate(false)}>
          {t("factory.doImport")}
        </button>
      </div>
      {result && (
        <p className="notice" role="status">
          {t(result.dry_run ? "currencies.checked" : "currencies.imported", { ...result })}
        </p>
      )}
      <ErrorLine error={run.error} />
    </section>
  );
}
