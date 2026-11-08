import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  acceptPayroll,
  addCostRate,
  costRatesKey,
  getCostRates,
  removeCostRate,
  type CostRates,
  type RateBrief,
  type RateKind,
  type RateValues,
} from "../api/costRates";
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

/** A rate in force and the next one, e.g. "450.00 from 2026-11-08 (next 500.00 from 2026-12-01)". */
function Rate({ now, next, none }: { now: RateBrief | null; next?: RateBrief | null; none: string }) {
  const { t } = useTranslation();
  return (
    <>
      {now ? t("costRate.from", { rate: formatDecimal(now.rate), date: now.effective_from }) : <span className="muted">{none}</span>}
      {next && <span className="muted small"> {t("costRate.next", { rate: formatDecimal(next.rate), date: next.effective_from })}</span>}
    </>
  );
}

/** P3-05: the dated labour, overhead, regrind and mould amortisation rates. */
export default function CostRatesPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const found = useQuery({ queryKey: costRatesKey, queryFn: getCostRates });
  const done = (d: CostRates) => queryClient.setQueryData(costRatesKey, d);
  const d = found.data;
  return (
    <main className="page">
      <h1>{t("costRate.title")}</h1>
      <p className="muted">{t("costRate.help")}</p>
      <ErrorLine error={found.error} />
      {d && (
        <>
          <Sections data={d} onDone={done} />
          <Machines data={d} />
          <Materials data={d} />
          <Moulds data={d} />
          {d.can_keep && <AddRate data={d} onDone={done} />}
          <History data={d} onDone={done} />
        </>
      )}
    </main>
  );
}

