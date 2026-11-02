import { useQuery } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";
import { useTranslation } from "react-i18next";

import { chartKey, listLedgerAccounts } from "../api/accounts";
import { listDivisions } from "../api/admin";
import type { MJLine, MJLineInput } from "../api/manualJournals";
import { listPayees } from "../api/payees";
import { formatDecimal, sumDecimal } from "../lib/decimal";
import SearchSelect from "./SearchSelect";

export type LineState = { account: string; debit: string; credit: string; division: string; supplier: string; description: string };
export const blankLine: LineState = { account: "", debit: "", credit: "", division: "", supplier: "", description: "" };

export function linesFrom(lines: MJLine[] | undefined): LineState[] {
  if (!lines) return [{ ...blankLine }, { ...blankLine }];
  return lines.map((l) => ({
    account: String(l.account.id),
    debit: l.debit === "0.00" ? "" : l.debit,
    credit: l.credit === "0.00" ? "" : l.credit,
    division: l.division ?? "",
    supplier: l.supplier ? String(l.supplier.id) : "",
    description: l.description,
  }));
}

/** The ledger accounts a journal may use: active, and never receivables (customer balances
 * change only through sales documents). */
export function useJournalAccounts() {
  const accounts = useQuery({ queryKey: [...chartKey, "accounts", false], queryFn: () => listLedgerAccounts(false) });
  return (accounts.data ?? []).filter((a) => a.is_active && !a.merged_into && a.account_type !== "accounts_receivable");
}

export function toInputs(lines: LineState[], accountList: { id: number; account_type: string }[]): MJLineInput[] {
  const typeOf = (id: string) => accountList.find((a) => String(a.id) === id)?.account_type ?? "";
  return lines.map((l) => ({
    account: Number(l.account),
    debit: l.debit,
    credit: l.credit,
    division: l.division || null,
    supplier: typeOf(l.account) === "accounts_payable" && l.supplier ? Number(l.supplier) : null,
    description: l.description,
  }));
}

/** Exact totals of what is typed; anything that is not a number counts as nothing yet. */
function total(values: string[]): string {
  const clean = values.map((v) => v.replace(/,/g, "").trim()).filter((v) => /^\d+(\.\d{1,2})?$/.test(v));
  return sumDecimal(clean);
}

export function JournalTotals({ lines }: { lines: LineState[] }) {
  const { t } = useTranslation();
  const debits = total(lines.map((l) => l.debit));
  const credits = total(lines.map((l) => l.credit));
  const difference = sumDecimal([debits, `-${credits}`]);
  return (
    <p aria-label={t("mj.totals")}>
      {t("mj.debit")}: <strong>{formatDecimal(debits)}</strong> · {t("mj.credit")}: <strong>{formatDecimal(credits)}</strong>
      {difference !== "0.00" && <span className="form-error"> · {t("mj.outBy", { amount: formatDecimal(difference.replace("-", "")) })}</span>}
    </p>
  );
}

/** The lines of a journal or a recurring journal template: account, debit, credit, division,
 * and the supplier on a payables line. */
export default function JournalLines({
  lines,
  setLines,
  accountList,
}: {
  lines: LineState[];
  setLines: Dispatch<SetStateAction<LineState[]>>;
  accountList: { id: number; number: string; full_name: string; account_type: string }[];
}) {
  const { t } = useTranslation();
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions });
  const suppliers = useQuery({ queryKey: ["payees", "", false], queryFn: () => listPayees("", false) });
  const setLine = (index: number, change: Partial<LineState>) => setLines((now) => now.map((l, i) => (i === index ? { ...l, ...change } : l)));
  const accountOptions = accountList.map((a) => ({ value: String(a.id), label: `${a.number ? `${a.number} ` : ""}${a.full_name}` }));
  const typeOf = (accountId: string) => accountList.find((a) => String(a.id) === accountId)?.account_type ?? "";
  const supplierOptions = (suppliers.data ?? []).map((s) => ({ value: String(s.id), label: `${s.code} ${s.name}` }));

  return (
    <div className="wide">
      <h2>{t("mj.lines")}</h2>
      {lines.map((l, index) => {
        const n = String(index + 1);
        return (
          <fieldset key={index} className="quote-line">
            <legend>{t("quotations.lineN", { n })}</legend>
            <div className="form-grid">
              <div className="wide">
                <SearchSelect label={t("mj.accountOf", { n })} options={accountOptions} value={l.account} onChange={(value) => setLine(index, { account: value })} />
              </div>
              <label>
                {t("mj.debit")}
                <input inputMode="decimal" className="num" aria-label={t("mj.debitOf", { n })} value={l.debit} onChange={(e) => setLine(index, { debit: e.target.value })} />
              </label>
              <label>
                {t("mj.credit")}
                <input inputMode="decimal" className="num" aria-label={t("mj.creditOf", { n })} value={l.credit} onChange={(e) => setLine(index, { credit: e.target.value })} />
              </label>
              <label>
                {t("vouchers.division")}
                <select aria-label={t("mj.divisionOf", { n })} value={l.division} onChange={(e) => setLine(index, { division: e.target.value })}>
                  <option value="">—</option>
                  {(divisions.data ?? []).map((d) => (
                    <option key={d.code} value={d.code}>
                      {d.code} {d.name}
                    </option>
                  ))}
                </select>
              </label>
              {typeOf(l.account) === "accounts_payable" && (
                <div className="wide">
                  <SearchSelect label={t("mj.supplierOf", { n })} options={supplierOptions} value={l.supplier} onChange={(value) => setLine(index, { supplier: value })} />
                </div>
              )}
              <label className="wide">
                {t("quotations.description")}
                <input aria-label={t("mj.descriptionOf", { n })} value={l.description} maxLength={500} onChange={(e) => setLine(index, { description: e.target.value })} />
              </label>
            </div>
            {lines.length > 2 && (
              <button type="button" className="small secondary" onClick={() => setLines((now) => now.filter((_, i) => i !== index))}>
                {t("quotations.removeLine")}
              </button>
            )}
          </fieldset>
        );
      })}
      <button type="button" className="small secondary" onClick={() => setLines((now) => [...now, { ...blankLine }])}>
        {t("quotations.addLine")}
      </button>
    </div>
  );
}
