import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { listDivisions } from "../api/admin";
import {
  addClassRate,
  assetsKey,
  discardRun,
  disposeAsset,
  listAssets,
  listClasses,
  listRuns,
  postRun,
  prepareRun,
  registerAsset,
  type AssetClassRow,
  type DepMethod,
  type FixedAssetRow,
} from "../api/assets";
import { ApiError } from "../api/client";
import { listPayAccounts } from "../api/payments";
import { formatDecimal } from "../lib/decimal";

function today(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

const TABS = ["register", "depreciation", "classes"] as const;

/** Fixed assets (P2-19): the register, monthly depreciation checked then posted, and the
 * classes' dated methods and rates. */
export default function FixedAssetsPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const tab = (TABS as readonly string[]).includes(params.get("tab") ?? "") ? params.get("tab")! : "register";
  return (
    <main className="page">
      <h1>{t("fa.title")}</h1>
      <p className="muted">{t("fa.help")}</p>
      <div className="toolbar" role="tablist">
        {TABS.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={tab === name}
            className={tab === name ? undefined : "secondary"}
            onClick={() => setParams({ tab: name }, { replace: true })}
          >
            {t(`fa.tabs.${name}`)}
          </button>
        ))}
      </div>
      {tab === "register" && <Register />}
      {tab === "depreciation" && <Depreciation />}
      {tab === "classes" && <Classes />}
    </main>
  );
}

