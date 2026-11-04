import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { chartKey, listLedgerAccounts } from "../api/accounts";
import { listDivisions } from "../api/admin";
import { ApiError } from "../api/client";
import { balanceSheet, generalLedger, profitAndLoss, reportsKey, trialBalance } from "../api/financialReports";
import ExportLinks from "../components/ExportLinks";
import SearchSelect from "../components/SearchSelect";
import { formatDecimal } from "../lib/decimal";

type Tab = "tb" | "bs" | "pl" | "gl";
const TABS: Tab[] = ["tb", "bs", "pl", "gl"];

const today = () => new Date().toLocaleDateString("en-CA");
const monthStart = (day: string) => `${day.slice(0, 8)}01`;
const show = (amount: string) => (amount === "0.00" ? "" : formatDecimal(amount));

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** Trial balance, balance sheet, profit and loss and general ledger (P2-03), for the company
 * or one division. Every figure opens the ledger behind it; every ledger line opens its
 * journal entry and the document (with its scans) that posted it. */
export default function FinancialReportsPage() {
  const { t } = useTranslation();
  const [search, setSearch] = useSearchParams();
  const asked = search.get("tab") as Tab | null;
  const tab: Tab = asked && TABS.includes(asked) ? asked : "tb";
  const get = (name: string, fallback = "") => search.get(name) ?? fallback;
  const set = (changes: Record<string, string>) => {
    const next = new URLSearchParams(search);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setSearch(next, { replace: true });
  };
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions });

  const division = get("division");
  const asAt = get("as_at", today());
  const to = get("to", today());
  const from = get("from", monthStart(to));
  /** The general ledger of one account, for the period behind a figure. */
  const ledgerOf = (account: number, start: string, end: string) => {
    const next = new URLSearchParams({ tab: "gl", account: String(account), from: start, to: end });
    if (division) next.set("division", division);
    return `?${next.toString()}`;
  };

  return (
    <main className="page">
      <h1>{t("fr.title")}</h1>
      <p className="muted">{t("fr.help")}</p>
      <div role="tablist" aria-label={t("fr.title")} className="tabs">
        {TABS.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            className={`tab ${tab === name ? "active" : ""}`}
            aria-selected={tab === name}
            onClick={() => set({ tab: name })}
          >
            {t(`fr.tabs.${name}`)}
          </button>
        ))}
      </div>
      <div className="toolbar">
        <label>
          {t("vouchers.division")}
          <select value={division} onChange={(e) => set({ division: e.target.value })}>
            <option value="">{t("fr.company")}</option>
            {(divisions.data ?? []).map((d) => (
              <option key={d.code} value={d.code}>
                {d.code} {d.name}
              </option>
            ))}
          </select>
        </label>
        {(tab === "tb" || tab === "bs") && (
          <>
            <label>
              {t("fr.asAt")}
              <input type="date" value={asAt} onChange={(e) => set({ as_at: e.target.value })} />
            </label>
            <label>
              {t("fr.compare")}
              <select value={get("compare")} onChange={(e) => set({ compare: e.target.value })}>
                <option value="">{t("fr.noCompare")}</option>
                <option value="month">{t("fr.previousMonth")}</option>
                <option value="year">{t("fr.previousYear")}</option>
              </select>
            </label>
            <label>
              <input type="checkbox" checked={get("sub") === "rollup"} onChange={(e) => set({ sub: e.target.checked ? "rollup" : "" })} />{" "}
              {t("fr.rollUp")}
            </label>
          </>
        )}
        {(tab === "pl" || tab === "gl") && (
          <>
            <label>
              {t("exports.from")}
              <input type="date" value={from} onChange={(e) => set({ from: e.target.value })} />
            </label>
            <label>
              {t("fr.to")}
              <input type="date" value={to} onChange={(e) => set({ to: e.target.value })} />
            </label>
          </>
        )}
      </div>
      {tab === "tb" && <TrialBalanceTab params={{ as_at: asAt, division, compare: get("compare"), sub: get("sub") }} ledgerOf={ledgerOf} />}
      {tab === "bs" && <BalanceSheetTab params={{ as_at: asAt, division, compare: get("compare"), sub: get("sub") }} ledgerOf={ledgerOf} />}
      {tab === "pl" && <ProfitAndLossTab params={{ from, to, division }} ledgerOf={ledgerOf} />}
      {tab === "gl" && (
        <LedgerTab
          params={{ from, to, division, account: get("account"), sub: get("sub") === "include" ? "include" : "" }}
          onAccount={(account) => set({ account })}
          onSub={(on) => set({ sub: on ? "include" : "" })}
        />
      )}
    </main>
  );
}

type LedgerOf = (account: number, start: string, end: string) => string;

