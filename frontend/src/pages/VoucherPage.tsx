import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type DragEvent, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { listDivisions } from "../api/admin";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import { approvePaymentCancellation, cancelPayment, rejectPaymentCancellation, whtCertificateUrl } from "../api/payments";
import { listPayees } from "../api/payees";
import { getAdvanceOrders, getPayableInvoices } from "../api/supplierInvoices";
import { getTaxes, taxesKey } from "../api/taxes";
import {
  createVoucher,
  decideCancellation,
  getPayeeBalance,
  getVoucher,
  listTransferAccounts,
  listVoucherTypes,
  removeVoucherFile,
  reviseVoucher,
  submitVoucher,
  updateVoucher,
  uploadVoucherFile,
  voucherFileUrl,
  voucherTypesKey,
  vouchersKey,
  type Cancellation,
  type VoucherDetail,
  type VoucherLineInput,
} from "../api/vouchers";
import MatchedInvoice from "../components/MatchedInvoice";
import { SentBackNotice } from "../components/SentBackNotice";
import VoucherActions from "../components/VoucherActions";
import { formatDecimal, sumDecimal } from "../lib/decimal";
import { formatDateTime } from "../lib/time";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

const ACCEPT = "application/pdf,image/jpeg,image/png";
const emptyLine = (): VoucherLineInput => ({
  invoice_no: "",
  invoice_date: null,
  description: "",
  amount: "",
  tax_code: null,
  tax_amount: "0.00",
});

/** One voucher: the Clerk's form while it is a draft or returned, otherwise its details. */
export default function VoucherPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const param = useParams().id;
  const [search] = useSearchParams();
  const id = param === "new" ? null : Number(param);
  const voucher = useQuery({
    queryKey: [...vouchersKey, "one", id],
    queryFn: () => getVoucher(id!),
    enabled: id !== null,
  });

  if (id !== null && !voucher.data) {
    return (
      <main className="page">
        <ErrorLine error={voucher.error} />
      </main>
    );
  }
  const data = voucher.data;
  const revising = Boolean(data?.actions?.includes("revise") && search.get("edit") === "1");
  const returned =
    data?.status === "returned" ? [...data.approvals].reverse().find((a) => a.action === "return") : undefined;
  return (
    <main className="page">
      <p>
        <Link to="/vouchers">{t("vouchers.backToList")}</Link>
      </p>
      <div className="title-row">
        <h1>{data ? `${t("vouchers.voucher")} ${data.number}` : t("vouchers.new")}</h1>
        {data && <VoucherActions voucher={data} showLabel onDeleted={() => navigate("/vouchers")} />}
      </div>
      {data?.deleted && (
        <p className="notice change-notice" role="status">
          {t("voucherActions.deletedBy", {
            name: data.deleted.by,
            when: formatDateTime(data.deleted.at),
          })}
          {data.deleted.reason && ` — ${data.deleted.reason}`}
        </p>
      )}
      {data?.parent && (
        <p className="notice" role="status">
          {t("amendments.amendmentOf", { revision: String(data.revision) })}{" "}
          <Link to={`/vouchers/${data.parent.id}`}>{data.parent.number}</Link>
          {data.amendment_reason && ` — ${data.amendment_reason}`}
        </p>
      )}
      {data && data.revisions.length > 0 && (
        <p className="notice change-notice" role="status">
          {data.status === "amended" ? t("amendments.replacedBy") : t("amendments.amendedBy")}{" "}
          {data.revisions.map((r, i) => (
            <span key={r.id}>
              {i > 0 && ", "}
              <Link to={`/vouchers/${r.id}`}>{r.number}</Link> ({t(`vouchers.statuses.${r.status}`)})
            </span>
          ))}
        </p>
      )}
      {returned && (
        <p className="notice change-notice" role="status">
          {t("amendments.returnedBy", { name: returned.user })} {returned.reason}
        </p>
      )}
      {data && <SentBackNotice approvals={data.approvals} />}
      {data && (
        <p className="muted">
          {t(`vouchers.statuses.${data.status}`)} · {data.division} · {data.voucher_date} ·{" "}
          {t("vouchers.createdBy", { name: data.created_by })}
        </p>
      )}
      {data?.warnings.map((w) => (
        <p key={w} className="notice" role="status">
          ⚠ {w}
        </p>
      ))}
      {revising && data && (
        <p className="notice" role="note">
          {t("voucherActions.reviseHelp")}
        </p>
      )}
      {!data || data.can_edit || revising ? (
        <VoucherForm key={`${data?.id ?? "new"}-${revising}`} me={me} voucher={data} revise={revising} />
      ) : (
        <ReadOnly voucher={data} />
      )}
      {data?.cancellation && <CancellationPanel voucher={data} request={data.cancellation} />}
      {data && <Attachments voucher={data} />}
      {data?.can_edit && <Submit voucher={data} />}
      {data && (data.payments?.length ?? 0) > 0 && <Payments voucher={data} />}
      {data && data.approvals.length > 0 && <History voucher={data} />}
    </main>
  );
}

