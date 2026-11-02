import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../api/client";
import {
  confirmTaxRate,
  getTaxRates,
  proposeTaxRate,
  rejectTaxRate,
  taxRatesKey,
  withdrawTaxRate,
  type RateRow,
  type TaxRates,
} from "../../api/taxRates";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

const localToday = () => new Date().toLocaleDateString("en-CA");

/** Settings → Tax rates (P16-20): VAT and the SSCL rates, entered by the Admin or the
 * Accountant and confirmed by the Director before they apply. */
export default function TaxRatesPage() {
  const { t } = useTranslation();
  const page = useQuery({ queryKey: taxRatesKey, queryFn: getTaxRates });
  const data = page.data;

  return (
    <main className="page">
      <h1>{t("taxRates.title")}</h1>
      <p className="muted">{t("taxRates.help")}</p>
      {data && (
        <>
          <section className="panel">
            <h2>{t("taxRates.inForce")}</h2>
            <div className="table-wrap">
              <table aria-label={t("taxRates.inForce")}>
                <thead>
                  <tr>
                    <th>{t("taxRates.tax")}</th>
                    <th>{t("taxRates.printedAs")}</th>
                    <th className="num">{t("taxRates.rate")}</th>
                    <th>{t("taxRates.since")}</th>
                    <th>{t("taxRates.coming")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.taxes.map((tax) => (
                    <tr key={tax.id}>
                      <td>
                        <span className="mono">{tax.code}</span> {tax.name}
                      </td>
                      <td>{tax.printed_as}</td>
                      <td className="num">{tax.current ? `${tax.current.rate}%` : t("taxRates.notSet")}</td>
                      <td>{tax.current?.effective_from ?? "—"}</td>
                      <td>{tax.coming.map((r) => `${r.rate}% ${t("taxRates.fromDate", { date: r.effective_from })}`).join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          {data.taxes.some((tax) => tax.pending.length > 0) && (
            <section className="panel">
              <h2>{t("taxRates.waiting")}</h2>
              {data.taxes.flatMap((tax) => tax.pending.map((r) => <Pending key={r.id} tax={tax} rate={r} canConfirm={data.can_confirm} />))}
            </section>
          )}
          {data.can_propose && <ProposeForm taxes={data.taxes} />}
        </>
      )}
      <ErrorLine error={page.error} />
    </main>
  );
}

function Pending({ tax, rate, canConfirm }: { tax: TaxRates; rate: RateRow; canConfirm: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const done = (latest: unknown) => queryClient.setQueryData(taxRatesKey, latest);
  const confirm = useMutation({ mutationFn: () => confirmTaxRate(rate.id), onSuccess: done });
  const reject = useMutation({ mutationFn: () => rejectTaxRate(rate.id, note), onSuccess: done });
  const withdraw = useMutation({ mutationFn: () => withdrawTaxRate(rate.id), onSuccess: done });
  const label = t("taxRates.changeFor", { tax: tax.code });
  return (
    <div className="pending-change" role="group" aria-label={label}>
      <p>
        <strong>{label}</strong> {t("taxRates.changeText", { rate: rate.rate, from: rate.effective_from, by: rate.created_by })}
      </p>
      <p className="muted">
        {t("access.reason")}: {rate.reason}
      </p>
      <div className="row-actions">
        {canConfirm && !rate.created_by_me && (
          <>
            <button type="button" onClick={() => confirm.mutate()}>
              {t("access.confirm")}
            </button>
            <input aria-label={t("taxRates.rejectReason")} placeholder={t("taxRates.rejectReason")} value={note} onChange={(e) => setNote(e.target.value)} />
            <button type="button" className="danger" onClick={() => reject.mutate()}>
              {t("limits.reject")}
            </button>
          </>
        )}
        {rate.created_by_me && (
          <button type="button" className="secondary" onClick={() => withdraw.mutate()}>
            {t("limits.withdraw")}
          </button>
        )}
      </div>
      <ErrorLine error={confirm.error ?? reject.error ?? withdraw.error} />
    </div>
  );
}

function ProposeForm({ taxes }: { taxes: TaxRates[] }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [component, setComponent] = useState(String(taxes[0]?.id ?? ""));
  const [from, setFrom] = useState(localToday());
  const [rate, setRate] = useState("");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => proposeTaxRate({ component: Number(component), effective_from: from, rate, reason }),
    onSuccess: (latest) => {
      queryClient.setQueryData(taxRatesKey, latest);
      setRate("");
      setReason("");
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <section className="panel" aria-label={t("taxRates.propose")}>
      <h2>{t("taxRates.propose")}</h2>
      <form className="inline-form" onSubmit={submit}>
        <label>
          {t("taxRates.tax")}
          <select value={component} onChange={(e) => setComponent(e.target.value)}>
            {taxes.map((tax) => (
              <option key={tax.id} value={tax.id}>
                {tax.code} {tax.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("limits.from")}
          <input type="date" value={from} min={localToday()} required onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          {t("taxRates.newRate")}
          <input inputMode="decimal" value={rate} required onChange={(e) => setRate(e.target.value)} />
        </label>
        <label>
          {t("access.reason")}
          <input value={reason} required placeholder={t("taxRates.reasonHint")} onChange={(e) => setReason(e.target.value)} />
        </label>
        <button type="submit" disabled={save.isPending}>
          {t("limits.send")}
        </button>
      </form>
      <p className="muted">{t("taxRates.proposeHelp")}</p>
      <ErrorLine error={save.error} />
    </section>
  );
}
