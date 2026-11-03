import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router";

import {
  chequesKey,
  clearIssued,
  clearReceived,
  listDeposits,
  listIssued,
  listReceived,
  makeDeposit,
  returnReceived,
  type IssuedCheque,
  type ReceivedCheque,
} from "../api/cheques";
import { ApiError } from "../api/client";
import { listPayAccounts } from "../api/payments";
import { formatDecimal, sumDecimal } from "../lib/decimal";

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

const RECEIVED = ["in_hand", "deposited", "cleared", "returned", "post_dated", "awaiting_approval"] as const;
const ISSUED = ["issued", "cleared", "spoiled"] as const;

/** Cheque register (P2-14): customers' cheques with deposit slips, cleared and returned
 * cheques; our own cheques, issued, cleared or spoiled. */
export default function ChequesPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "issued" ? "issued" : "received";
  return (
    <main className="page">
      <h1>{t("cheques.title")}</h1>
      <p className="muted">{t("cheques.help")}</p>
      <div className="toolbar" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "received"}
          className={tab === "received" ? undefined : "secondary"}
          onClick={() => setParams({}, { replace: true })}
        >
          {t("cheques.received")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "issued"}
          className={tab === "issued" ? undefined : "secondary"}
          onClick={() => setParams({ tab: "issued" }, { replace: true })}
        >
          {t("cheques.issued")}
        </button>
      </div>
      {tab === "received" ? <Received /> : <Issued />}
    </main>
  );
}

