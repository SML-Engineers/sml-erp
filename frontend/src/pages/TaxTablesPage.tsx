import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { addTaxTable, listTaxTables, taxTablesKey, type TaxBand } from "../api/payroll";
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

const emptyBand = (): TaxBand => ({ up_to: "", rate: "", constant: "0" });

/** APIT tables and EPF/ETF rates, kept by the Accountant (P2B-06). */
export default function TaxTablesPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: taxTablesKey, queryFn: listTaxTables });
  const [kind, setKind] = useState("secondary");
  const [from, setFrom] = useState("");
  const [reason, setReason] = useState("");
  const [bands, setBands] = useState<TaxBand[]>([emptyBand(), emptyBand()]);
  const add = useMutation({
    mutationFn: () =>
      addTaxTable({
        kind,
        effective_from: from,
        reason,
        bands: bands.map((b, i) => (i === bands.length - 1 ? { ...b, up_to: null } : b)),
      }),
    onSuccess: () => {
      setBands([emptyBand(), emptyBand()]);
      setReason("");
      void queryClient.invalidateQueries({ queryKey: taxTablesKey });
    },
  });
  const setBand = (i: number, change: Partial<TaxBand>) =>
    setBands((all) => all.map((b, n) => (n === i ? { ...b, ...change } : b)));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  const d = list.data;
  return (
    <div className="page">
      <h1>{t("taxTables.title")}</h1>
      <p className="muted">{t("taxTables.help")}</p>
      <ErrorLine error={list.error} />
      {d?.tables.map((x) => (
        <section className="panel" key={x.id} aria-label={`${x.kind_label} ${x.effective_from}`}>
          <h2>
            {x.kind_label} <span className="muted">{t("taxTables.from", { date: x.effective_from })}</span>
          </h2>
          <p className="muted">{x.reason}</p>
          <table>
            <thead>
              <tr>
                <th className="num">{t("taxTables.upTo")}</th>
                <th className="num">{t("taxTables.rate")}</th>
                <th className="num">{t("taxTables.constant")}</th>
              </tr>
            </thead>
            <tbody>
              {x.bands.map((b, i) => (
                <tr key={i}>
                  <td className="num">{b.up_to === null ? t("taxTables.above") : formatDecimal(b.up_to)}</td>
                  <td className="num">{b.rate}%</td>
                  <td className="num">{formatDecimal(b.constant)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
      {d && (
        <section className="panel" aria-label={t("taxTables.epf")}>
          <h2>{t("taxTables.epf")}</h2>
          <ul>
            {d.statutory.map((s) => (
              <li key={s.effective_from}>
                {t("taxTables.epfLine", { date: s.effective_from, ee: s.epf_employee, er: s.epf_employer, etf: s.etf })}
              </li>
            ))}
          </ul>
        </section>
      )}
      <form className="panel form-grid" aria-label={t("taxTables.add")} onSubmit={submit}>
        <h2 className="wide">{t("taxTables.add")}</h2>
        <label>
          {t("taxTables.kind")}
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="primary">{t("taxTables.primary")}</option>
            <option value="secondary">{t("taxTables.secondary")}</option>
          </select>
        </label>
        <label>
          {t("taxTables.appliesFrom")}
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="wide">
          {t("taxTables.source")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        {bands.map((b, i) => (
          <div className="wide form-grid" key={i}>
            <label>
              {t("taxTables.bandUpTo", { n: i + 1 })}
              <input
                inputMode="decimal"
                disabled={i === bands.length - 1}
                placeholder={i === bands.length - 1 ? t("taxTables.above") : ""}
                value={i === bands.length - 1 ? "" : (b.up_to ?? "")}
                onChange={(e) => setBand(i, { up_to: e.target.value })}
              />
            </label>
            <label>
              {t("taxTables.bandRate", { n: i + 1 })}
              <input inputMode="decimal" value={b.rate} onChange={(e) => setBand(i, { rate: e.target.value })} />
            </label>
            <label>
              {t("taxTables.bandConstant", { n: i + 1 })}
              <input inputMode="decimal" value={b.constant} onChange={(e) => setBand(i, { constant: e.target.value })} />
            </label>
          </div>
        ))}
        <div className="wide row-actions">
          <button type="button" className="secondary" onClick={() => setBands((all) => [...all, emptyBand()])}>
            {t("taxTables.addBand")}
          </button>
          <button type="submit" disabled={add.isPending}>
            {t("taxTables.save")}
          </button>
        </div>
        <p className="muted wide">{t("taxTables.addHelp")}</p>
        <div className="wide">
          <ErrorLine error={add.error} />
        </div>
      </form>
    </div>
  );
}
