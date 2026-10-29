import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { ApiError, apiGet, apiSend } from "../api/client";
import { getVoucher, voucherFileUrl, vouchersKey, type VoucherSummary } from "../api/vouchers";
import VoucherActions from "../components/VoucherActions";
import { formatDecimal, sumDecimal } from "../lib/decimal";

interface Waiting extends VoucherSummary {
  submitted_at: string | null;
  waiting_level: number | null;
  last_comment: string;
}

type Choice = "approve" | "reject";

interface BulkResult {
  confirmed: number;
  approved: number;
  rejected: number;
  fully_approved: string[];
}

const waitingKey = [...vouchersKey, "waiting"];

/** Compare two decimal strings exactly (no floating point). */
function compare(a: string, b: string): number {
  const diff = sumDecimal([a, `-${b}`.replace("--", "")]);
  return diff.startsWith("-") ? -1 : diff === "0.00" ? 0 : 1;
}

/**
 * The Director's approval page (spec 4.4): tabs per voucher type with pending counts,
 * Approve and Reject columns with a reason, bulk ticks, Confirm and Reset; a side panel
 * with the scan and details; filters and totals. Usable on a phone.
 */
export default function DirectorPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const queue = useQuery({ queryKey: waitingKey, queryFn: () => apiGet<Waiting[]>("/vouchers/waiting/") });
  const [tab, setTab] = useState("");
  const [filter, setFilter] = useState({ from: "", to: "", payee: "", min: "", max: "", division: "" });
  const [choices, setChoices] = useState<Record<number, Choice | undefined>>({});
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [missing, setMissing] = useState<number[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [result, setResult] = useState<BulkResult | null>(null);

  const all = queue.data ?? [];
  const tabs = useMemo(() => {
    const counts = new Map<string, { name: string; count: number }>();
    for (const v of all) {
      const entry = counts.get(v.voucher_type.code) ?? { name: v.voucher_type.name, count: 0 };
      entry.count += 1;
      counts.set(v.voucher_type.code, entry);
    }
    return [...counts.entries()];
  }, [all]);
  const divisions = [...new Set(all.map((v) => v.division))].sort();
  const valid = (s: string) => /^\d+(\.\d{1,2})?$/.test(s.replace(/,/g, ""));
  const rows = all.filter(
    (v) =>
      (!tab || v.voucher_type.code === tab) &&
      (!filter.from || v.voucher_date >= filter.from) &&
      (!filter.to || v.voucher_date <= filter.to) &&
      (!filter.payee || (v.payee?.name ?? "").toLowerCase().includes(filter.payee.toLowerCase())) &&
      (!filter.division || v.division === filter.division) &&
      (!filter.min || !valid(filter.min) || compare(v.total_amount, filter.min.replace(/,/g, "")) >= 0) &&
      (!filter.max || !valid(filter.max) || compare(v.total_amount, filter.max.replace(/,/g, "")) <= 0),
  );
  const ticked = all.filter((v) => choices[v.id]);
  const toApprove = ticked.filter((v) => choices[v.id] === "approve");
  const toReject = ticked.filter((v) => choices[v.id] === "reject");

  const choose = (id: number, choice: Choice, on: boolean) => {
    setChoices((now) => ({ ...now, [id]: on ? choice : undefined }));
    setMissing((now) => now.filter((m) => m !== id));
    setConfirming(false);
  };
  const tickAll = (choice: Choice | undefined) => {
    setChoices((now) => ({ ...now, ...Object.fromEntries(rows.map((v) => [v.id, choice])) }));
    setMissing([]);
    setConfirming(false);
  };
  const reset = () => {
    setChoices({});
    setReasons({});
    setMissing([]);
    setConfirming(false);
  };

  const send = useMutation({
    mutationFn: () =>
      apiSend<BulkResult>("POST", "/vouchers/decisions/", {
        decisions: ticked.map((v) => ({ id: v.id, decision: choices[v.id], reason: reasons[v.id] ?? "" })),
      }),
    onSuccess: (data) => {
      setResult(data);
      reset();
      void queryClient.invalidateQueries({ queryKey: vouchersKey });
    },
    onError: (error) => {
      const errors = error instanceof ApiError ? (error.body as { errors?: Record<string, string> } | null)?.errors : undefined;
      if (errors) setMissing(Object.keys(errors).map(Number));
      setConfirming(false);
    },
  });

  function confirm() {
    setResult(null);
    const lacking = toReject.filter((v) => !(reasons[v.id] ?? "").trim()).map((v) => v.id);
    setMissing(lacking);
    if (lacking.length || !ticked.length) return;
    setConfirming(true);
  }

  const visibleTotal = sumDecimal(rows.map((v) => v.total_amount));
  const approveTotal = sumDecimal(toApprove.map((v) => v.total_amount));
  const serverErrors =
    send.error instanceof ApiError ? (send.error.body as { errors?: Record<string, string> } | null)?.errors : undefined;

  return (
    <main className="page director-page">
      <h1>{t("director.title")}</h1>
      <div role="tablist" aria-label={t("director.types")} className="tabs">
        <button type="button" role="tab" className={`tab ${tab === "" ? "active" : ""}`} aria-selected={tab === ""} onClick={() => setTab("")}>
          {t("director.all", { count: String(all.length) })}
        </button>
        {tabs.map(([code, { name, count }]) => (
          <button
            key={code}
            type="button"
            role="tab"
            className={`tab ${tab === code ? "active" : ""}`}
            aria-selected={tab === code}
            onClick={() => setTab(code)}
          >
            {name} ({count})
          </button>
        ))}
      </div>

      <details className="filters">
        <summary>{t("director.filters")}</summary>
        <div className="form-grid">
          <label>
            {t("director.from")}
            <input type="date" value={filter.from} onChange={(e) => setFilter((f) => ({ ...f, from: e.target.value }))} />
          </label>
          <label>
            {t("director.to")}
            <input type="date" value={filter.to} onChange={(e) => setFilter((f) => ({ ...f, to: e.target.value }))} />
          </label>
          <label>
            {t("director.payee")}
            <input value={filter.payee} onChange={(e) => setFilter((f) => ({ ...f, payee: e.target.value }))} />
          </label>
          <label>
            {t("director.min")}
            <input inputMode="decimal" value={filter.min} onChange={(e) => setFilter((f) => ({ ...f, min: e.target.value }))} />
          </label>
          <label>
            {t("director.max")}
            <input inputMode="decimal" value={filter.max} onChange={(e) => setFilter((f) => ({ ...f, max: e.target.value }))} />
          </label>
          <label>
            {t("director.division")}
            <select value={filter.division} onChange={(e) => setFilter((f) => ({ ...f, division: e.target.value }))}>
              <option value="">{t("director.allDivisions")}</option>
              {divisions.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
        </div>
      </details>

      {queue.data && all.length === 0 && <p className="muted">{t("director.empty")}</p>}
      {rows.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("director.title")}>
            <thead>
              <tr>
                <th>{t("vouchers.number")}</th>
                <th>{t("vouchers.date")}</th>
                <th>{t("vouchers.payee")}</th>
                <th>{t("director.division")}</th>
                <th className="num">{t("vouchers.total")}</th>
                <th>{t("director.approve")}</th>
                <th>{t("director.reject")}</th>
                <th>{t("director.reason")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((v) => (
                <tr key={v.id} className={missing.includes(v.id) ? "row-error" : undefined}>
                  <td>
                    <button type="button" className="link-button mono" onClick={() => setOpen(v.id)}>
                      {v.number}
                    </button>
                    {v.attachments > 0 && <span aria-label={t("vouchers.hasFiles")}> 📎</span>}
                    <VoucherActions voucher={v} />
                  </td>
                  <td>{v.voucher_date}</td>
                  <td>{v.payee?.name ?? v.voucher_type.name}</td>
                  <td>{v.division}</td>
                  <td className="num">{formatDecimal(v.total_amount)}</td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={t("director.approveOne", { number: v.number })}
                      checked={choices[v.id] === "approve"}
                      onChange={(e) => choose(v.id, "approve", e.target.checked)}
                    />
                  </td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={t("director.rejectOne", { number: v.number })}
                      checked={choices[v.id] === "reject"}
                      onChange={(e) => choose(v.id, "reject", e.target.checked)}
                    />
                  </td>
                  <td>
                    <input
                      aria-label={t("director.reasonFor", { number: v.number })}
                      value={reasons[v.id] ?? ""}
                      placeholder={choices[v.id] === "reject" ? t("director.reasonNeeded") : t("director.optional")}
                      onChange={(e) => {
                        setReasons((now) => ({ ...now, [v.id]: e.target.value }));
                        setMissing((now) => now.filter((m) => m !== v.id));
                      }}
                    />
                    {serverErrors?.[String(v.id)] && <div className="form-error">{serverErrors[String(v.id)]}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th colSpan={4}>{t("director.shown", { count: String(rows.length) })}</th>
                <th className="num">{formatDecimal(visibleTotal)}</th>
                <th colSpan={3} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {rows.length > 0 && (
        <div className="row-actions sticky-actions">
          <button type="button" className="secondary" onClick={() => tickAll("approve")}>
            {t("director.approveAll")}
          </button>
          <button type="button" className="secondary" onClick={() => tickAll("reject")}>
            {t("director.rejectAll")}
          </button>
          <button type="button" className="secondary" onClick={() => tickAll(undefined)}>
            {t("director.clearAll")}
          </button>
          <button type="button" onClick={confirm} disabled={send.isPending}>
            {t("director.confirm")}
          </button>
          <button type="button" className="secondary" onClick={reset}>
            {t("director.reset")}
          </button>
        </div>
      )}
      {missing.length > 0 && !serverErrors && (
        <p className="form-error" role="alert">
          {t("director.reasonsMissing")}
        </p>
      )}
      {send.error && (
        <p className="form-error" role="alert">
          {send.error instanceof ApiError && send.error.detail ? send.error.detail : t("common.error")}
        </p>
      )}
      {confirming && (
        <div className="panel notice" role="alertdialog" aria-label={t("director.check")}>
          <p>
            {t("director.summary", {
              approve: String(toApprove.length),
              total: formatDecimal(approveTotal),
              reject: String(toReject.length),
            })}
          </p>
          <div className="row-actions">
            <button type="button" onClick={() => send.mutate()} disabled={send.isPending}>
              {t("director.yes")}
            </button>
            <button type="button" className="secondary" onClick={() => setConfirming(false)}>
              {t("director.no")}
            </button>
          </div>
        </div>
      )}
      {result && (
        <p className="notice" role="status">
          {t("director.done", { approved: String(result.approved), rejected: String(result.rejected) })}
        </p>
      )}

      {open !== null && <SidePanel key={open} id={open} onClose={() => setOpen(null)} />}
    </main>
  );
}

function SidePanel({ id, onClose }: { id: number; onClose: () => void }) {
  const { t } = useTranslation();
  const voucher = useQuery({ queryKey: [...vouchersKey, "one", id], queryFn: () => getVoucher(id) });
  const v = voucher.data;
  if (!v) return null;
  const scan = v.attachments[0];
  const checked = [...v.approvals].reverse().find((a) => a.action === "approve" && a.level === 2);
  return (
    <aside className="side-panel" aria-label={t("director.details", { number: v.number })}>
      <div className="row-actions">
        <h2>
          <Link to={`/vouchers/${v.id}`}>{v.number}</Link>
        </h2>
        <button type="button" className="small secondary" onClick={onClose}>
          {t("director.close")}
        </button>
      </div>
      <p>
        {v.voucher_type.name} · {v.payee?.name ?? v.transfer_to?.code} · {v.division}
      </p>
      {v.payee_balance && (
        <p className="muted">{t("vouchers.outstanding", { amount: formatDecimal(v.payee_balance.outstanding) })}</p>
      )}
      {checked && (
        <p>
          {t("director.accountantSaid", { name: checked.user })}: <em>{checked.reason || t("director.noComment")}</em>
        </p>
      )}
      {v.warnings.map((w) => (
        <p key={w} className="notice">
          ⚠ {w}
        </p>
      ))}
      <div className="preview">
        {scan?.content_type === "application/pdf" && <iframe title={scan.file_name} src={voucherFileUrl(v.id, scan.id)} />}
        {scan && scan.content_type !== "application/pdf" && <img alt={scan.file_name} src={voucherFileUrl(v.id, scan.id)} />}
      </div>
      <table aria-label={t("vouchers.lines")}>
        <tbody>
          {v.lines.map((l) => (
            <tr key={l.line_no}>
              <td>
                {l.invoice_no}
                <div className="muted">
                  {l.account ? `${l.account.number} ${l.account.name}` : ""} ·{" "}
                  {l.splits.length ? l.splits.map((s) => `${s.division} ${formatDecimal(s.amount)}`).join(", ") : l.division}
                </div>
              </td>
              <td className="num">{formatDecimal(l.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </aside>
  );
}