function Received() {
  const { t } = useTranslation();
  const [status, setStatus] = useState("");
  const rows = useQuery({ queryKey: [...chequesKey, "received", status], queryFn: () => listReceived(status) });
  return (
    <>
      <Deposit />
      <div className="toolbar">
        <label>
          {t("cheques.status")}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("cheques.all")}</option>
            {RECEIVED.map((s) => (
              <option key={s} value={s}>
                {t(`cheques.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {rows.data?.length === 0 && <p className="muted">{t("cheques.none")}</p>}
      {rows.data && rows.data.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("cheques.received")}>
            <thead>
              <tr>
                <th>{t("cheques.receipt")}</th>
                <th>{t("cheques.customer")}</th>
                <th>{t("cheques.cheque")}</th>
                <th>{t("cheques.chequeDate")}</th>
                <th className="num">{t("cheques.amount")}</th>
                <th>{t("cheques.status")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.data.map((r) => (
                <ReceivedRow key={r.id} row={r} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ErrorLine error={rows.error} />
      <Deposits />
    </>
  );
}

function ReceivedRow({ row }: { row: ReceivedCheque }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [on, setOn] = useState(today());
  const [reason, setReason] = useState("");
  const done = () => void queryClient.invalidateQueries({ queryKey: chequesKey });
  const clear = useMutation({ mutationFn: () => clearReceived(row.id, on), onSuccess: done });
  const back = useMutation({ mutationFn: () => returnReceived(row.id, on, reason), onSuccess: done });
  const open = row.status === "in_hand" || row.status === "deposited";
  return (
    <tr>
      <td>
        <Link className="mono" to={`/receipts/${row.id}`}>
          {row.number}
        </Link>
      </td>
      <td>{row.customer.name}</td>
      <td>
        {row.reference} {row.cheque_bank && <span className="muted">{row.cheque_bank}</span>}
      </td>
      <td>{row.cheque_date ?? ""}</td>
      <td className="num">{formatDecimal(row.amount_lkr)}</td>
      <td>
        {t(`cheques.statuses.${row.status}`)}
        {row.deposit && <div className="muted">{row.deposit.number}</div>}
        {row.cleared_on && <div className="muted">{row.cleared_on}</div>}
        {row.returned_on && (
          <div className="muted">
            {row.returned_on}: {row.return_reason}
          </div>
        )}
      </td>
      <td>
        {open && (
          <div className="inline-form">
            <input type="date" aria-label={t("cheques.date")} value={on} onChange={(e) => setOn(e.target.value)} />
            {row.status === "deposited" && (
              <button type="button" className="small" disabled={clear.isPending} onClick={() => clear.mutate()}>
                {t("cheques.clear")}
              </button>
            )}
            <input aria-label={t("cheques.reason")} placeholder={t("cheques.reason")} value={reason} onChange={(e) => setReason(e.target.value)} />
            <button type="button" className="small secondary" disabled={back.isPending} onClick={() => back.mutate()}>
              {t("cheques.return")}
            </button>
          </div>
        )}
        <ErrorLine error={clear.error ?? back.error} />
      </td>
    </tr>
  );
}

function Deposit() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const waiting = useQuery({ queryKey: [...chequesKey, "received", "in_hand"], queryFn: () => listReceived("in_hand") });
  const accounts = useQuery({ queryKey: ["payments", "accounts"], queryFn: listPayAccounts });
  const banks = (accounts.data ?? []).filter((a) => (a.kind === "current" || a.kind === "savings") && a.currency === "LKR");
  const [account, setAccount] = useState("");
  const [date, setDate] = useState(today());
  const [slipNo, setSlipNo] = useState("");
  const [chosen, setChosen] = useState<number[]>([]);
  const save = useMutation({
    mutationFn: () => makeDeposit({ account: Number(account), deposit_date: date, slip_no: slipNo, receipts: chosen }),
    onSuccess: () => {
      setChosen([]);
      setSlipNo("");
      void queryClient.invalidateQueries({ queryKey: chequesKey });
    },
  });
  const rows = waiting.data ?? [];
  const total = sumDecimal(rows.filter((r) => chosen.includes(r.id)).map((r) => r.amount_lkr));
  return (
    <section className="panel" aria-label={t("cheques.deposit")}>
      <h2>{t("cheques.deposit")}</h2>
      <p className="muted">{t("cheques.depositHelp")}</p>
      {rows.length === 0 ? (
        <p className="muted">{t("cheques.nothingInHand")}</p>
      ) : (
        <>
          <ul className="plain-list">
            {rows.map((r) => (
              <li key={r.id}>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={chosen.includes(r.id)}
                    onChange={(e) => setChosen((now) => (e.target.checked ? [...now, r.id] : now.filter((x) => x !== r.id)))}
                  />
                  {r.number} · {r.customer.name} · {r.reference} · LKR {formatDecimal(r.amount_lkr)}
                </label>
              </li>
            ))}
          </ul>
          <div className="inline-form">
            <label>
              {t("cheques.depositAccount")}
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
              {t("cheques.depositDate")}
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </label>
            <label>
              {t("cheques.slipNo")}
              <input value={slipNo} maxLength={50} onChange={(e) => setSlipNo(e.target.value)} />
            </label>
            <span>{t("cheques.depositTotal", { amount: formatDecimal(total) })}</span>
            <button type="button" disabled={save.isPending || !account || chosen.length === 0} onClick={() => save.mutate()}>
              {t("cheques.depositButton")}
            </button>
          </div>
        </>
      )}
      <ErrorLine error={save.error} />
    </section>
  );
}

function Deposits() {
  const { t } = useTranslation();
  const slips = useQuery({ queryKey: [...chequesKey, "deposits"], queryFn: listDeposits });
  if (!slips.data || slips.data.length === 0) return null;
  return (
    <section className="panel" aria-label={t("cheques.deposits")}>
      <h2>{t("cheques.deposits")}</h2>
      <div className="table-wrap">
        <table aria-label={t("cheques.deposits")}>
          <thead>
            <tr>
              <th>{t("cheques.deposits")}</th>
              <th>{t("cheques.date")}</th>
              <th>{t("cheques.account")}</th>
              <th>{t("cheques.slipNo")}</th>
              <th className="num">{t("cheques.amount")}</th>
              <th>{t("cheques.journal")}</th>
            </tr>
          </thead>
          <tbody>
            {slips.data.map((d) => (
              <tr key={d.id}>
                <td className="mono">{d.number}</td>
                <td>{d.deposit_date}</td>
                <td>{d.account.code}</td>
                <td>{d.slip_no}</td>
                <td className="num">{formatDecimal(d.total)}</td>
                <td>{d.journal_entry}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Issued() {
  const { t } = useTranslation();
  const [status, setStatus] = useState("");
  const rows = useQuery({ queryKey: [...chequesKey, "issued", status], queryFn: () => listIssued(status) });
  return (
    <>
      <div className="toolbar">
        <label>
          {t("cheques.status")}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("cheques.all")}</option>
            {ISSUED.map((s) => (
              <option key={s} value={s}>
                {t(`cheques.statuses.${s}`)}
              </option>
            ))}
          </select>
        </label>
      </div>
      {rows.data?.length === 0 && <p className="muted">{t("cheques.none")}</p>}
      {rows.data && rows.data.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("cheques.issued")}>
            <thead>
              <tr>
                <th>{t("cheques.cheque")}</th>
                <th>{t("cheques.account")}</th>
                <th>{t("cheques.payee")}</th>
                <th>{t("cheques.payment")}</th>
                <th className="num">{t("cheques.amount")}</th>
                <th>{t("cheques.status")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.data.map((r) => (
                <IssuedRow key={r.id} row={r} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ErrorLine error={rows.error} />
    </>
  );
}

function IssuedRow({ row }: { row: IssuedCheque }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [on, setOn] = useState(today());
  const clear = useMutation({
    mutationFn: () => clearIssued(row.id, on),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: chequesKey }),
  });
  return (
    <tr>
      <td className="mono">{row.number}</td>
      <td>{row.account.code}</td>
      <td>{row.payment?.payee ?? row.reason}</td>
      <td>
        {row.payment && (
          <Link to={`/vouchers/${row.payment.voucher.id}`}>
            {row.payment.number} · {row.payment.voucher.number}
          </Link>
        )}
      </td>
      <td className="num">{row.payment ? formatDecimal(row.payment.amount) : ""}</td>
      <td>
        {t(`cheques.statuses.${row.status}`)}
        {row.cleared_on && <div className="muted">{row.cleared_on}</div>}
      </td>
      <td>
        {row.status === "issued" && row.payment && (
          <div className="inline-form">
            <input type="date" aria-label={t("cheques.date")} value={on} onChange={(e) => setOn(e.target.value)} />
            <button type="button" className="small" disabled={clear.isPending} onClick={() => clear.mutate()}>
              {t("cheques.clear")}
            </button>
          </div>
        )}
        <ErrorLine error={clear.error} />
      </td>
    </tr>
  );
}
