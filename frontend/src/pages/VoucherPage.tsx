import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type DragEvent, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { listDivisions } from "../api/admin";
import type { CurrentUser } from "../api/auth";
import { ApiError } from "../api/client";
import { listPayees } from "../api/payees";
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
import VoucherActions from "../components/VoucherActions";
import { formatDecimal, sumDecimal } from "../lib/decimal";

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
  const sentBack = data?.approvals.at(-1)?.action === "send_down" ? data.approvals.at(-1) : undefined;
  const returned =
    data?.status === "returned" ? [...data.approvals].reverse().find((a) => a.action === "return") : undefined;
  return (
    <main className="page">
      <p>
        <Link to="/vouchers">{t("vouchers.backToList")}</Link>
      </p>
      <div className="row-actions">
        <h1>{data ? `${t("vouchers.voucher")} ${data.number}` : t("vouchers.new")}</h1>
        {data && <VoucherActions voucher={data} onDeleted={() => navigate("/vouchers")} />}
      </div>
      {data?.deleted && (
        <p className="notice change-notice" role="status">
          {t("voucherActions.deletedBy", {
            name: data.deleted.by,
            when: new Date(data.deleted.at).toLocaleString(),
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
      {sentBack && (
        <p className="notice change-notice" role="status">
          {t("voucherActions.sentBack", { name: sentBack.user })} {sentBack.reason}
        </p>
      )}
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
      {type?.needs_payee && (
        <div className="wide">
          <label>
            {t("vouchers.findPayee")}
            <input value={payeeSearch} onChange={(e) => setPayeeSearch(e.target.value)} />
          </label>
          {candidates.length > 0 && (
            <ul className="changes" aria-label={t("vouchers.payeeResults")}>
              {candidates.slice(0, 10).map((p) => (
                <li key={p.id}>
                  <button type="button" className="link-button" onClick={() => setPayee({ id: p.id, name: p.name })}>
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
        <table aria-label={t("vouchers.lines")}>
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
                </td>
                <td>
                  {line.tax_code ? (
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
          </tfoot>
        </table>
      </div>
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
            {new Date(row.acted_at).toLocaleString()}
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
        {t("cancellations.requestedBy", { name: request.requested_by, when: new Date(request.requested_at).toLocaleString() })}
        : {request.reason}
      </p>
      {request.decided_by && (
        <p className="muted">
          {t("cancellations.decidedBy", { name: request.decided_by, when: new Date(request.decided_at ?? "").toLocaleString() })}
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

/** Payments made against the voucher, and what is left to pay (P1-07). */
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
              <tr key={p.id}>
                <td className="mono">{p.number}</td>
                <td>{p.payment_date}</td>
                <td>{p.account.code}</td>
                <td>{t(`payments.methods.${p.method}`)}</td>
                <td>{p.reference}</td>
                <td className="num">{formatDecimal(p.amount)}</td>
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
    </section>
  );
}
