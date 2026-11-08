import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { listDivisions } from "../api/admin";
import {
  addClassRate,
  assetsKey,
  decideClassRate,
  decideTerms,
  getWaiting,
  proposeTerms,
  sendAllTerms,
  discardRun,
  disposeAsset,
  listAssets,
  listClasses,
  listRuns,
  postRun,
  prepareRun,
  registerAsset,
  type AssetClassRow,
  type AssetTerms,
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

const TABS = ["register", "approvals", "depreciation", "classes"] as const;

/** "10% straight line · 10 years", with "waiting for the Director" when not yet approved. */
function TermsText({ terms }: { terms: Pick<AssetTerms, "method" | "rate" | "life_years" | "status"> | null }) {
  const { t } = useTranslation();
  if (!terms) return <span className="muted">{t("fa.noTerms")}</span>;
  return (
    <>
      {terms.method === "none" ? t("fa.methods.none") : `${terms.rate}% ${t(`fa.methods.${terms.method}`)}`}
      {terms.life_years ? ` · ${t("fa.years", { count: terms.life_years })}` : ""}
      {terms.status !== "approved" && <span className="muted small"> ({t(`fa.approvals.${terms.status}`)})</span>}
    </>
  );
}

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
      {tab === "approvals" && <Approvals />}
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
                <th>{t("fa.terms")}</th>
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
                    <TermsText terms={a.terms} />
                  </td>
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
        <>
          <ChangeTerms asset={assets.data.find((a) => a.id === open)!} />
          <Dispose asset={assets.data.find((a) => a.id === open)!} />
        </>
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
      <p className="muted wide">{t("fa.termsHelp")}</p>
      <label>
        {t("fa.method")}
        <select value={values.method ?? ""} onChange={(e) => set("method", e.target.value)}>
          <option value="">{t("fa.classDefault")}</option>
          <option value="straight_line">{t("fa.methods.straight_line")}</option>
          <option value="reducing_balance">{t("fa.methods.reducing_balance")}</option>
          <option value="none">{t("fa.methods.none")}</option>
        </select>
      </label>
      {values.method && field("life_years", t("fa.lifeYears"), { inputMode: "decimal" })}
      {values.method && field("rate", t("fa.ratePercent"), { inputMode: "decimal" })}
      {values.method && field("terms_reason", t("fa.termsReason"))}
      <div className="wide row-actions">
        <button type="button" disabled={save.isPending || !values.asset_class || !values.division} onClick={() => save.mutate()}>
          {t("fa.save")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </section>
  );
}

function ChangeTerms({ asset }: { asset: FixedAssetRow }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [values, setValues] = useState({
    effective_from: today(),
    method: "straight_line" as DepMethod,
    rate: "",
    life_years: "",
    reason: "",
  });
  const save = useMutation({
    mutationFn: () => proposeTerms(asset.id, values),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: assetsKey }),
  });
  const set = (key: keyof typeof values) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  return (
    <section className="panel form-grid" aria-label={t("fa.changeTerms")}>
      <h2 className="wide">
        {t("fa.changeTerms")}: {asset.code} {asset.name}
      </h2>
      <p className="wide">
        {t("fa.termsNow")}: <TermsText terms={asset.terms} />
      </p>
      <label>
        {t("fa.rateFrom")}
        <input type="date" value={values.effective_from} onChange={set("effective_from")} />
      </label>
      <label>
        {t("fa.method")}
        <select value={values.method} onChange={set("method")}>
          <option value="straight_line">{t("fa.methods.straight_line")}</option>
          <option value="reducing_balance">{t("fa.methods.reducing_balance")}</option>
          <option value="none">{t("fa.methods.none")}</option>
        </select>
      </label>
      <label>
        {t("fa.lifeYears")}
        <input inputMode="decimal" value={values.life_years} onChange={set("life_years")} />
      </label>
      <label>
        {t("fa.ratePercent")}
        <input inputMode="decimal" value={values.rate} onChange={set("rate")} />
      </label>
      <label className="wide">
        {t("fa.reason")}
        <input value={values.reason} onChange={set("reason")} />
      </label>
      <div className="wide row-actions">
        <button type="button" disabled={save.isPending} onClick={() => save.mutate()}>
          {t("fa.sendTerms")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </section>
  );
}