/** The voucher form: the Clerk's draft, or (revise) an approver's changes while it waits
 * for them; the Director's change to the payee, amounts or lines goes back to the Accountant. */
function VoucherForm({ voucher, revise = false }: { me: CurrentUser; voucher?: VoucherDetail; revise?: boolean }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const types = useQuery({ queryKey: [...voucherTypesKey, false], queryFn: () => listVoucherTypes(false) });
  const divisions = useQuery({ queryKey: ["divisions", "mine"], queryFn: listDivisions, enabled: !voucher });
  const taxes = useQuery({ queryKey: taxesKey, queryFn: getTaxes });
  const accounts = useQuery({ queryKey: [...vouchersKey, "transfer-accounts"], queryFn: listTransferAccounts });
  const [division, setDivision] = useState(voucher?.division ?? "");
  const [typeCode, setTypeCode] = useState(voucher?.voucher_type.code ?? "");
  const [payeeSearch, setPayeeSearch] = useState("");
  const [payee, setPayee] = useState<{ id: number; name: string } | null>(voucher?.payee ?? null);
  const [transferTo, setTransferTo] = useState(voucher?.transfer_to ? String(voucher.transfer_to.id) : "");
  const [description, setDescription] = useState(voucher?.description ?? "");
  const [lines, setLines] = useState<VoucherLineInput[]>(
    voucher?.lines.map((l) => ({
      invoice_no: l.invoice_no,
      invoice_date: l.invoice_date,
      description: l.description,
      amount: l.amount,
      tax_code: l.tax_code,
      tax_amount: l.tax_amount,
      supplier_invoice: l.supplier_invoice?.id ?? null,
      advance_order: l.advance_order?.id ?? null,
    })) ?? [emptyLine()],
  );
  const type = types.data?.find((x) => x.code === typeCode);
  const payees = useQuery({
    queryKey: ["payees", "search", payeeSearch],
    queryFn: () => listPayees(payeeSearch, false),
    enabled: Boolean(type?.needs_payee) && payeeSearch.length >= 2,
  });
  const balance = useQuery({
    queryKey: [...vouchersKey, "balance", payee?.id],
    queryFn: () => getPayeeBalance(payee!.id),
    enabled: payee !== null,
  });
  const purchaseCodes = (taxes.data?.codes ?? []).filter((c) => c.is_active && c.use !== "sales");
  const voucherDivision = voucher?.division ?? division;
  const payable = useQuery({
    queryKey: ["supplier-invoices", "payable", payee?.id, voucherDivision],
    queryFn: () => getPayableInvoices(payee!.id, voucherDivision),
    enabled: payee !== null && Boolean(voucherDivision) && !revise,
  });
  const onVoucher = new Set(lines.map((l) => l.supplier_invoice).filter(Boolean));
  const [showAdvance, setShowAdvance] = useState(false);
  const advanceOrders = useQuery({
    queryKey: ["supplier-invoices", "advance-orders", payee?.id, voucherDivision],
    queryFn: () => getAdvanceOrders(payee!.id, voucherDivision),
    enabled: showAdvance && payee !== null && Boolean(voucherDivision) && !revise,
  });
  function payAdvance(order: { id: number; label: string; left: string }) {
    const line: VoucherLineInput = {
      invoice_no: "",
      invoice_date: null,
      description: "",
      amount: order.left,
      tax_code: null,
      tax_amount: "0.00",
      advance_order: order.id,
    };
    setLines((now) => [...now.filter((l) => l.supplier_invoice || l.advance_order || l.amount || l.invoice_no || l.description), line]);
    setShowAdvance(false);
  }
  function payInvoice(invoice: { id: number; number: string; invoice_no: string; invoice_date: string; unpaid: string }) {
    const line: VoucherLineInput = {
      invoice_no: invoice.invoice_no,
      invoice_date: invoice.invoice_date,
      description: `Supplier invoice ${invoice.number}`,
      amount: invoice.unpaid,
      tax_code: null,
      tax_amount: "0.00",
      supplier_invoice: invoice.id,
    };
    setLines((now) => {
      const kept = now.filter((l) => l.supplier_invoice || l.amount || l.invoice_no || l.description);
      return [...kept, line];
    });
  }
  const candidates = (payees.data ?? []).filter((p) => !type?.payee_category || p.category === type.payee_category);

  const save = useMutation({
    mutationFn: () => {
      const input = {
        voucher_type: typeCode,
        division: voucher ? undefined : division,
        payee: type?.needs_payee ? (payee?.id ?? null) : null,
        transfer_to: type && !type.needs_payee && transferTo ? Number(transferTo) : null,
        description,
        lines: lines.map((l) => ({ ...l, tax_amount: l.tax_code ? "0" : l.tax_amount || "0" })),
      };
      if (voucher && revise) return reviseVoucher(voucher.id, input);
      return voucher ? updateVoucher(voucher.id, input) : createVoucher(input);
    },
    onSuccess: (saved) => {
      queryClient.setQueryData([...vouchersKey, "one", saved.id], saved);
      void queryClient.invalidateQueries({ queryKey: vouchersKey });
      if (!voucher || revise) navigate(`/vouchers/${saved.id}`);
    },
  });

  const setLine = (index: number, change: Partial<VoucherLineInput>) =>
    setLines((now) => now.map((l, i) => (i === index ? { ...l, ...change } : l)));
  const manualTotal = sumDecimal(
    lines.flatMap((l) => [l.amount || "0", l.tax_code ? "0" : l.tax_amount || "0"]).map((v) => (/^-?\d+(\.\d+)?$/.test(v) ? v : "0")),
  );

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="panel form-grid" aria-label={t("vouchers.form")} onSubmit={submit}>
      {!voucher && (
        <label>
          {t("vouchers.division")}
          <select value={division} required onChange={(e) => setDivision(e.target.value)}>
            <option value="">—</option>
            {divisions.data?.map((d) => (
              <option key={d.code} value={d.code}>
                {d.code} {d.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        {t("vouchers.type")}
        <select value={typeCode} required disabled={revise} onChange={(e) => setTypeCode(e.target.value)}>
          <option value="">—</option>
          {types.data?.map((x) => (
            <option key={x.code} value={x.code}>
              {x.name}
            </option>
          ))}
        </select>
      </label>
      {(!type || type.needs_payee) && (
        <div className="wide">
          <label>
            {t("vouchers.findPayee")}
            <input
              value={payeeSearch}
              disabled={!type}
              placeholder={type ? t("vouchers.payeeHint") : t("vouchers.chooseTypeFirst")}
              onChange={(e) => setPayeeSearch(e.target.value)}
            />
          </label>
          {candidates.length > 0 && (
            <ul className="changes" aria-label={t("vouchers.payeeResults")}>
              {candidates.slice(0, 10).map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => {
                      setPayee({ id: p.id, name: p.name });
                      setPayeeSearch(""); // chosen: close the list
                    }}
                  >
                    {p.code} {p.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p>
            {t("vouchers.payee")}: <strong>{payee?.name ?? t("vouchers.noPayeeYet")}</strong>
            {balance.data && (
              <span className="muted">
                {" "}
                · {t("vouchers.outstanding", { amount: formatDecimal(balance.data.outstanding) })}
              </span>
            )}
          </p>
        </div>
      )}
      {type && !type.needs_payee && (
        <label>
          {t("vouchers.transferTo")}
          <select value={transferTo} onChange={(e) => setTransferTo(e.target.value)}>
            <option value="">—</option>
            {accounts.data?.map((a) => (
              <option key={a.id} value={a.id}>
                {a.code} {a.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="wide">
        {t("vouchers.description")}
        <input value={description} maxLength={500} onChange={(e) => setDescription(e.target.value)} />
      </label>

      <div className="wide table-wrap">
        <table aria-label={t("vouchers.lines")} className="fit-inputs">
          <thead>
            <tr>
              <th>{t("vouchers.invoiceNo")}</th>
              <th>{t("vouchers.invoiceDate")}</th>
              <th>{t("vouchers.lineDescription")}</th>
              <th className="num">{t("vouchers.amount")}</th>
              <th>{t("vouchers.taxCode")}</th>
              <th className="num">{t("vouchers.tax")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lines.map((line, index) => (
              <tr key={index}>
                {line.supplier_invoice ? (
                  <>
                    <td>{line.invoice_no}</td>
                    <td>{line.invoice_date ?? ""}</td>
                    <td>
                      {line.description} <span className="muted">· {t("vouchers.paysMatchedInvoice")}</span>
                    </td>
                  </>
                ) : line.advance_order ? (
                  <>
                    <td colSpan={2}>
                      <strong>{t("vouchers.advanceLine")}</strong>
                    </td>
                    <td>
                      <input
                        aria-label={t("vouchers.advanceReasonOf", { n: String(index + 1) })}
                        placeholder={t("vouchers.advanceReasonHint")}
                        value={line.description}
                        onChange={(e) => setLine(index, { description: e.target.value })}
                      />
                    </td>
                  </>
                ) : (
                  <>
                    <td>
                      <input
                        aria-label={t("vouchers.invoiceNoOf", { n: String(index + 1) })}
                        value={line.invoice_no}
                        maxLength={50}
                        onChange={(e) => setLine(index, { invoice_no: e.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        type="date"
                        aria-label={t("vouchers.invoiceDateOf", { n: String(index + 1) })}
                        value={line.invoice_date ?? ""}
                        onChange={(e) => setLine(index, { invoice_date: e.target.value || null })}
                      />
                    </td>
                    <td>
                      <input
                        aria-label={t("vouchers.descriptionOf", { n: String(index + 1) })}
                        value={line.description}
                        onChange={(e) => setLine(index, { description: e.target.value })}
                      />
                    </td>
                  </>
                )}
                <td>
                  <input
                    inputMode="decimal"
                    className="num"
                    required
                    aria-label={t("vouchers.amountOf", { n: String(index + 1) })}
                    value={line.amount}
                    onChange={(e) => setLine(index, { amount: e.target.value })}
                  />
                </td>
                <td>
                  {line.supplier_invoice || line.advance_order ? (
                    <span className="muted">—</span>
                  ) : (
                  <select
                    aria-label={t("vouchers.taxCodeOf", { n: String(index + 1) })}
                    value={line.tax_code ?? ""}
                    onChange={(e) => setLine(index, { tax_code: e.target.value || null })}
                  >
                    <option value="">{t("vouchers.enterTax")}</option>
                    {purchaseCodes.map((c) => (
                      <option key={c.code} value={c.code}>
                        {c.code}
                      </option>
                    ))}
                  </select>
                  )}
                </td>
                <td>
                  {line.supplier_invoice || line.advance_order ? (
                    <span className="muted">{line.advance_order ? "—" : t("vouchers.taxOnInvoice")}</span>
                  ) : line.tax_code ? (
                    <span className="muted">{t("vouchers.taxOnSave")}</span>
                  ) : (
                    <input
                      inputMode="decimal"
                      className="num"
                      aria-label={t("vouchers.taxOf", { n: String(index + 1) })}
                      value={line.tax_amount}
                      onChange={(e) => setLine(index, { tax_amount: e.target.value })}
                    />
                  )}
                </td>
                <td>
                  {lines.length > 1 && (
                    <button
                      type="button"
                      className="small secondary"
                      onClick={() => setLines((now) => now.filter((_, i) => i !== index))}
                    >
                      {t("vouchers.removeLine")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {payable.data && payable.data.some((i) => !onVoucher.has(i.id)) && (
        <div className="wide notice" role="region" aria-label={t("vouchers.matchedInvoices")}>
          <strong>{t("vouchers.matchedInvoices")}</strong>
          <ul className="changes">
            {payable.data
              .filter((i) => !onVoucher.has(i.id))
              .map((i) => (
                <li key={i.id}>
                  {t("vouchers.matchedInvoice", { no: i.invoice_no, due: i.due_date, unpaid: formatDecimal(i.unpaid) })}{" "}
                  <button type="button" className="small" onClick={() => payInvoice(i)}>
                    {t("vouchers.payInvoice", { no: i.invoice_no })}
                  </button>
                </li>
              ))}
          </ul>
        </div>
      )}
      {payee && !revise && (
        <div className="wide">
          <button type="button" className="secondary small" onClick={() => setShowAdvance((v) => !v)}>
            {t("vouchers.advanceOnPo")}
          </button>
          {showAdvance && advanceOrders.data && (
            <div className="notice" role="region" aria-label={t("vouchers.advanceOnPo")}>
              <p>{t("vouchers.advanceHelp")}</p>
              {advanceOrders.data.length === 0 && <p className="muted">{t("vouchers.noAdvanceOrders")}</p>}
              <ul className="changes">
                {advanceOrders.data
                  .filter((o) => Number(o.left) > 0)
                  .map((o) => (
                    <li key={o.id}>
                      {t("vouchers.advanceOrder", { po: o.label, total: formatDecimal(o.total_lkr), advanced: formatDecimal(o.advanced) })}{" "}
                      <button type="button" className="small" onClick={() => payAdvance(o)}>
                        {t("vouchers.advanceOn", { po: o.label })}
                      </button>
                    </li>
                  ))}
              </ul>
            </div>
          )}
        </div>
      )}
      <div className="wide row-actions">
        <button type="button" className="secondary" onClick={() => setLines((now) => [...now, emptyLine()])}>
          {t("vouchers.addLine")}
        </button>
        <span>
          {t("vouchers.totalSoFar")}: <strong>{formatDecimal(manualTotal)}</strong>
          {lines.some((l) => l.tax_code) && <span className="muted"> {t("vouchers.plusTaxCodes")}</span>}
        </span>
      </div>
      {voucher && (
        <p className="wide">
          {t("vouchers.savedTotal")}: <strong>LKR {formatDecimal(voucher.total_amount)}</strong>
        </p>
      )}
      <div className="wide">
        <button type="submit" disabled={save.isPending}>
          {revise ? t("voucherActions.saveChanges") : t("vouchers.saveDraft")}
        </button>
      </div>
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function ReadOnly({ voucher }: { voucher: VoucherDetail }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("vouchers.details")}>
      <p>
        {voucher.voucher_type.name}
        {voucher.payee && ` · ${voucher.payee.name}`}
        {voucher.transfer_to && ` · ${t("vouchers.transferTo")}: ${voucher.transfer_to.code}`}
      </p>
      {voucher.description && <p>{voucher.description}</p>}
      <div className="table-wrap">
        <table aria-label={t("vouchers.lines")}>
          <thead>
            <tr>
              <th>{t("vouchers.invoiceNo")}</th>
              <th>{t("vouchers.invoiceDate")}</th>
              <th>{t("vouchers.lineDescription")}</th>
              <th className="num">{t("vouchers.amount")}</th>
              <th className="num">{t("vouchers.tax")}</th>
              <th className="num">{t("vouchers.total")}</th>
            </tr>
          </thead>
          <tbody>
            {voucher.lines.map((l) => (
              <tr key={l.line_no}>
                <td>{l.invoice_no}</td>
                <td>{l.invoice_date ?? ""}</td>
                <td>{l.description}</td>
                <td className="num">{formatDecimal(l.amount)}</td>
                <td className="num">{formatDecimal(l.tax_amount)}</td>
                <td className="num">{formatDecimal(l.total)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={5}>{t("vouchers.total")}</th>
              <th className="num">{formatDecimal(voucher.total_amount)}</th>
            </tr>
            {Number(voucher.wht_total ?? 0) > 0 && (
              <tr>
                <th colSpan={5}>
                  {t("vouchers.whtKept")} · {t("vouchers.payable")} LKR {formatDecimal(voucher.payable ?? "0")}
                </th>
                <th className="num">{formatDecimal(voucher.wht_total ?? "0")}</th>
              </tr>
            )}
          </tfoot>
        </table>
      </div>
      {voucher.lines
        .filter((l) => l.advance_order)
        .map((l) => (
          <p key={`a${l.line_no}`} className="notice">
            {t("vouchers.advanceException", { po: l.advance_order!.label, amount: formatDecimal(l.total), total: formatDecimal(l.advance_order!.total_lkr) })}{" "}
            <Link to={`/purchase-orders/${l.advance_order!.id}`}>{l.advance_order!.label}</Link>
          </p>
        ))}
      {voucher.lines
        .filter((l) => l.supplier_invoice)
        .map((l) => (
          <MatchedInvoice key={l.line_no} invoice={l.supplier_invoice!} />
        ))}
    </section>
  );
}


function Attachments({ voucher }: { voucher: VoucherDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [warnings, setWarnings] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const key = [...vouchersKey, "one", voucher.id];
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      let latest: VoucherDetail = voucher;
      const found: string[] = [];
      for (const file of files) {
        latest = await uploadVoucherFile(voucher.id, file);
        found.push(...(latest.upload_warnings ?? []));
      }
      return { latest, found };
    },
    onSuccess: ({ latest, found }) => {
      queryClient.setQueryData(key, latest);
      setWarnings(found);
    },
  });
  const remove = useMutation({
    mutationFn: (attachmentId: number) => removeVoucherFile(voucher.id, attachmentId),
    onSuccess: (latest) => queryClient.setQueryData(key, latest),
  });
  const pick = (list: FileList | null) => {
    if (list && list.length) upload.mutate(Array.from(list));
  };
  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    pick(event.dataTransfer.files);
  };

  return (
    <section className="panel" aria-label={t("vouchers.files")}>
      <h2>{t("vouchers.files")}</h2>
      {voucher.attachments.length === 0 && <p className="muted">{t("vouchers.noFiles")}</p>}
      <ul className="changes">
        {voucher.attachments.map((a) => (
          <li key={a.id}>
            <a href={voucherFileUrl(voucher.id, a.id)} target="_blank" rel="noreferrer">
              {a.file_name}
            </a>{" "}
            <span className="muted">({Math.ceil(a.size / 1024)} KB)</span>
            {voucher.can_edit && (
              <button type="button" className="small secondary" onClick={() => remove.mutate(a.id)}>
                {t("vouchers.removeFile")}
              </button>
            )}
          </li>
        ))}
      </ul>
      {voucher.can_edit && (
        <div
          className={`drop-zone ${dragging ? "dragging" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={drop}
        >
          <p>{t("vouchers.dropHere")}</p>
          <label>
            {t("vouchers.chooseFiles")}
            <input type="file" multiple accept={ACCEPT} onChange={(e) => pick(e.target.files)} />
          </label>
          <label>
            {t("vouchers.takePhoto")}
            <input type="file" accept="image/*" capture="environment" onChange={(e) => pick(e.target.files)} />
          </label>
          {upload.isPending && <p role="status">{t("vouchers.uploading")}</p>}
        </div>
      )}
      {warnings.map((w) => (
        <p key={w} className="notice" role="status">
          ⚠ {w}
        </p>
      ))}
      <ErrorLine error={upload.error ?? remove.error} />
    </section>
  );
}

function Submit({ voucher }: { voucher: VoucherDetail }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [comment, setComment] = useState("");
  const send = useMutation({
    mutationFn: () => submitVoucher(voucher.id, comment),
    onSuccess: (latest) => {
      queryClient.setQueryData([...vouchersKey, "one", voucher.id], latest);
      void queryClient.invalidateQueries({ queryKey: vouchersKey });
    },
  });
  return (
    <section className="panel" aria-label={t("vouchers.submit")}>
      <h2>{t("vouchers.submit")}</h2>
      <p className="muted">{t("vouchers.submitHelp")}</p>
      <label className="inline-form">
        {t("vouchers.comment")}
        <input value={comment} onChange={(e) => setComment(e.target.value)} />
      </label>
      <button type="button" disabled={send.isPending} onClick={() => send.mutate()}>
        {t("vouchers.submit")}
      </button>
      <ErrorLine error={send.error} />
    </section>
  );
}

function History({ voucher }: { voucher: VoucherDetail }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("vouchers.history")}>
      <h2>{t("vouchers.history")}</h2>
      <ul className="changes">
        {voucher.approvals.map((row, index) => (
          <li key={index}>
            L{row.level} · {t(`vouchers.actions.${row.action}`)} · {row.user} ·{" "}
            {formatDateTime(row.acted_at)}
            {row.reason && ` — ${row.reason}`}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The latest cancellation request: waiting, approved or rejected; the Director decides
 * here (spec 4.2, P1-06). */
function CancellationPanel({ voucher, request }: { voucher: VoucherDetail; request: Cancellation }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const decide = useMutation({
    mutationFn: (decision: "approve" | "reject") => decideCancellation(request.id, decision, reason),
    onSuccess: (latest) => {
      queryClient.setQueryData([...vouchersKey, "one", voucher.id], latest);
      void queryClient.invalidateQueries({ queryKey: vouchersKey });
    },
  });
  return (
    <section className="panel change-notice" aria-label={t("cancellations.panel")}>
      <h2>{t("cancellations.panel")}</h2>
      <p>
        {t(`cancellations.statuses.${request.status}`)} ·{" "}
        {t("cancellations.requestedBy", { name: request.requested_by, when: formatDateTime(request.requested_at) })}
        : {request.reason}
      </p>
      {request.decided_by && (
        <p className="muted">
          {t("cancellations.decidedBy", { name: request.decided_by, when: formatDateTime(request.decided_at ?? "") })}
          {request.decision_reason && `: ${request.decision_reason}`}
        </p>
      )}
      {request.can_decide && (
        <>
          <label className="wide">
            {t("cancellations.decisionReason")}
            <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div className="row-actions">
            <button type="button" className="danger" disabled={decide.isPending} onClick={() => decide.mutate("approve")}>
              {t("cancellations.approve")}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={decide.isPending || !reason.trim()}
              onClick={() => decide.mutate("reject")}
            >
              {t("cancellations.reject")}
            </button>
          </div>
        </>
      )}
      <ErrorLine error={decide.error} />
    </section>
  );
}

/** Payments made against the voucher, and what is left to pay (P1-07); cancelling a payment
 * with the Director's approval (P2-11). */
function Payments({ voucher }: { voucher: VoucherDetail }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("payments.ofVoucher")}>
      <h2>{t("payments.ofVoucher")}</h2>
      <div className="table-wrap">
        <table aria-label={t("payments.ofVoucher")}>
          <thead>
            <tr>
              <th>{t("payments.number")}</th>
              <th>{t("payments.date")}</th>
              <th>{t("payments.account")}</th>
              <th>{t("payments.method")}</th>
              <th>{t("payments.reference")}</th>
              <th className="num">{t("payments.amount")}</th>
            </tr>
          </thead>
          <tbody>
            {voucher.payments?.map((p) => (
              <tr key={p.id} className={p.cancelled ? "muted" : undefined}>
                <td className="mono">
                  {p.number}
                  {p.cancelled && <div>{t("payments.cancelled")}</div>}
                </td>
                <td>{p.payment_date}</td>
                <td>{p.account.code}</td>
                <td>{t(`payments.methods.${p.method}`)}</td>
                <td>
                  {p.reference}
                  {p.wht_certificate && (
                    <div>
                      <a href={whtCertificateUrl(p.id)} target="_blank" rel="noopener noreferrer">
                        {t("payments.whtCertificateNo", { number: p.wht_certificate, amount: formatDecimal(p.wht_amount ?? "0") })}
                      </a>
                    </div>
                  )}
                </td>
                <td className="num">
                  {p.cancelled ? <s>{formatDecimal(p.amount)}</s> : formatDecimal(p.amount)}
                  {p.currency && p.currency !== "LKR" && (
                    <div className="muted">
                      {p.currency} {formatDecimal(p.paid_amount ?? "")} @ {p.exchange_rate}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={5}>{t("payments.remaining")}</th>
              <th className="num">{formatDecimal(voucher.remaining ?? "")}</th>
            </tr>
          </tfoot>
        </table>
      </div>
      {voucher.payments?.map((p) => (
        <PaymentCancel key={p.id} voucher={voucher} payment={p} />
      ))}
    </section>
  );
}

function PaymentCancel({ voucher, payment }: { voucher: VoucherDetail; payment: NonNullable<VoucherDetail["payments"]>[number] }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const act = useMutation({
    mutationFn: (call: () => Promise<unknown>) => call(),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: [...vouchersKey, "one", String(voucher.id)] }),
  });
  const c = payment.cancellation;
  const error = act.error;
  return (
    <div aria-label={t("payments.cancelOf", { number: payment.number })} role="group">
      {c?.status === "pending" && <p>{t("payments.cancelPending", { name: c.requested_by, reason: c.reason })}</p>}
      {c?.status === "approved" && (
        <p className="muted">{t("payments.cancelDone", { name: c.decided_by ?? "", reason: c.reason, entry: c.reversal_entry ?? "" })}</p>
      )}
      {c?.status === "rejected" && !payment.can_cancel && <p className="muted">{t("payments.cancelRejected", { name: c.decided_by ?? "" })}</p>}
      {c?.can_decide && (
        <div className="inline-form">
          <label>
            {t("payments.decisionNote")}
            <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
          </label>
          <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => approvePaymentCancellation(c.id, note))}>
            {t("payments.approveCancel")}
          </button>
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate(() => rejectPaymentCancellation(c.id, note))}>
            {t("payments.rejectCancel")}
          </button>
        </div>
      )}
      {payment.can_cancel && (
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            act.mutate(() => cancelPayment(payment.id, reason));
          }}
        >
          <label>
            {t("payments.cancelReason")} ({payment.number})
            <input value={reason} required maxLength={2000} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="submit" className="secondary" disabled={act.isPending}>
            {t("payments.askCancel")}
          </button>
        </form>
      )}
      {error ? (
        <p className="form-error" role="alert">
          {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
        </p>
      ) : null}
    </div>
  );
}
