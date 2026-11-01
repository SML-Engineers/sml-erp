import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import { chartKey, listLedgerAccounts } from "../api/accounts";
import { listDivisions } from "../api/admin";
import { ApiError, apiGet, apiSend } from "../api/client";
import { getTaxes, taxesKey } from "../api/taxes";
import MatchedInvoice from "../components/MatchedInvoice";
import SearchSelect from "../components/SearchSelect";
import {
  getVoucher,
  voucherFileUrl,
  vouchersKey,
  type VoucherDetail,
  type VoucherLineData,
  type VoucherSummary,
} from "../api/vouchers";
import { formatDecimal } from "../lib/decimal";

interface Waiting extends VoucherSummary {
  submitted_at: string | null;
  waiting_level: number | null;
}

interface SplitRow {
  division: string;
  amount: string;
  percent: string;
}

interface Coding {
  line_no: number;
  account: string;
  division: string;
  tax_code: string;
  tax_amount: string;
  job_ref: string;
  split: boolean;
  byPercent: boolean;
  splits: SplitRow[];
}

const waitingKey = [...vouchersKey, "waiting"];

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** Vouchers waiting for my approval: the queue, with the invoice beside the details. */
export default function ReviewPage() {
  const { t } = useTranslation();
  const queue = useQuery({ queryKey: waitingKey, queryFn: () => apiGet<Waiting[]>("/vouchers/waiting/") });
  const [search] = useSearchParams();
  const [selected, setSelected] = useState<number | null>(Number(search.get("open")) || null);
  // Open the first voucher in the queue, and the next one after a decision (skipping those
  // just decided, which stay in the list until it is fetched again).
  const [decided, setDecided] = useState<number[]>([]);
  const first = queue.data?.find((v) => !decided.includes(v.id))?.id ?? null;
  useEffect(() => {
    if (selected === null && first !== null) setSelected(first);
  }, [selected, first]);

  return (
    <main className="page">
      <h1>{t("voucherReview.title")}</h1>
      <p className="muted">{t("voucherReview.help")}</p>
      <div className="review-layout">
        <section className="panel" aria-label={t("voucherReview.queue")}>
          <h2>{t("voucherReview.queue")}</h2>
          {queue.data?.length === 0 && <p className="muted">{t("voucherReview.empty")}</p>}
          <ul className="queue">
            {queue.data?.map((v) => (
              <li key={v.id} className={v.id === selected ? "selected" : undefined}>
                <button type="button" className="link-button" onClick={() => setSelected(v.id)}>
                  <span className="mono">{v.number}</span> · {v.payee?.name ?? v.voucher_type.name}
                </button>
                <span className="muted">
                  {v.voucher_type.name} · L{v.waiting_level} · LKR {formatDecimal(v.total_amount)}
                </span>
              </li>
            ))}
          </ul>
          <ErrorLine error={queue.error} />
        </section>
        {selected !== null && (
          <ReviewPanel
            key={selected}
            id={selected}
            onDone={() => {
              setDecided((now) => [...now, selected]);
              setSelected(null);
            }}
          />
        )}
      </div>
    </main>
  );
}

function toCoding(line: VoucherLineData, fallbackDivision: string): Coding {
  return {
    line_no: line.line_no,
    account: line.account ? String(line.account.id) : "",
    division: line.division ?? (line.splits.length ? "" : fallbackDivision),
    tax_code: line.tax_code ?? "",
    tax_amount: line.tax_amount,
    job_ref: line.job_ref,
    split: line.splits.length > 0,
    byPercent: line.splits.some((s) => s.percent !== null),
    splits: line.splits.length
      ? line.splits.map((s) => ({ division: s.division, amount: s.amount, percent: s.percent ?? "" }))
      : [
          { division: fallbackDivision, amount: "", percent: "" },
          { division: "", amount: "", percent: "" },
        ],
  };
}