/** The Director approves each asset's terms and changes to class defaults (owner, 8 Nov 2026). */
function Approvals() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const waiting = useQuery({ queryKey: [...assetsKey, "waiting"], queryFn: getWaiting });
  const [reason, setReason] = useState("");
  const refresh = () => {
    setReason("");
    void queryClient.invalidateQueries({ queryKey: assetsKey });
  };
  const terms = useMutation({
    mutationFn: ({ id, action }: { id: number; action: "approve" | "reject" }) => decideTerms(id, action, reason),
    onSuccess: refresh,
  });
  const rates = useMutation({
    mutationFn: ({ id, action }: { id: number; action: "approve" | "reject" }) => decideClassRate(id, action, reason),
    onSuccess: refresh,
  });
  const sendAll = useMutation({ mutationFn: sendAllTerms, onSuccess: refresh });
  const d = waiting.data;
  if (!d) return <ErrorLine error={waiting.error} />;
  const decider = d.terms.some((x) => x.can_decide) || d.rates.some((x) => x.can_decide);
  return (
    <>
      <p className="muted">{t("fa.approvalsHelp")}</p>
      {d.can_send_all && d.without_terms > 0 && (
        <section className="panel" aria-label={t("fa.withoutTerms")}>
          <p>{t("fa.withoutTermsCount", { count: d.without_terms })}</p>
          <button type="button" disabled={sendAll.isPending} onClick={() => sendAll.mutate()}>
            {t("fa.sendAll")}
          </button>
          <ErrorLine error={sendAll.error} />
        </section>
      )}
      {decider && (
        <label className="wide">
          {t("fa.decisionReason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      )}
      <section className="panel" aria-label={t("fa.waitingTerms")}>
        <h2>{t("fa.waitingTerms")}</h2>
        {d.terms.length === 0 ? (
          <p className="muted">{t("fa.nothingWaiting")}</p>
        ) : (
          <div className="table-wrap">
            <table aria-label={t("fa.waitingTerms")}>
              <thead>
                <tr>
                  <th>{t("fa.code")}</th>
                  <th>{t("fa.class")}</th>
                  <th className="num">{t("fa.cost")}</th>
                  <th>{t("fa.terms")}</th>
                  <th>{t("fa.rateFrom")}</th>
                  <th>{t("fa.reason")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {d.terms.map((x) => (
                  <tr key={x.id}>
                    <td>
                      {x.asset} {x.asset_name}
                    </td>
                    <td>{x.asset_class}</td>
                    <td className="num">{formatDecimal(x.cost)}</td>
                    <td>
                      <TermsText terms={{ ...x, status: "approved" }} />
                    </td>
                    <td>{x.effective_from}</td>
                    <td>
                      {x.reason} <span className="muted small">{x.by}</span>
                    </td>
                    <td>
                      {x.can_decide && (
                        <div className="row-actions">
                          <button
                            type="button"
                            className="small"
                            aria-label={t("fa.approveOf", { code: x.asset })}
                            disabled={terms.isPending}
                            onClick={() => terms.mutate({ id: x.id, action: "approve" })}
                          >
                            {t("fa.approve")}
                          </button>
                          <button
                            type="button"
                            className="secondary small"
                            aria-label={t("fa.rejectOf", { code: x.asset })}
                            disabled={terms.isPending}
                            onClick={() => terms.mutate({ id: x.id, action: "reject" })}
                          >
                            {t("fa.reject")}
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
        <ErrorLine error={terms.error} />
      </section>
      <section className="panel" aria-label={t("fa.waitingDefaults")}>
        <h2>{t("fa.waitingDefaults")}</h2>
        {d.rates.length === 0 ? (
          <p className="muted">{t("fa.nothingWaiting")}</p>
        ) : (
          d.rates.map((x) => (
            <p key={x.id}>
              <strong>{x.asset_class}</strong> {t("fa.since", { date: x.effective_from })}:{" "}
              <TermsText terms={{ ...x, status: "approved" }} />{" "}
              <span className="muted small">
                {x.reason} {x.by}
              </span>{" "}
              {x.can_decide && (
                <>
                  <button
                    type="button"
                    className="small"
                    aria-label={t("fa.approveOf", { code: x.asset_class })}
                    disabled={rates.isPending}
                    onClick={() => rates.mutate({ id: x.id, action: "approve" })}
                  >
                    {t("fa.approve")}
                  </button>{" "}
                  <button
                    type="button"
                    className="secondary small"
                    aria-label={t("fa.rejectOf", { code: x.asset_class })}
                    disabled={rates.isPending}
                    onClick={() => rates.mutate({ id: x.id, action: "reject" })}
                  >
                    {t("fa.reject")}
                  </button>
                </>
              )}
            </p>
          ))
        )}
        <ErrorLine error={rates.error} />
      </section>
    </>
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
      {classes.data?.map((c) => (
        <ClassCard key={c.id} row={c} />
      ))}
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
  const [life, setLife] = useState("");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => addClassRate(row.id, { effective_from: from, method, rate, life_years: life, reason }),
    onSuccess: () => {
      setRate("");
      setLife("");
      void queryClient.invalidateQueries({ queryKey: assetsKey });
    },
  });
  return (
    <section className="panel" aria-label={row.name}>
      <h2>
        {row.name} · {row.cost_account}
      </h2>
      <p>
        {row.current ? (
          <>
            <TermsText terms={{ ...row.current, status: "approved" }} /> {t("fa.since", { date: row.current.from })}
          </>
        ) : (
          t("fa.noRate")
        )}
      </p>
      {row.rates
        .filter((r) => r.status === "awaiting")
        .map((r) => (
          <p key={r.id} className="muted">
            {t("fa.waitingDefault", { date: r.effective_from })}: <TermsText terms={{ ...r, status: "approved" }} />
          </p>
        ))}
      <div className="inline-form">
        <input type="date" aria-label={t("fa.rateFrom")} value={from} onChange={(e) => setFrom(e.target.value)} />
        <select aria-label={t("fa.method")} value={method} onChange={(e) => setMethod(e.target.value as DepMethod)}>
          <option value="straight_line">{t("fa.methods.straight_line")}</option>
          <option value="reducing_balance">{t("fa.methods.reducing_balance")}</option>
          <option value="none">{t("fa.methods.none")}</option>
        </select>
        <input
          aria-label={t("fa.lifeYears")}
          placeholder={t("fa.yearsShort")}
          inputMode="decimal"
          value={life}
          onChange={(e) => setLife(e.target.value)}
        />
        <input
          aria-label={t("fa.ratePercent")}
          placeholder="%"
          inputMode="decimal"
          value={rate}
          onChange={(e) => setRate(e.target.value)}
        />
        <input aria-label={t("fa.reason")} placeholder={t("fa.agreedWith")} value={reason} onChange={(e) => setReason(e.target.value)} />
        <button type="button" className="small" disabled={save.isPending} onClick={() => save.mutate()}>
          {t("fa.addRate")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </section>
  );
}