function Register() {
  const { t } = useTranslation();
  const assets = useQuery({ queryKey: [...assetsKey, "list"], queryFn: listAssets });
  const [open, setOpen] = useState<number | null>(null);
  return (
    <>
      <AssetForm />
      {assets.data && assets.data.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("fa.register")}>
            <thead>
              <tr>
                <th>{t("fa.code")}</th>
                <th>{t("fa.name")}</th>
                <th>{t("fa.class")}</th>
                <th>{t("fa.division")}</th>
                <th className="num">{t("fa.cost")}</th>
                <th className="num">{t("fa.accumulated")}</th>
                <th className="num">{t("fa.bookValue")}</th>
                <th>{t("fa.status")}</th>
              </tr>
            </thead>
            <tbody>
              {assets.data.map((a) => (
                <tr key={a.id}>
                  <td>
                    <button type="button" className="link-button mono" onClick={() => setOpen(open === a.id ? null : a.id)}>
                      {a.code}
                    </button>
                  </td>
                  <td>{a.name}</td>
                  <td>{a.asset_class.name}</td>
                  <td>{a.division}</td>
                  <td className="num">{formatDecimal(a.cost)}</td>
                  <td className="num">{formatDecimal(a.accumulated)}</td>
                  <td className="num">{formatDecimal(a.book_value)}</td>
                  <td>
                    {t(`fa.statuses.${a.status}`)}
                    {a.disposed_on && <div className="muted">{a.disposed_on}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {assets.data?.length === 0 && <p className="muted">{t("fa.none")}</p>}
      <ErrorLine error={assets.error} />
      {open !== null && assets.data?.find((a) => a.id === open)?.status === "active" && (
        <Dispose asset={assets.data.find((a) => a.id === open)!} />
      )}
    </>
  );
}

function AssetForm() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const classes = useQuery({ queryKey: [...assetsKey, "classes"], queryFn: listClasses });
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions });
  const [values, setValues] = useState<Record<string, string>>({ acquisition_date: today() });
  const set = (name: string, value: string) => setValues((now) => ({ ...now, [name]: value }));
  const save = useMutation({
    mutationFn: () => registerAsset({ ...values, asset_class: Number(values.asset_class) }),
    onSuccess: () => {
      setValues({ acquisition_date: today() });
      void queryClient.invalidateQueries({ queryKey: assetsKey });
    },
  });
  const field = (name: string, label: string, extra: { inputMode?: "decimal"; type?: string } = {}) => (
    <label key={name}>
      {label}
      <input value={values[name] ?? ""} onChange={(e) => set(name, e.target.value)} {...extra} />
    </label>
  );
  return (
    <section className="panel form-grid" aria-label={t("fa.add")}>
      <h2 className="wide">{t("fa.add")}</h2>
      <label>
        {t("fa.class")}
        <select value={values.asset_class ?? ""} onChange={(e) => set("asset_class", e.target.value)}>
          <option value="">—</option>
          {classes.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("fa.division")}
        <select value={values.division ?? ""} onChange={(e) => set("division", e.target.value)}>
          <option value="">—</option>
          {divisions.data?.map((d) => (
            <option key={d.code} value={d.code}>
              {d.code} {d.name}
            </option>
          ))}
        </select>
      </label>
      {field("name", t("fa.name"))}
      {field("acquisition_date", t("fa.acquired"), { type: "date" })}
      {field("cost", t("fa.cost"), { inputMode: "decimal" })}
      {field("depreciation_from", t("fa.from"), { type: "date" })}
      {field("residual_value", t("fa.residual"), { inputMode: "decimal" })}
      {field("opening_accumulated", t("fa.openingAccumulated"), { inputMode: "decimal" })}
      {field("serial_no", t("fa.serial"))}
      {field("supplier", t("fa.supplier"))}
      <div className="wide row-actions">
        <button type="button" disabled={save.isPending || !values.asset_class || !values.division} onClick={() => save.mutate()}>
          {t("fa.save")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </section>
  );
}

function Dispose({ asset }: { asset: FixedAssetRow }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const accounts = useQuery({ queryKey: ["payments", "accounts"], queryFn: listPayAccounts });
  const [day, setDay] = useState(today());
  const [proceeds, setProceeds] = useState("");
  const [account, setAccount] = useState("");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => disposeAsset(asset.id, { disposed_on: day, proceeds, account: account ? Number(account) : null, reason }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: assetsKey }),
  });
  return (
    <section className="panel form-grid" aria-label={t("fa.dispose")}>
      <h2 className="wide">
        {t("fa.dispose")}: {asset.code} {asset.name}
      </h2>
      <label>
        {t("fa.disposedOn")}
        <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
      </label>
      <label>
        {t("fa.proceeds")}
        <input inputMode="decimal" value={proceeds} onChange={(e) => setProceeds(e.target.value)} />
      </label>
      <label>
        {t("fa.into")}
        <select value={account} onChange={(e) => setAccount(e.target.value)}>
          <option value="">—</option>
          {(accounts.data ?? []).map((a) => (
            <option key={a.id} value={a.id}>
              {a.code} {a.name}
            </option>
          ))}
        </select>
      </label>
      <label className="wide">
        {t("fa.reason")}
        <input value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <div className="wide row-actions">
        <button type="button" disabled={save.isPending} onClick={() => save.mutate()}>
          {t("fa.disposeButton")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </section>
  );
}

