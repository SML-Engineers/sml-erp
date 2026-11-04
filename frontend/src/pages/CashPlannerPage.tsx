import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { addWhatIf, cashPlanKey, getCashPlan, removeWhatIf, type CashPlan } from "../api/cashPlanner";
import { ApiError } from "../api/client";
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

const negative = (amount: string) => amount.startsWith("-");

/** The day-by-day balance as a small line, red below nil. */
function Chart({ plan }: { plan: CashPlan }) {
  const { t } = useTranslation();
  const values = plan.days.map((d) => Number(d.closing));
  const top = Math.max(0, ...values);
  const bottom = Math.min(0, ...values);
  const span = top - bottom || 1;
  const width = 600;
  const height = 140;
  const y = (v: number) => height - ((v - bottom) / span) * height;
  const points = values.map((v, i) => `${(i / (values.length - 1 || 1)) * width},${y(v).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t("planner.chart")} style={{ width: "100%", maxWidth: 720, height: "auto" }}>
      <line x1={0} x2={width} y1={y(0)} y2={y(0)} stroke="currentColor" strokeOpacity={0.3} strokeDasharray="4 4" />
      <polyline points={points} fill="none" stroke={negative(plan.lowest.amount) ? "#b42318" : "#1f6feb"} strokeWidth={2} />
    </svg>
  );
}

/** Cash flow planner (P2-25): the bank and cash balance projected day by day for 13 weeks,
 * from what customers owe, what we owe, recurring payments and "what-if" items. */
export default function CashPlannerPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [off, setOff] = useState<number[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [form, setForm] = useState({ description: "", on_date: "", amount: "", direction: "out" as "in" | "out" });
  const plan = useQuery({ queryKey: [...cashPlanKey, off], queryFn: () => getCashPlan(off), placeholderData: (p) => p });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: cashPlanKey });
  const add = useMutation({
    mutationFn: () => addWhatIf(form),
    onSuccess: () => {
      setForm({ description: "", on_date: "", amount: "", direction: "out" });
      refresh();
    },
  });
  const remove = useMutation({ mutationFn: (id: number) => removeWhatIf(id), onSuccess: refresh });
  const data = plan.data;
  return (
    <main className="page">
      <h1>{t("planner.title")}</h1>
      <p className="muted">{t("planner.help")}</p>
      <ErrorLine error={plan.error} />
      {data && (
        <>
          <section className="panel" aria-label={t("planner.summary")}>
            <dl className="details">
              <dt>{t("planner.today", { date: data.today })}</dt>
              <dd>LKR {formatDecimal(data.opening)}</dd>
              <dt>{t("planner.lowest")}</dt>
              <dd className={negative(data.lowest.amount) ? "danger-text" : undefined}>
                LKR {formatDecimal(data.lowest.amount)} ({data.lowest.day})
              </dd>
              <dt>{t("planner.end", { date: data.end })}</dt>
              <dd>LKR {formatDecimal(data.closing)}</dd>
            </dl>
            {negative(data.lowest.amount) && (
              <p className="form-error" role="alert">
                {t("planner.shortfall", { day: data.lowest.day })}
              </p>
            )}
            <Chart plan={data} />
          </section>

          <section className="panel" aria-label={t("planner.byWeek")}>
            <h2>{t("planner.byWeek")}</h2>
            <div className="table-wrap">
              <table aria-label={t("planner.byWeek")}>
                <thead>
                  <tr>
                    <th>{t("planner.week")}</th>
                    <th className="num">{t("planner.in")}</th>
                    <th className="num">{t("planner.out")}</th>
                    <th className="num">{t("planner.balance")}</th>
                    <th className="num">{t("planner.lowestInWeek")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.weeks.map((w) => {
                    const items = data.flows.filter((f) => f.day >= w.from && f.day <= w.to);
                    return (
                      <WeekRows
                        key={w.from}
                        week={w}
                        items={items}
                        open={open === w.from}
                        onToggle={() => setOpen(open === w.from ? null : w.from)}
                      />
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel" aria-label={t("planner.whatIfs")}>
            <h2>{t("planner.whatIfs")}</h2>
            <p className="muted">{t("planner.whatIfsHelp")}</p>
            <ul className="changes">
              {data.what_ifs.map((i) => (
                <li key={i.id}>
                  <label>
                    <input
                      type="checkbox"
                      checked={!off.includes(i.id)}
                      onChange={(e) => setOff(e.target.checked ? off.filter((x) => x !== i.id) : [...off, i.id])}
                    />{" "}
                    {i.on_date} · {i.description} · LKR {formatDecimal(i.amount)}
                  </label>{" "}
                  {data.can_plan && (
                    <button type="button" className="small secondary" onClick={() => remove.mutate(i.id)}>
                      {t("planner.remove")}
                    </button>
                  )}
                </li>
              ))}
            </ul>
            {data.can_plan && (
              <div className="inline-form">
                <input aria-label={t("planner.description")} placeholder={t("planner.description")} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                <input type="date" aria-label={t("planner.date")} value={form.on_date} onChange={(e) => setForm({ ...form, on_date: e.target.value })} />
                <input aria-label={t("planner.amount")} placeholder="LKR" inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
                <select aria-label={t("planner.direction")} value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value as "in" | "out" })}>
                  <option value="out">{t("planner.moneyOut")}</option>
                  <option value="in">{t("planner.moneyIn")}</option>
                </select>
                <button type="button" disabled={add.isPending} onClick={() => add.mutate()}>
                  {t("planner.add")}
                </button>
              </div>
            )}
            <ErrorLine error={add.error ?? remove.error} />
          </section>
        </>
      )}
    </main>
  );
}

function WeekRows({
  week: w,
  items,
  open,
  onToggle,
}: {
  week: CashPlan["weeks"][number];
  items: CashPlan["flows"];
  open: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  return (
    <>
      <tr>
        <td>
          <button type="button" className="link" aria-expanded={open} onClick={onToggle}>
            {w.from} – {w.to}
          </button>
        </td>
        <td className="num">{formatDecimal(w.in)}</td>
        <td className="num">{formatDecimal(w.out)}</td>
        <td className={`num ${negative(w.closing) ? "danger-text" : ""}`}>{formatDecimal(w.closing)}</td>
        <td className={`num ${negative(w.lowest) ? "danger-text" : ""}`}>{formatDecimal(w.lowest)}</td>
      </tr>
      {open &&
        (items.length === 0 ? (
          <tr>
            <td colSpan={5} className="muted">
              {t("planner.nothing")}
            </td>
          </tr>
        ) : (
          items.map((f, i) => (
            <tr key={i} className="muted">
              <td>
                {f.day} · {t(`planner.kinds.${f.kind}`)}: {f.link ? <Link to={f.link}>{f.label}</Link> : f.label}
              </td>
              <td className="num">{negative(f.amount) ? "" : formatDecimal(f.amount)}</td>
              <td className="num">{negative(f.amount) ? formatDecimal(f.amount.slice(1)) : ""}</td>
              <td colSpan={2} />
            </tr>
          ))
        ))}
    </>
  );
}
