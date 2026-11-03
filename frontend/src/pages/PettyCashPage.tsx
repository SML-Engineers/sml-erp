import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { ApiError } from "../api/client";
import { listPayees } from "../api/payees";
import {
  listFloats,
  listPettyExpenses,
  pettyKey,
  pettySlipUrl,
  recordPettyExpense,
  removePettyExpense,
  replenishFloat,
  type PettyFloat,
} from "../api/pettyCash";
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

/** Petty cash (P2-17): the custodian records small expenses with their slips; the Clerk tops
 * the float up with a Petty Cash voucher that goes through the three approvals. */
export default function PettyCashPage() {
  const { t } = useTranslation();
  const floats = useQuery({ queryKey: [...pettyKey, "floats"], queryFn: listFloats });
  const [chosen, setChosen] = useState<number | null>(null);
  const current = floats.data?.find((f) => f.id === chosen) ?? (floats.data?.length === 1 ? floats.data[0] : undefined);
  return (
    <main className="page">
      <h1>{t("petty.title")}</h1>
      <p className="muted">{t("petty.help")}</p>
      {floats.data?.length === 0 && <p className="muted">{t("petty.none")}</p>}
      {floats.data && floats.data.length > 1 && (
        <div className="toolbar">
          <label>
            {t("petty.float")}
            <select value={chosen ?? ""} onChange={(e) => setChosen(Number(e.target.value) || null)}>
              <option value="">—</option>
              {floats.data.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.code} {f.name}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      <ErrorLine error={floats.error} />
      {current && <Float key={current.id} box={current} />}
    </main>
  );
}

function Float({ box }: { box: PettyFloat }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const found = useQuery({ queryKey: [...pettyKey, "expenses", box.id], queryFn: () => listPettyExpenses(box.id) });
  const remove = useMutation({
    mutationFn: (id: number) => removePettyExpense(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: pettyKey }),
  });
  const figures = found.data?.float ?? box;
  return (
    <>
      <section className="panel" aria-label={t("petty.figures")}>
        <h2>
          {box.code} {box.name}
        </h2>
        <dl className="details">
          <dt>{t("petty.custodian")}</dt>
          <dd>{box.custodian ?? "—"}</dd>
          <dt>{t("petty.floatAmount")}</dt>
          <dd>{formatDecimal(figures.float)}</dd>
          <dt>{t("petty.spent")}</dt>
          <dd>{formatDecimal(figures.spent)}</dd>
          <dt>{t("petty.cashInHand")}</dt>
          <dd>
            <strong>{formatDecimal(figures.cash_in_hand)}</strong>
          </dd>
        </dl>
      </section>
      {box.can_record && <RecordForm box={box} />}
      <Replenish box={box} waiting={figures.not_on_voucher} />
      {found.data && found.data.expenses.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("petty.expenses")}>
            <thead>
              <tr>
                <th>{t("petty.number")}</th>
                <th>{t("petty.date")}</th>
                <th>{t("petty.paidTo")}</th>
                <th>{t("petty.description")}</th>
                <th className="num">{t("petty.amount")}</th>
                <th>{t("petty.status")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {found.data.expenses.map((e) => (
                <tr key={e.id}>
                  <td className="mono">{e.number}</td>
                  <td>{e.expense_date}</td>
                  <td>{e.paid_to}</td>
                  <td>
                    {e.description}
                    {e.ledger && <div className="muted">{e.ledger.number} {e.ledger.name}</div>}
                  </td>
                  <td className="num">{formatDecimal(e.amount)}</td>
                  <td>
                    {t(`petty.statuses.${e.status}`)}
                    {e.voucher && (
                      <div>
                        <Link to={`/vouchers/${e.voucher.id}`}>{e.voucher.number}</Link>
                      </div>
                    )}
                  </td>
                  <td>
                    <a href={pettySlipUrl(e.id)} target="_blank" rel="noopener noreferrer">
                      {t("petty.slip")}
                    </a>
                    {e.status === "open" && !e.voucher && box.can_record && (
                      <>
                        {" "}
                        <button type="button" className="small secondary" disabled={remove.isPending} onClick={() => remove.mutate(e.id)}>
                          {t("petty.remove")}
                        </button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ErrorLine error={found.error ?? remove.error} />
    </>
  );
}

function RecordForm({ box }: { box: PettyFloat }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [date, setDate] = useState(today());
  const [paidTo, setPaidTo] = useState("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [formKey, setFormKey] = useState(0);
  const save = useMutation({
    mutationFn: () => recordPettyExpense(box.id, { expense_date: date, paid_to: paidTo, description, amount, ledger: "", slip: file! }),
    onSuccess: () => {
      setPaidTo("");
      setDescription("");
      setAmount("");
      setFile(null);
      setFormKey((k) => k + 1);
      void queryClient.invalidateQueries({ queryKey: pettyKey });
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  return (
    <form key={formKey} className="panel form-grid" aria-label={t("petty.record")} onSubmit={submit}>
      <h2 className="wide">{t("petty.record")}</h2>
      <label>
        {t("petty.date")}
        <input type="date" value={date} required onChange={(e) => setDate(e.target.value)} />
      </label>
      <label>
        {t("petty.paidTo")}
        <input value={paidTo} required maxLength={150} onChange={(e) => setPaidTo(e.target.value)} />
      </label>
      <label className="wide">
        {t("petty.description")}
        <input value={description} required maxLength={500} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <label>
        {t("petty.amount")}
        <input inputMode="decimal" value={amount} required onChange={(e) => setAmount(e.target.value)} />
      </label>
      <label>
        {t("petty.slipFile")}
        <input type="file" accept="image/*,application/pdf" capture="environment" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <div className="wide row-actions">
        <button type="submit" disabled={save.isPending || !file}>
          {t("petty.save")}
        </button>
      </div>
      <ErrorLine error={save.error} />
    </form>
  );
}

function Replenish({ box, waiting }: { box: PettyFloat; waiting: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const payees = useQuery({ queryKey: ["payees", "", false], queryFn: () => listPayees("", false) });
  const [payee, setPayee] = useState("");
  const make = useMutation({
    mutationFn: () => replenishFloat(box.id, Number(payee)),
    onSuccess: (data) => navigate(`/vouchers/${data.voucher.id}`),
  });
  if (!Number(waiting) || payees.isError) return null;
  return (
    <section className="panel" aria-label={t("petty.topUp")}>
      <h2>{t("petty.topUp")}</h2>
      <p className="muted">{t("petty.topUpHelp", { amount: formatDecimal(waiting) })}</p>
      <div className="inline-form">
        <label>
          {t("petty.payee")}
          <select value={payee} onChange={(e) => setPayee(e.target.value)}>
            <option value="">—</option>
            {(payees.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.code} {p.name}
              </option>
            ))}
          </select>
        </label>
        <button type="button" disabled={make.isPending || !payee} onClick={() => make.mutate()}>
          {t("petty.makeVoucher")}
        </button>
      </div>
      <ErrorLine error={make.error} />
    </section>
  );
}