function Depreciation() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const runs = useQuery({ queryKey: [...assetsKey, "runs"], queryFn: listRuns });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: assetsKey });
  const prepare = useMutation({ mutationFn: (month: string) => prepareRun(month), onSuccess: refresh });
  const post = useMutation({ mutationFn: (id: number) => postRun(id), onSuccess: refresh });
  const discard = useMutation({ mutationFn: (id: number) => discardRun(id), onSuccess: refresh });
  const next = runs.data?.next_month;
  return (
    <>
      <section className="panel" aria-label={t("fa.nextMonth")}>
        <h2>{t("fa.nextMonth")}</h2>
        {next ? (
          <button type="button" disabled={prepare.isPending} onClick={() => prepare.mutate(next)}>
            {t("fa.prepare", { month: next.slice(0, 7) })}
          </button>
        ) : (
          <p className="muted">{t("fa.nothingYet")}</p>
        )}
        <ErrorLine error={prepare.error ?? post.error ?? discard.error} />
      </section>
      {runs.data?.runs.map((r) => (
        <section key={r.id} className="panel" aria-label={r.month_end}>
          <h2>
            {r.month_end.slice(0, 7)} · {t(`fa.runStatuses.${r.status}`)} · LKR {formatDecimal(r.total)}
            {r.journal_entry && ` · ${r.journal_entry}`}
          </h2>
          <div className="table-wrap">
            <table aria-label={t("fa.linesOf", { month: r.month_end.slice(0, 7) })}>
              <thead>
                <tr>
                  <th>{t("fa.code")}</th>
                  <th>{t("fa.division")}</th>
                  <th>{t("fa.rate")}</th>
                  <th className="num">{t("fa.bookValue")}</th>
                  <th className="num">{t("fa.amount")}</th>
                </tr>
              </thead>
              <tbody>
                {r.lines.map((x) => (
                  <tr key={x.asset.id}>
                    <td>
                      {x.asset.code} {x.asset.name}
                    </td>
                    <td>{x.division}</td>
                    <td>
                      {x.rate}% {t(`fa.methods.${x.method}`)}
                    </td>
                    <td className="num">{formatDecimal(x.book_value_before)}</td>
                    <td className="num">{formatDecimal(x.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {r.status === "draft" && (
            <div className="row-actions">
              <button type="button" disabled={post.isPending} onClick={() => post.mutate(r.id)}>
                {t("fa.post")}
              </button>
              <button type="button" className="secondary" disabled={prepare.isPending} onClick={() => prepare.mutate(r.month_end)}>
                {t("fa.again")}
              </button>
              <button type="button" className="secondary" disabled={discard.isPending} onClick={() => discard.mutate(r.id)}>
                {t("fa.discard")}
              </button>
            </div>
          )}
        </section>
      ))}
    </>
  );
}

function Classes() {
  const { t } = useTranslation();
  const classes = useQuery({ queryKey: [...assetsKey, "classes"], queryFn: listClasses });
  return (
    <>
      <p className="muted">{t("fa.classesHelp")}</p>
      {classes.data?.map((c) => <ClassCard key={c.id} row={c} />)}
      <ErrorLine error={classes.error} />
    </>
  );
}

function ClassCard({ row }: { row: AssetClassRow }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [from, setFrom] = useState(today());
  const [method, setMethod] = useState<DepMethod>("straight_line");
  const [rate, setRate] = useState("");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => addClassRate(row.id, { effective_from: from, method, rate, reason }),
    onSuccess: () => {
      setRate("");
      void queryClient.invalidateQueries({ queryKey: assetsKey });
    },
  });
  return (
    <section className="panel" aria-label={row.name}>
      <h2>
        {row.name} · {row.cost_account}
      </h2>
      <p>
        {row.current ? `${row.current.rate}% ${t(`fa.methods.${row.current.method}`)} ${t("fa.since", { date: row.current.from })}` : t("fa.noRate")}
      </p>
      <div className="inline-form">
        <input type="date" aria-label={t("fa.rateFrom")} value={from} onChange={(e) => setFrom(e.target.value)} />
        <select aria-label={t("fa.method")} value={method} onChange={(e) => setMethod(e.target.value as DepMethod)}>
          <option value="straight_line">{t("fa.methods.straight_line")}</option>
          <option value="reducing_balance">{t("fa.methods.reducing_balance")}</option>
          <option value="none">{t("fa.methods.none")}</option>
        </select>
        <input aria-label={t("fa.ratePercent")} placeholder="%" inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} />
        <input aria-label={t("fa.reason")} placeholder={t("fa.agreedWith")} value={reason} onChange={(e) => setReason(e.target.value)} />
        <button type="button" className="small" disabled={save.isPending} onClick={() => save.mutate()}>
          {t("fa.addRate")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </section>
  );
}