function ReviewPanel({ id, onDone }: { id: number; onDone: () => void }) {
  const queryClient = useQueryClient();
  const key = [...vouchersKey, "one", id];
  const voucher = useQuery({ queryKey: key, queryFn: () => getVoucher(id) });
  if (!voucher.data) return <ErrorLine error={voucher.error} />;
  const refresh = (data: VoucherDetail) => {
    queryClient.setQueryData(key, data);
    void queryClient.invalidateQueries({ queryKey: waitingKey });
  };
  return <ReviewForm voucher={voucher.data} onSaved={refresh} onDone={onDone} />;
}

function ReviewForm(props: { voucher: VoucherDetail; onSaved: (v: VoucherDetail) => void; onDone: () => void }) {
  const { t } = useTranslation();
  const { voucher } = props;
  const accounts = useQuery({ queryKey: [...chartKey, "accounts", false], queryFn: () => listLedgerAccounts(false) });
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions });
  const taxes = useQuery({ queryKey: taxesKey, queryFn: getTaxes });
  const [codings, setCodings] = useState<Coding[]>(voucher.lines.map((l) => toCoding(l, voucher.division)));
  const [saved, setSaved] = useState(JSON.stringify(codings));
  const unsaved = JSON.stringify(codings) !== saved;
  const [text, setText] = useState("");
  const [file, setFile] = useState(voucher.attachments[0]?.id ?? null);
  const purchaseCodes = (taxes.data?.codes ?? []).filter((c) => c.is_active && c.use !== "sales");
  const usable = (accounts.data ?? []).filter(
    (a) => a.is_active && !a.merged_into && !["accounts_receivable", "accounts_payable"].includes(a.account_type),
  );

  const set = (index: number, change: Partial<Coding>) =>
    setCodings((now) => now.map((c, i) => (i === index ? { ...c, ...change } : c)));
  const setSplit = (index: number, row: number, change: Partial<SplitRow>) =>
    setCodings((now) =>
      now.map((c, i) => (i === index ? { ...c, splits: c.splits.map((s, r) => (r === row ? { ...s, ...change } : s)) } : c)),
    );

  const saveCoding = () =>
    apiSend<VoucherDetail>("PATCH", `/vouchers/${voucher.id}/coding/`, {
      lines: codings.map((c) => ({
        line_no: c.line_no,
        account: c.account ? Number(c.account) : null,
        division: c.split ? null : c.division || null,
        tax_code: c.tax_code || null,
        tax_amount: c.tax_code ? "0" : c.tax_amount || "0",
        job_ref: c.job_ref,
        splits: c.split
          ? c.splits.map((s) => (c.byPercent ? { division: s.division, percent: s.percent } : { division: s.division, amount: s.amount }))
          : [],
      })),
    });
  const save = useMutation({
    mutationFn: saveCoding,
    onSuccess: (data) => {
      setSaved(JSON.stringify(codings));
      props.onSaved(data);
    },
  });
  const decide = useMutation({
    mutationFn: async (decision: "approve" | "return" | "reject") => {
      // Approving uses the coding on the screen: save it first (it stops here if it is wrong).
      if (decision === "approve" && unsaved) {
        props.onSaved(await saveCoding());
        setSaved(JSON.stringify(codings));
      }
      return apiSend<VoucherDetail>("POST", `/vouchers/${voucher.id}/${decision}/`, decision === "approve" ? { comment: text } : { reason: text });
    },
    onSuccess: (data) => {
      props.onSaved(data);
      props.onDone();
    },
  });
  const current = voucher.attachments.find((a) => a.id === file);
  const title = `${t("vouchers.voucher")} ${voucher.number}`;

  return (
    <section className="panel review-panel" aria-label={title}>
      <h2>
        <Link to={`/vouchers/${voucher.id}`}>{title}</Link>
      </h2>
      <p>
        {voucher.voucher_type.name} · {voucher.payee?.name ?? voucher.transfer_to?.code} · {voucher.division} ·{" "}
        {t("vouchers.createdBy", { name: voucher.created_by })}
      </p>
      {voucher.payee_balance && (
        <p className="muted">{t("vouchers.outstanding", { amount: formatDecimal(voucher.payee_balance.outstanding) })}</p>
      )}
      {voucher.warnings.map((w) => (
        <p key={w} className="notice">
          ⚠ {w}
        </p>
      ))}
      {voucher.approvals.at(-1)?.action === "send_down" && (
        <p className="notice change-notice" role="status">
          {t("voucherActions.sentBack", { name: voucher.approvals.at(-1)!.user })} {voucher.approvals.at(-1)!.reason}
        </p>
      )}

      <div className="preview" aria-label={t("voucherReview.preview")} role="group">
        {voucher.attachments.length > 1 && (
          <select aria-label={t("voucherReview.whichFile")} value={file ?? ""} onChange={(e) => setFile(Number(e.target.value))}>
            {voucher.attachments.map((a) => (
              <option key={a.id} value={a.id}>
                {a.file_name}
              </option>
            ))}
          </select>
        )}
        {current?.content_type === "application/pdf" && (
          <iframe title={current.file_name} src={voucherFileUrl(voucher.id, current.id)} />
        )}
        {current && current.content_type !== "application/pdf" && (
          <img alt={current.file_name} src={voucherFileUrl(voucher.id, current.id)} />
        )}
        {!current && <p className="muted">{t("voucherReview.noScan")}</p>}
      </div>

      {voucher.lines
        .filter((l) => l.supplier_invoice)
        .map((l) => (
          <MatchedInvoice key={l.line_no} invoice={l.supplier_invoice!} />
        ))}
      <div className="table-wrap no-clip">
        <table aria-label={t("voucherReview.coding")} className="coding-table">
          <thead>
            <tr>
              <th>{t("vouchers.invoiceNo")}</th>
              <th className="num">{t("vouchers.amount")}</th>
              <th>{t("voucherReview.account")}</th>
              <th>{t("vouchers.division")}</th>
              <th>{t("vouchers.taxCode")}</th>
              <th className="num">{t("vouchers.tax")}</th>
              <th>{t("voucherReview.job")}</th>
            </tr>
          </thead>
          <tbody>
            {voucher.lines.map((line, index) => {
              const c = codings[index];
              const n = String(line.line_no);
              if (line.supplier_invoice) {
                // Pays a matched supplier invoice: always Accounts payable, no tax (P16-11).
                return (
                  <tr key={line.line_no}>
                    <td>
                      {line.invoice_no}
                      {line.description && <div className="muted">{line.description}</div>}
                    </td>
                    <td className="num">{formatDecimal(line.amount)}</td>
                    <td colSpan={4}>
                      {line.account?.number} {line.account?.name} · {line.division} ·{" "}
                      <span className="muted">{t("vouchers.paysMatchedInvoice")}</span>
                    </td>
                    <td>
                      <input aria-label={t("voucherReview.jobOf", { n })} value={c.job_ref} maxLength={50} onChange={(e) => set(index, { job_ref: e.target.value })} />
                    </td>
                  </tr>
                );
              }
              return (
                <tr key={line.line_no}>
                  <td>
                    {line.invoice_no}
                    {line.invoice_date && <span className="muted"> {line.invoice_date}</span>}
                    {line.description && <div className="muted">{line.description}</div>}
                  </td>
                  <td className="num">{formatDecimal(line.amount)}</td>
                  <td>
                    <SearchSelect
                      label={t("voucherReview.accountOf", { n })}
                      options={usable.map((a) => ({ value: String(a.id), label: `${a.number} ${a.full_name}`.trim() }))}
                      value={c.account}
                      onChange={(value) => {
                        const chosen = usable.find((a) => String(a.id) === value);
                        set(index, {
                          account: value,
                          // the account's defaults, as QuickBooks does
                          ...(chosen?.default_division && !c.split ? { division: chosen.default_division } : {}),
                          ...(chosen?.default_tax_code && !c.tax_code ? { tax_code: chosen.default_tax_code } : {}),
                        });
                      }}
                    />
                  </td>
                  <td>
                    {!c.split && (
                      <select aria-label={t("voucherReview.divisionOf", { n })} value={c.division} onChange={(e) => set(index, { division: e.target.value })}>
                        <option value="">—</option>
                        {divisions.data?.map((d) => (
                          <option key={d.code} value={d.code}>
                            {d.code}
                          </option>
                        ))}
                      </select>
                    )}
                    <label className="check">
                      <input type="checkbox" checked={c.split} onChange={(e) => set(index, { split: e.target.checked })} />
                      {t("voucherReview.split")}
                    </label>
                    {c.split && (
                      <div role="group" aria-label={t("voucherReview.splitOf", { n })}>
                        <label className="check">
                          <input type="checkbox" checked={c.byPercent} onChange={(e) => set(index, { byPercent: e.target.checked })} />
                          {t("voucherReview.byPercent")}
                        </label>
                        {c.splits.map((s, row) => (
                          <div key={row} className="split-row">
                            <select
                              aria-label={t("voucherReview.splitDivision", { n, row: String(row + 1) })}
                              value={s.division}
                              onChange={(e) => setSplit(index, row, { division: e.target.value })}
                            >
                              <option value="">—</option>
                              {divisions.data?.map((d) => (
                                <option key={d.code} value={d.code}>
                                  {d.code}
                                </option>
                              ))}
                            </select>
                            <input
                              inputMode="decimal"
                              aria-label={c.byPercent ? t("voucherReview.splitPercent", { n, row: String(row + 1) }) : t("voucherReview.splitAmount", { n, row: String(row + 1) })}
                              value={c.byPercent ? s.percent : s.amount}
                              onChange={(e) => setSplit(index, row, c.byPercent ? { percent: e.target.value } : { amount: e.target.value })}
                            />
                          </div>
                        ))}
                        <button
                          type="button"
                          className="small secondary"
                          onClick={() => set(index, { splits: [...c.splits, { division: "", amount: "", percent: "" }] })}
                        >
                          {t("voucherReview.addDivision")}
                        </button>
                      </div>
                    )}
                  </td>
                  <td>
                    <select aria-label={t("voucherReview.taxCodeOf", { n })} value={c.tax_code} onChange={(e) => set(index, { tax_code: e.target.value })}>
                      <option value="">{t("vouchers.enterTax")}</option>
                      {purchaseCodes.map((code) => (
                        <option key={code.code} value={code.code}>
                          {code.code}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="num">
                    {c.tax_code ? (
                      formatDecimal(line.tax_amount)
                    ) : (
                      <input
                        inputMode="decimal"
                        className="num"
                        aria-label={t("voucherReview.taxOf", { n })}
                        value={c.tax_amount}
                        onChange={(e) => set(index, { tax_amount: e.target.value })}
                      />
                    )}
                  </td>
                  <td>
                    <input aria-label={t("voucherReview.jobOf", { n })} value={c.job_ref} maxLength={50} onChange={(e) => set(index, { job_ref: e.target.value })} />
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={5}>{t("vouchers.total")}</th>
              <th className="num" colSpan={2}>
                LKR {formatDecimal(voucher.total_amount)}
              </th>
            </tr>
          </tfoot>
        </table>
      </div>
      <div className="row-actions">
        <button type="button" className="secondary" disabled={save.isPending} onClick={() => save.mutate()}>
          {t("voucherReview.saveCoding")}
        </button>
        {unsaved && (
          <span className="muted" role="status">
            {t("voucherReview.unsaved")}
          </span>
        )}
      </div>
      <ErrorLine error={save.error} />

      <label className="inline-form">
        {t("voucherReview.commentOrReason")}
        <input value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <div className="row-actions">
        <button type="button" disabled={decide.isPending} onClick={() => decide.mutate("approve")}>
          {t("voucherReview.approve")}
        </button>
        <button type="button" className="secondary" disabled={decide.isPending} onClick={() => decide.mutate("return")}>
          {t("voucherReview.return")}
        </button>
        <button type="button" className="danger" disabled={decide.isPending} onClick={() => decide.mutate("reject")}>
          {t("voucherReview.reject")}
        </button>
      </div>
      <p className="muted">{t("voucherReview.saveFirst")}</p>
      <ErrorLine error={decide.error} />
    </section>
  );
}
