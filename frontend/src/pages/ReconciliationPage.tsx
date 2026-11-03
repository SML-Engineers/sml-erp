import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { chartKey, listLedgerAccounts } from "../api/accounts";
import { listDivisions } from "../api/admin";
import { ApiError } from "../api/client";
import { listPayAccounts } from "../api/payments";
import {
  acceptSuggestions,
  finishReconciliation,
  getCandidates,
  getReconciliation,
  listRules,
  matchLine,
  postLine,
  reconciliationKey,
  saveRule,
  unmatchLine,
  type RecLine,
} from "../api/reconciliation";
import SearchSelect from "../components/SearchSelect";
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

/** The end of last month, YYYY-MM-DD. */
function lastMonthEnd(): string {
  const now = new Date();
  const end = new Date(now.getFullYear(), now.getMonth(), 0);
  return `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, "0")}-${String(end.getDate()).padStart(2, "0")}`;
}

function money(value: string | null | undefined) {
  return value ? formatDecimal(value) : "";
}

/** Bank reconciliation (P2-16): match statement lines to the books, post bank charges and
 * interest, and lock the month once the difference is nil. */
export default function ReconciliationPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const accounts = useQuery({ queryKey: ["payments", "accounts"], queryFn: listPayAccounts });
  const banks = (accounts.data ?? []).filter((a) => a.kind === "current" || a.kind === "savings");
  const [account, setAccount] = useState("");
  const [periodEnd, setPeriodEnd] = useState(lastMonthEnd());
  const [note, setNote] = useState("");
  const key = [...reconciliationKey, account, periodEnd];
  const rec = useQuery({ queryKey: key, queryFn: () => getReconciliation(account, periodEnd), enabled: account !== "" });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: reconciliationKey });
  const accept = useMutation({ mutationFn: () => acceptSuggestions(account, periodEnd), onSuccess: refresh });
  const finish = useMutation({ mutationFn: () => finishReconciliation(account, periodEnd, note), onSuccess: refresh });
  const d = rec.data;

  return (
    <main className="page">
      <h1>{t("rec.title")}</h1>
      <p className="muted">{t("rec.help")}</p>
      <div className="toolbar">
        <label>
          {t("rec.account")}
          <select value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="">—</option>
            {banks.map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("rec.periodEnd")}
          <input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} />
        </label>
      </div>
      <ErrorLine error={rec.error} />
      {d && (
        <>
          <section className="panel" aria-label={t("rec.figures")}>
            <dl className="details">
              <dt>{t("rec.bankBalance")}</dt>
              <dd>{d.bank_balance === null ? t("rec.noStatement") : money(d.bank_balance)}</dd>
              <dt>{t("rec.bookBalance")}</dt>
              <dd>{money(d.book_balance)}</dd>
              <dt>{t("rec.unpresented")}</dt>
              <dd>{money(d.unpresented_total)}</dd>
              <dt>{t("rec.notInBooks")}</dt>
              <dd>{money(d.not_in_books_total)}</dd>
              <dt>{t("rec.difference")}</dt>
              <dd>
                <strong>{d.difference === null ? "—" : money(d.difference)}</strong>
              </dd>
              {d.locked_to && (
                <>
                  <dt>{t("rec.lockedTo")}</dt>
                  <dd>{d.locked_to}</dd>
                </>
              )}
            </dl>
            <div className="row-actions">
              <button type="button" className="secondary" disabled={accept.isPending} onClick={() => accept.mutate()}>
                {t("rec.acceptAll")}
              </button>
              <input aria-label={t("rec.note")} placeholder={t("rec.note")} value={note} onChange={(e) => setNote(e.target.value)} />
              <button type="button" disabled={finish.isPending} onClick={() => finish.mutate()}>
                {t("rec.finish")}
              </button>
            </div>
            {accept.data && <p role="status">{t("rec.accepted", { count: accept.data.matched })}</p>}
            <ErrorLine error={accept.error ?? finish.error} />
          </section>
          <div className="table-wrap no-clip">
            <table aria-label={t("rec.lines")}>
              <thead>
                <tr>
                  <th>{t("bs.date")}</th>
                  <th>{t("bs.description")}</th>
                  <th className="num">{t("bs.out")}</th>
                  <th className="num">{t("bs.in")}</th>
                  <th>{t("rec.inBooks")}</th>
                </tr>
              </thead>
              <tbody>
                {d.lines.map((line) => (
                  <LineRow key={line.id} line={line} onDone={refresh} />
                ))}
              </tbody>
            </table>
          </div>
          {d.unpresented.length > 0 && (
            <section className="panel" aria-label={t("rec.unpresented")}>
              <h2>{t("rec.unpresented")}</h2>
              <ul className="plain-list">
                {d.unpresented.map((i) => (
                  <li key={i.entry.id}>
                    {i.date} · {i.entry.number} · {i.narration} · {money(i.amount)}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
      <Rules />
    </main>
  );
}

function LineRow({ line, onDone }: { line: RecLine; onDone: () => void }) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<"" | "find" | "post">("");
  const match = useMutation({ mutationFn: (entry: number) => matchLine(line.id, entry), onSuccess: onDone });
  const unmatch = useMutation({ mutationFn: () => unmatchLine(line.id), onSuccess: onDone });
  return (
    <tr>
      <td>{line.date}</td>
      <td>
        {line.description}
        {line.reference && <span className="muted"> {line.reference}</span>}
      </td>
      <td className="num">{Number(line.money_out) ? money(line.money_out) : ""}</td>
      <td className="num">{Number(line.money_in) ? money(line.money_in) : ""}</td>
      <td>
        {line.match ? (
          <>
            {line.match.entry.number} <span className="muted">{line.match.narration}</span>{" "}
            <button type="button" className="small secondary" disabled={unmatch.isPending} onClick={() => unmatch.mutate()}>
              {t("rec.unmatch")}
            </button>
          </>
        ) : (
          <>
            {line.suggestion && (
              <div>
                {t("rec.suggested")}: {line.suggestion.entry.number} · {line.suggestion.narration}{" "}
                <button type="button" className="small" disabled={match.isPending} onClick={() => match.mutate(line.suggestion!.entry.id)}>
                  {t("rec.accept")}
                </button>
              </div>
            )}
            <button type="button" className="small secondary" onClick={() => setMode(mode === "find" ? "" : "find")}>
              {t("rec.find")}
            </button>{" "}
            <button type="button" className="small secondary" onClick={() => setMode(mode === "post" ? "" : "post")}>
              {t("rec.post")}
            </button>
            {mode === "find" && <Candidates line={line} onPick={(entry) => match.mutate(entry)} />}
            {mode === "post" && <PostForm line={line} onDone={onDone} />}
          </>
        )}
        <ErrorLine error={match.error ?? unmatch.error} />
      </td>
    </tr>
  );
}

function Candidates({ line, onPick }: { line: RecLine; onPick: (entry: number) => void }) {
  const { t } = useTranslation();
  const found = useQuery({ queryKey: [...reconciliationKey, "candidates", line.id], queryFn: () => getCandidates(line.id) });
  if (!found.data) return null;
  if (found.data.length === 0) return <p className="muted">{t("rec.noCandidates")}</p>;
  return (
    <ul className="plain-list">
      {found.data.map((c) => (
        <li key={c.entry.id}>
          <button type="button" className="link-button" onClick={() => onPick(c.entry.id)}>
            {c.entry.number}
          </button>{" "}
          {c.date} · {c.narration}
          {c.reference_found && ` · ${t("rec.referenceFound")}`}
        </li>
      ))}
    </ul>
  );
}

function PostForm({ line, onDone }: { line: RecLine; onDone: () => void }) {
  const { t } = useTranslation();
  const accounts = useQuery({ queryKey: [...chartKey, "accounts", false], queryFn: () => listLedgerAccounts(false) });
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions });
  const [account, setAccount] = useState(line.coding ? String(line.coding.ledger.id) : "");
  const [division, setDivision] = useState(line.coding?.division ?? "");
  const [description, setDescription] = useState(line.description);
  const post = useMutation({
    mutationFn: () => postLine({ line: line.id, account: Number(account), division, description }),
    onSuccess: onDone,
  });
  const usable = (accounts.data ?? []).filter(
    (a) => a.is_active && !a.merged_into && !["accounts_receivable", "accounts_payable", "bank"].includes(a.account_type),
  );
  return (
    <div className="inline-form" role="group" aria-label={t("rec.post")}>
      {line.coding && <span className="muted">{t(line.coding.from === "rule" ? "rec.fromRule" : "rec.fromEarlier")}</span>}
      <SearchSelect
        label={t("rec.postTo")}
        options={usable.map((a) => ({ value: String(a.id), label: `${a.number} ${a.full_name}`.trim() }))}
        value={account}
        onChange={setAccount}
      />
      <select aria-label={t("vouchers.division")} value={division} onChange={(e) => setDivision(e.target.value)}>
        <option value="">—</option>
        {divisions.data?.map((dv) => (
          <option key={dv.code} value={dv.code}>
            {dv.code}
          </option>
        ))}
      </select>
      <input aria-label={t("bs.description")} value={description} onChange={(e) => setDescription(e.target.value)} />
      <button type="button" className="small" disabled={post.isPending || !account} onClick={() => post.mutate()}>
        {t("rec.postButton")}
      </button>
      <ErrorLine error={post.error} />
    </div>
  );
}

function Rules() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const rules = useQuery({ queryKey: [...reconciliationKey, "rules"], queryFn: listRules });
  const accounts = useQuery({ queryKey: [...chartKey, "accounts", false], queryFn: () => listLedgerAccounts(false) });
  const [text, setText] = useState("");
  const [direction, setDirection] = useState("any");
  const [ledger, setLedger] = useState("");
  const [division, setDivision] = useState("");
  const save = useMutation({
    mutationFn: () => saveRule({ text, direction, ledger: Number(ledger), division, account: null }),
    onSuccess: () => {
      setText("");
      void queryClient.invalidateQueries({ queryKey: reconciliationKey });
    },
  });
  const usable = (accounts.data ?? []).filter(
    (a) => a.is_active && !["accounts_receivable", "accounts_payable", "bank"].includes(a.account_type),
  );
  return (
    <section className="panel" aria-label={t("rec.rules")}>
      <h2>{t("rec.rules")}</h2>
      <p className="muted">{t("rec.rulesHelp")}</p>
      <ul className="plain-list">
        {rules.data?.map((r) => (
          <li key={r.id}>
            "{r.text}" → {r.ledger.number} {r.ledger.name}
            {r.division && ` · ${r.division}`}
            {!r.is_active && ` · ${t("bs.inactive")}`}
          </li>
        ))}
      </ul>
      <div className="inline-form">
        <input aria-label={t("rec.ruleText")} placeholder={t("rec.ruleText")} value={text} onChange={(e) => setText(e.target.value)} />
        <select aria-label={t("rec.direction")} value={direction} onChange={(e) => setDirection(e.target.value)}>
          <option value="any">{t("rec.directions.any")}</option>
          <option value="out">{t("rec.directions.out")}</option>
          <option value="in">{t("rec.directions.in")}</option>
        </select>
        <SearchSelect
          label={t("rec.postTo")}
          options={usable.map((a) => ({ value: String(a.id), label: `${a.number} ${a.full_name}`.trim() }))}
          value={ledger}
          onChange={setLedger}
        />
        <input aria-label={t("vouchers.division")} placeholder="WS" maxLength={2} value={division} onChange={(e) => setDivision(e.target.value)} />
        <button type="button" disabled={save.isPending || !text || !ledger} onClick={() => save.mutate()}>
          {t("rec.addRule")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </section>
  );
}