function TrialBalanceTab({ params, ledgerOf }: { params: Record<string, string>; ledgerOf: LedgerOf }) {
  const { t } = useTranslation();
  const report = useQuery({ queryKey: [...reportsKey, "tb", params], queryFn: () => trialBalance(params) });
  const data = report.data;
  const compare = data?.compare_date;
  return (
    <section className="panel" aria-label={t("fr.tabs.tb")}>
      <ExportLinks path="/reports/trial-balance/" params={params} label={t("fr.tabs.tb")} />
      <ErrorLine error={report.error} />
      {data && (
        <div className="table-wrap">
          <table aria-label={t("fr.tabs.tb")}>
            <thead>
              <tr>
                <th>{t("mj.account")}</th>
                <th>{t("fr.type")}</th>
                <th className="num">{t("fr.debitOn", { date: data.as_at })}</th>
                <th className="num">{t("fr.creditOn", { date: data.as_at })}</th>
                {compare && <th className="num">{t("fr.debitOn", { date: compare })}</th>}
                {compare && <th className="num">{t("fr.creditOn", { date: compare })}</th>}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => {
                const link = ledgerOf(r.account.id, monthStart(data.as_at), data.as_at);
                return (
                  <tr key={r.account.id}>
                    <td>
                      <span className="mono">{r.account.number}</span> {r.account.name}
                    </td>
                    <td>{r.account.account_type_label}</td>
                    <td className="num">{r.debit !== "0.00" && <Link to={link}>{formatDecimal(r.debit)}</Link>}</td>
                    <td className="num">{r.credit !== "0.00" && <Link to={link}>{formatDecimal(r.credit)}</Link>}</td>
                    {compare && <td className="num">{show(r.compare_debit)}</td>}
                    {compare && <td className="num">{show(r.compare_credit)}</td>}
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <th colSpan={2}>{t("vouchers.total")}</th>
                <th className="num">{formatDecimal(data.total_debit)}</th>
                <th className="num">{formatDecimal(data.total_credit)}</th>
                {compare && <th className="num">{formatDecimal(data.compare_total_debit)}</th>}
                {compare && <th className="num">{formatDecimal(data.compare_total_credit)}</th>}
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      {data && data.rows.length === 0 && <p className="muted">{t("fr.nothing")}</p>}
    </section>
  );
}

function BalanceSheetTab({ params, ledgerOf }: { params: Record<string, string>; ledgerOf: LedgerOf }) {
  const { t } = useTranslation();
  const report = useQuery({ queryKey: [...reportsKey, "bs", params], queryFn: () => balanceSheet(params) });
  const data = report.data;
  const compare = data?.compare_date;
  return (
    <section className="panel" aria-label={t("fr.tabs.bs")}>
      <ExportLinks path="/reports/balance-sheet/" params={params} label={t("fr.tabs.bs")} />
      <ErrorLine error={report.error} />
      {data && (
        <div className="table-wrap">
          <table aria-label={t("fr.tabs.bs")}>
            <thead>
              <tr>
                <th />
                <th className="num">{data.as_at}</th>
                {compare && <th className="num">{compare}</th>}
              </tr>
            </thead>
            {data.sections.map((s) => (
              <tbody key={s.key}>
                <tr>
                  <th colSpan={compare ? 3 : 2}>{t(`fr.sections.${s.key}`)}</th>
                </tr>
                {s.rows.map((r) => (
                  <tr key={r.label}>
                    <td>{r.kind === "account" ? r.label : t(`fr.kinds.${r.kind}`)}</td>
                    <td className="num">
                      {r.account ? <Link to={ledgerOf(r.account.id, monthStart(data.as_at), data.as_at)}>{formatDecimal(r.amount)}</Link> : formatDecimal(r.amount)}
                    </td>
                    {compare && <td className="num">{formatDecimal(r.compare)}</td>}
                  </tr>
                ))}
                <tr>
                  <th>{t(`fr.totals.${s.key}`)}</th>
                  <th className="num">{formatDecimal(s.total)}</th>
                  {compare && <th className="num">{formatDecimal(s.compare_total)}</th>}
                </tr>
              </tbody>
            ))}
          </table>
        </div>
      )}
      {data?.division && <p className="muted">{t("fr.divisionNote")}</p>}
    </section>
  );
}

function ProfitAndLossTab({ params, ledgerOf }: { params: Record<string, string>; ledgerOf: LedgerOf }) {
  const { t } = useTranslation();
  const report = useQuery({ queryKey: [...reportsKey, "pl", params], queryFn: () => profitAndLoss(params) });
  const data = report.data;
  return (
    <section className="panel" aria-label={t("fr.tabs.pl")}>
      <ExportLinks path="/reports/profit-and-loss/" params={params} label={t("fr.tabs.pl")} />
      <ErrorLine error={report.error} />
      {data && (
        <div className="table-wrap">
          <table aria-label={t("fr.tabs.pl")}>
            <thead>
              <tr>
                <th>{t("mj.account")}</th>
                <th>{t("fr.type")}</th>
                <th className="num">{t("fr.amount")}</th>
                {data.has_budget && <th className="num">{t("budget.budget")}</th>}
                {data.has_budget && <th className="num">{t("budget.difference")}</th>}
                {data.has_budget && <th className="num">%</th>}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.account.id}>
                  <td>
                    <span className="mono">{r.account.number}</span> {r.account.name}
                  </td>
                  <td>{r.account_type_label}</td>
                  <td className="num">
                    <Link to={ledgerOf(r.account.id, data.from, data.to)}>{formatDecimal(r.amount)}</Link>
                  </td>
                  {data.has_budget && <td className="num">{formatDecimal(r.budget ?? "0.00")}</td>}
                  {data.has_budget && <td className="num">{formatDecimal(r.difference ?? "0.00")}</td>}
                  {data.has_budget && <td className="num">{r.percent ?? ""}</td>}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th colSpan={2}>{t("fr.profit")}</th>
                <th className="num">{formatDecimal(data.profit)}</th>
                {data.has_budget && <th className="num">{formatDecimal(data.budget_profit ?? "0.00")}</th>}
                {data.has_budget && <th className="num">{formatDecimal(data.profit_difference ?? "0.00")}</th>}
                {data.has_budget && <th />}
              </tr>
            </tfoot>
          </table>
        </div>
      )}
      <p className="muted">{t("fr.plNote")}</p>
      {data?.has_budget && <p className="muted">{t("budget.plNote")}</p>}
    </section>
  );
}

function LedgerTab({
  params,
  onAccount,
  onSub,
}: {
  params: Record<string, string>;
  onAccount: (account: string) => void;
  onSub: (on: boolean) => void;
}) {
  const { t } = useTranslation();
  const accounts = useQuery({ queryKey: [...chartKey, "accounts", false], queryFn: () => listLedgerAccounts(false) });
  const options = [
    { value: "", label: t("fr.allAccounts") },
    ...(accounts.data ?? [])
      .filter((a) => !a.merged_into)
      .map((a) => ({ value: String(a.id), label: `${a.number ? `${a.number} ` : ""}${a.full_name}` })),
  ];
  const report = useQuery({ queryKey: [...reportsKey, "gl", params], queryFn: () => generalLedger(params) });
  const data = report.data;
  return (
    <section className="panel" aria-label={t("fr.tabs.gl")}>
      <div className="toolbar">
        <SearchSelect label={t("mj.account")} options={options} value={params.account} onChange={onAccount} />
        <label>
          <input type="checkbox" checked={params.sub === "include"} onChange={(e) => onSub(e.target.checked)} /> {t("fr.withSub")}
        </label>
        <ExportLinks path="/reports/general-ledger/" params={params} label={t("fr.tabs.gl")} />
      </div>
      <ErrorLine error={report.error} />
      {data?.accounts.length === 0 && <p className="muted">{t("fr.nothing")}</p>}
      {data?.accounts.map((a) => (
        <div className="table-wrap" key={a.account.id}>
          <h2>
            <span className="mono">{a.account.number}</span> {a.account.name}
          </h2>
          <table aria-label={`${a.account.number} ${a.account.name}`.trim()}>
            <thead>
              <tr>
                <th>{t("vouchers.date")}</th>
                <th>{t("fr.entry")}</th>
                <th>{t("mj.narration")}</th>
                <th>{t("vouchers.division")}</th>
                <th className="num">{t("mj.debit")}</th>
                <th className="num">{t("mj.credit")}</th>
                <th className="num">{t("fr.balance")}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>{data.from}</td>
                <td />
                <td>{t("fr.broughtForward")}</td>
                <td />
                <td />
                <td />
                <td className="num">{formatDecimal(a.opening)}</td>
              </tr>
              {a.lines.map((x, i) => (
                <tr key={`${x.entry.id}-${i}`}>
                  <td>{x.entry_date}</td>
                  <td>
                    <Link to={`/journal?entry=${x.entry.id}&q=${encodeURIComponent(x.entry.number)}`} className="mono">
                      {x.entry.number}
                    </Link>
                    {x.source_page && (
                      <div>
                        <Link to={x.source_page}>{x.source_id}</Link>
                      </div>
                    )}
                  </td>
                  <td>
                    {x.narration}
                    {x.description && <div className="muted">{x.description}</div>}
                    {x.supplier && <div className="muted">{x.supplier}</div>}
                  </td>
                  <td>{x.division ?? ""}</td>
                  <td className="num">{show(x.debit)}</td>
                  <td className="num">{show(x.credit)}</td>
                  <td className="num">{formatDecimal(x.balance)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th colSpan={4}>{t("fr.carriedForward")}</th>
                <th className="num">{formatDecimal(a.total_debit)}</th>
                <th className="num">{formatDecimal(a.total_credit)}</th>
                <th className="num">{formatDecimal(a.closing)}</th>
              </tr>
            </tfoot>
          </table>
        </div>
      ))}
      <p className="muted">{t("fr.glNote")}</p>
    </section>
  );
}