function Sections({ data, onDone }: { data: CostRates; onDone: (d: CostRates) => void }) {
  const { t } = useTranslation();
  const [day, setDay] = useState("");
  const accept = useMutation({
    mutationFn: (sections: string[]) => acceptPayroll({ sections, effective_from: day }),
    onSuccess: onDone,
  });
  const offered = data.sections.some((s) => s.payroll);
  return (
    <section className="panel" aria-label={t("costRate.sections")}>
      <h2>{t("costRate.sections")}</h2>
      <p className="muted">{t("costRate.sectionsHelp")}</p>
      <div className="table-wrap">
        <table aria-label={t("costRate.sections")}>
          <thead>
            <tr>
              <th>{t("costRate.section")}</th>
              <th>{t("costRate.labour")}</th>
              <th>{t("costRate.overhead")}</th>
              {data.can_keep && <th>{t("costRate.payroll")}</th>}
            </tr>
          </thead>
          <tbody>
            {data.sections.map((s) => (
              <tr key={s.code}>
                <td>
                  {s.code} <span className="muted small">{s.name}</span>
                </td>
                <td>
                  <Rate now={s.labour} next={s.labour_next} none={t("costRate.noLabour")} />
                </td>
                <td>
                  <Rate now={s.overhead} next={s.overhead_next} none={t("costRate.zero")} />
                </td>
                {data.can_keep && (
                  <td>
                    {s.payroll ? (
                      <>
                        {t(s.payroll.basis === "division" ? "costRate.offerDivision" : "costRate.offer", {
                          rate: formatDecimal(s.payroll.per_hour),
                          payroll: s.payroll.payroll,
                        })}{" "}
                        <button
                          type="button"
                          className="secondary small"
                          aria-label={t("costRate.acceptFor", { code: s.code })}
                          disabled={accept.isPending}
                          onClick={() => accept.mutate([s.code])}
                        >
                          {t("costRate.accept")}
                        </button>
                      </>
                    ) : (
                      <span className="muted">{t("costRate.noOffer")}</span>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.can_keep && offered && (
        <div className="inline-form">
          <label>
            {t("costRate.acceptFrom")}
            <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
          </label>
          <button type="button" disabled={accept.isPending} onClick={() => accept.mutate([])}>
            {t("costRate.acceptAll")}
          </button>
        </div>
      )}
      <ErrorLine error={accept.error} />
    </section>
  );
}

function Machines({ data }: { data: CostRates }) {
  const { t } = useTranslation();
  if (data.machines.length === 0) return null;
  return (
    <section className="panel" aria-label={t("costRate.machines")}>
      <h2>{t("costRate.machines")}</h2>
      <p className="muted">{t("costRate.machinesHelp")}</p>
      <div className="table-wrap">
        <table aria-label={t("costRate.machines")}>
          <thead>
            <tr>
              <th>{t("costRate.machine")}</th>
              <th>{t("costRate.section")}</th>
              <th>{t("costRate.ownRate")}</th>
              <th className="num">{t("costRate.inForce")}</th>
            </tr>
          </thead>
          <tbody>
            {data.machines.map((m) => (
              <tr key={m.code}>
                <td>
                  {m.code} <span className="muted small">{m.name}</span>
                </td>
                <td>{m.section}</td>
                <td>
                  <Rate now={m.overhead} next={m.overhead_next} none={t("costRate.sectionRate")} />
                </td>
                <td className="num">{formatDecimal(m.in_force)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Materials({ data }: { data: CostRates }) {
  const { t } = useTranslation();
  if (data.materials.length === 0) return null;
  return (
    <section className="panel" aria-label={t("costRate.regrind")}>
      <h2>{t("costRate.regrind")}</h2>
      <p className="muted">{t("costRate.regrindHelp")}</p>
      <div className="table-wrap">
        <table aria-label={t("costRate.regrind")}>
          <thead>
            <tr>
              <th>{t("costRate.material")}</th>
              <th className="num">{t("costRate.perKg")}</th>
              <th>{t("costRate.basis")}</th>
            </tr>
          </thead>
          <tbody>
            {data.materials.map((m) => (
              <tr key={m.code}>
                <td>
                  {m.code} <span className="muted small">{m.name}</span>
                </td>
                <td className="num">{m.per_kg ? formatDecimal(m.per_kg) : <span className="muted">{t("costRate.noStockCost")}</span>}</td>
                <td>
                  {m.basis === "set" ? t("costRate.basisSet", { date: m.set?.effective_from ?? "" }) : t("costRate.basisMaterial")}
                  {m.set_next && (
                    <span className="muted small">
                      {" "}
                      {t("costRate.next", { rate: formatDecimal(m.set_next.rate), date: m.set_next.effective_from })}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Moulds({ data }: { data: CostRates }) {
  const { t } = useTranslation();
  return (
    <section className="panel" aria-label={t("costRate.moulds")}>
      <h2>{t("costRate.moulds")}</h2>
      <p className="muted">{t("costRate.mouldsHelp")}</p>
      {data.moulds.length === 0 ? (
        <p className="muted">{t("costRate.noMoulds")}</p>
      ) : (
        <div className="table-wrap">
          <table aria-label={t("costRate.moulds")}>
            <thead>
              <tr>
                <th>{t("costRate.mould")}</th>
                <th className="num">{t("costRate.mouldCost")}</th>
                <th className="num">{t("costRate.lifeShots")}</th>
                <th>{t("costRate.perShot")}</th>
              </tr>
            </thead>
            <tbody>
              {data.moulds.map((m) => (
                <tr key={m.code}>
                  <td>
                    {m.code} <span className="muted small">{m.name}</span>
                  </td>
                  <td className="num">{formatDecimal(m.mould_cost)}</td>
                  <td className="num">{m.life_shots === null ? "" : formatDecimal(String(m.life_shots))}</td>
                  <td>
                    <Rate now={m.rate} next={m.next} none={t("costRate.zero")} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

const EMPTY = { target: "", effective_from: "", rate: "", mould_cost: "", life_shots: "", reason: "" };

function AddRate({ data, onDone }: { data: CostRates; onDone: (d: CostRates) => void }) {
  const { t } = useTranslation();
  const [kind, setKind] = useState<RateKind>("labour");
  const [onMachine, setOnMachine] = useState(false);
  const [values, setValues] = useState(EMPTY);
  const set = (key: keyof typeof EMPTY) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  const targetKey = kind === "regrind" ? "material" : kind === "mould" ? "mould" : kind === "overhead" && onMachine ? "machine" : "section";
  const options =
    targetKey === "material"
      ? data.materials
      : targetKey === "mould"
        ? data.moulds
        : targetKey === "machine"
          ? data.machines
          : data.sections;
  const save = useMutation({
    mutationFn: () => {
      const body: RateValues = { kind, [targetKey]: values.target, effective_from: values.effective_from, reason: values.reason };
      if (kind === "mould") Object.assign(body, { mould_cost: values.mould_cost, life_shots: values.life_shots });
      else body.rate = values.rate;
      return addCostRate(body);
    },
    onSuccess: (d) => {
      setValues(EMPTY);
      onDone(d);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <section className="panel" aria-label={t("costRate.add")}>
      <h2>{t("costRate.add")}</h2>
      <form className="form-grid" aria-label={t("costRate.add")} onSubmit={submit}>
        <label>
          {t("costRate.kind")}
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as RateKind);
              setValues({ ...values, target: "" });
            }}
          >
            {(["labour", "overhead", "regrind", "mould"] as const).map((k) => (
              <option key={k} value={k}>
                {t(`costRate.kinds.${k}`)}
              </option>
            ))}
          </select>
        </label>
        {kind === "overhead" && (
          <label className="check">
            <input
              type="checkbox"
              checked={onMachine}
              onChange={(e) => {
                setOnMachine(e.target.checked);
                setValues({ ...values, target: "" });
              }}
            />{" "}
            {t("costRate.forOneMachine")}
          </label>
        )}
        <label>
          {t(`costRate.targets.${targetKey}`)}
          <select value={values.target} onChange={set("target")}>
            <option value="">{t("costRate.choose")}</option>
            {options.map((o) => (
              <option key={o.code} value={o.code}>
                {o.code} {o.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("costRate.effectiveFrom")}
          <input type="date" value={values.effective_from} onChange={set("effective_from")} />
        </label>
        {kind === "mould" ? (
          <>
            <label>
              {t("costRate.mouldCost")}
              <input inputMode="decimal" value={values.mould_cost} onChange={set("mould_cost")} />
            </label>
            <label>
              {t("costRate.lifeShots")}
              <input inputMode="numeric" value={values.life_shots} onChange={set("life_shots")} />
            </label>
          </>
        ) : (
          <label>
            {t(`costRate.rateOf.${kind}`)}
            <input inputMode="decimal" value={values.rate} onChange={set("rate")} />
          </label>
        )}
        <label className="wide">
          {t("costRate.reason")}
          <input value={values.reason} onChange={set("reason")} />
        </label>
        <div className="wide row-actions">
          <button type="submit" disabled={save.isPending}>
            {t("costRate.save")}
          </button>
        </div>
        <p className="muted wide">{t("costRate.addHelp")}</p>
        <div className="wide">
          <ErrorLine error={save.error} />
        </div>
      </form>
    </section>
  );
}

function History({ data, onDone }: { data: CostRates; onDone: (d: CostRates) => void }) {
  const { t } = useTranslation();
  const remove = useMutation({ mutationFn: removeCostRate, onSuccess: onDone });
  if (data.history.length === 0) return null;
  return (
    <section className="panel" aria-label={t("costRate.history")}>
      <h2>{t("costRate.history")}</h2>
      <div className="table-wrap">
        <table aria-label={t("costRate.history")}>
          <thead>
            <tr>
              <th>{t("costRate.kind")}</th>
              <th>{t("costRate.for")}</th>
              <th>{t("costRate.effectiveFrom")}</th>
              <th className="num">{t("costRate.rate")}</th>
              <th>{t("costRate.reason")}</th>
              <th>{t("costRate.by")}</th>
              {data.can_keep && <th />}
            </tr>
          </thead>
          <tbody>
            {data.history.map((r) => (
              <tr key={r.id}>
                <td>{r.kind_label}</td>
                <td>{r.target}</td>
                <td>{r.effective_from}</td>
                <td className="num">{formatDecimal(r.rate)}</td>
                <td>
                  {r.reason}
                  {r.source === "payroll" && <span className="muted small"> {t("costRate.fromPayroll")}</span>}
                </td>
                <td>{r.created_by}</td>
                {data.can_keep && (
                  <td>
                    {!r.in_force && (
                      <button
                        type="button"
                        className="secondary small"
                        aria-label={t("costRate.removeOf", { target: r.target, date: r.effective_from })}
                        disabled={remove.isPending}
                        onClick={() => remove.mutate(r.id)}
                      >
                        {t("costRate.remove")}
                      </button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ErrorLine error={remove.error} />
    </section>
  );
}
