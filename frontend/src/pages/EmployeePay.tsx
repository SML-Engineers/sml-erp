import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import {
  actOnPayChange,
  editPayChange,
  employeePayKey,
  getEmployeePay,
  preparePayChange,
  SETTING_FIELDS,
  type ChangeAction,
  type ChangeValues,
  type EmployeePay as Pay,
  type PayChange,
  type PaySettings,
} from "../api/pay";
import { formatDecimal } from "../lib/decimal";

/** The attendance bonus a new employee starts with (owner, 5 Nov 2026). */
const ATTENDANCE_BONUS = "1500";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

const mark = (value: boolean | null) => (value === null ? "" : value ? "true" : "false");

/** An employee's pay (P2B-02) and pay changes approved by the Director (P2B-17). */
export default function EmployeePay({ employeeId }: { employeeId: number }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = employeePayKey(employeeId);
  const found = useQuery({ queryKey: key, queryFn: () => getEmployeePay(employeeId) });
  const done = (p: Pay) => queryClient.setQueryData(key, p);
  const [editing, setEditing] = useState<PayChange | "new" | null>(null);
  const p = found.data;
  return (
    <section className="panel" aria-label={t("pay.title")}>
      <h2>{t("pay.title")}</h2>
      <ErrorLine error={found.error} />
      {p && (
        <>
          <div className="table-wrap">
            <table aria-label={t("pay.current")}>
              <thead>
                <tr>
                  <th>{t("pay.component")}</th>
                  <th>{t("pay.since")}</th>
                  <th>{t("pc.epf")}</th>
                  <th>{t("pc.apit")}</th>
                  <th className="num">{t("pay.amount")}</th>
                </tr>
              </thead>
              <tbody>
                {p.current.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
                      {t("pay.none")}
                    </td>
                  </tr>
                )}
                {p.current.map((x) => (
                  <tr key={x.component}>
                    <td>
                      {x.component_name}
                      {x.kind === "deduction" && <span className="tag"> {t("pc.kinds.deduction")}</span>}
                      {x.own_marks && <span className="tag"> {t("pay.ownMarks")}</span>}
                    </td>
                    <td>{x.since}</td>
                    <td>{x.epf_liable ? t("pc.yes") : "—"}</td>
                    <td>{x.apit_taxable ? t("pc.yes") : "—"}</td>
                    <td className="num">{x.kind === "deduction" ? `(${formatDecimal(x.amount)})` : formatDecimal(x.amount)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th colSpan={4}>{t("pay.net")}</th>
                  <th className="num">{formatDecimal(p.totals.net)}</th>
                </tr>
              </tfoot>
            </table>
          </div>
          <p className="muted">
            {t("pay.totalsHelp", {
              epf: formatDecimal(p.totals.epf_earnings),
              apit: formatDecimal(p.totals.apit_earnings),
            })}
          </p>
          <Settings title={t("pay.settings")} settings={p.settings} defaults={p.defaults} since={p.settings_since} />

          <h3>{t("pay.changes")}</h3>
          <p className="muted">{t("pay.changesHelp")}</p>
          {p.can_prepare && editing === null && (
            <button type="button" onClick={() => setEditing("new")}>
              {t("pay.prepare")}
            </button>
          )}
          {editing !== null && (
            <ChangeForm
              employeeId={employeeId}
              pay={p}
              current={editing === "new" ? null : editing}
              onDone={(next) => {
                if (next) done(next);
                setEditing(null);
              }}
            />
          )}
          {p.changes.length === 0 && <p className="muted">{t("pay.noChanges")}</p>}
          {p.changes.map((c) => (
            <ChangeCard key={c.id} change={c} pay={p} onDone={done} onEdit={() => setEditing(c)} />
          ))}

          <h3>{t("pay.history")}</h3>
          <div className="table-wrap">
            <table aria-label={t("pay.history")}>
              <thead>
                <tr>
                  <th>{t("pay.from")}</th>
                  <th>{t("pay.component")}</th>
                  <th className="num">{t("pay.amount")}</th>
                  <th>{t("pay.reasonCol")}</th>
                  <th>{t("pay.by")}</th>
                </tr>
              </thead>
              <tbody>
                {p.history.map((r) => (
                  <tr key={r.id}>
                    <td>{r.effective_from}</td>
                    <td>{r.component_name}</td>
                    <td className="num">{formatDecimal(r.amount)}</td>
                    <td>{r.reason}</td>
                    <td>{r.created_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function Settings({
  title,
  settings,
  defaults,
  since,
}: {
  title: string;
  settings: PaySettings | null;
  defaults: PaySettings;
  since?: string | null;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <h4>
        {title}
        {since && <span className="muted"> {t("pay.since")} {since}</span>}
      </h4>
      <dl className="details">
        {SETTING_FIELDS.map((f) => {
          const own = settings?.[f] ?? null;
          return (
            <div key={f}>
              <dt>{t(`pay.s.${f}`)}</dt>
              <dd>
                {own ?? defaults[f] ?? "—"}
                {own === null && <span className="muted"> ({t("pay.default")})</span>}
              </dd>
            </div>
          );
        })}
        <div>
          <dt>{t("pay.s.apit")}</dt>
          <dd>{t(`pay.apit.${settings?.apit ?? "primary"}`)}</dd>
        </div>
      </dl>
    </div>
  );
}

function ChangeCard({
  change: c,
  pay,
  onDone,
  onEdit,
}: {
  change: PayChange;
  pay: Pay;
  onDone: (p: Pay) => void;
  onEdit: () => void;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const act = useMutation({
    mutationFn: (action: ChangeAction) => actOnPayChange(c.id, action, reason),
    onSuccess: (p) => {
      setReason("");
      onDone(p);
    },
  });
  const needsReason = c.can_approve || c.can_withdraw;
  const title = c.is_new_employee ? t("pay.newEmployee") : t("pay.change");
  return (
    <article className="panel" aria-label={`${title} ${c.effective_from}`}>
      <h4>
        {title} — {t("pay.fromMonth", { month: c.effective_from })}{" "}
        <span className="tag">{c.returned && c.status === "draft" ? t("pay.returned") : c.status_label}</span>
      </h4>
      <p>
        {c.reason} <span className="muted">— {c.created_by}</span>
      </p>
      {c.lines.length > 0 && (
        <div className="table-wrap">
          <table aria-label={t("pay.amounts")}>
            <thead>
              <tr>
                <th>{t("pay.component")}</th>
                <th className="num">{t("pay.amount")}</th>
                <th>{t("pc.epf")}</th>
                <th>{t("pc.apit")}</th>
              </tr>
            </thead>
            <tbody>
              {c.lines.map((x) => (
                <tr key={x.component}>
                  <td>{x.component_name}</td>
                  <td className="num">{formatDecimal(x.amount)}</td>
                  <td>{x.epf_liable === null ? t("pay.default") : x.epf_liable ? t("pc.yes") : t("pay.no")}</td>
                  <td>{x.apit_taxable === null ? t("pay.default") : x.apit_taxable ? t("pc.yes") : t("pay.no")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {c.settings && <Settings title={t("pay.newSettings")} settings={c.settings} defaults={pay.defaults} />}
      {c.history.length > 0 && (
        <ul className="muted">
          {c.history.map((h, i) => (
            <li key={i}>
              {h.action} — {h.user}
              {h.reason && `: ${h.reason}`}
            </li>
          ))}
        </ul>
      )}
      {needsReason && (
        <label>
          {c.can_approve ? t("pay.comment") : t("pay.withdrawReason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      )}
      <div className="row-actions">
        {c.can_edit && (
          <button type="button" className="secondary" onClick={onEdit}>
            {t("pay.edit")}
          </button>
        )}
        {c.can_submit && (
          <button type="button" disabled={act.isPending} onClick={() => act.mutate("submit")}>
            {t("pay.submit")}
          </button>
        )}
        {c.can_approve && (
          <>
            <button type="button" disabled={act.isPending} onClick={() => act.mutate("approve")}>
              {t("pay.approve")}
            </button>
            <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("return")}>
              {t("pay.return")}
            </button>
            <button type="button" className="danger" disabled={act.isPending} onClick={() => act.mutate("reject")}>
              {t("pay.reject")}
            </button>
          </>
        )}
        {c.can_withdraw && (
          <button type="button" className="secondary" disabled={act.isPending} onClick={() => act.mutate("withdraw")}>
            {t("pay.withdraw")}
          </button>
        )}
      </div>
      <ErrorLine error={act.error} />
    </article>
  );
}

function ChangeForm({
  employeeId,
  pay,
  current,
  onDone,
}: {
  employeeId: number;
  pay: Pay;
  current: PayChange | null;
  onDone: (p: Pay | null) => void;
}) {
  const { t } = useTranslation();
  const isNew = current ? current.is_new_employee : !pay.changes.some((c) => c.status === "approved");
  const start = (): ChangeValues => ({
    effective_from: current?.effective_from ?? pay.next_month,
    reason: current?.reason ?? "",
    lines: pay.components.map((comp) => {
      const line = current?.lines.find((x) => x.component === comp.code);
      const amount = line?.amount ?? (!current && isNew && comp.code === "ATTEND" ? ATTENDANCE_BONUS : "");
      return {
        component: comp.code,
        amount,
        epf_liable: line?.epf_liable ?? null,
        apit_taxable: line?.apit_taxable ?? null,
      };
    }),
    settings: current
      ? current.settings && Object.fromEntries(Object.entries(current.settings).map(([k, v]) => [k, v ?? ""]))
      : null,
  });
  const [values, setValues] = useState<ChangeValues>(start);
  const save = useMutation({
    mutationFn: () => {
      const body = { ...values, lines: values.lines.filter((x) => x.amount !== "") };
      return current ? editPayChange(current.id, body) : preparePayChange(employeeId, body);
    },
    onSuccess: (p) => onDone(p),
  });
  const setLine = (code: string, change: Partial<ChangeValues["lines"][number]>) =>
    setValues((v) => ({ ...v, lines: v.lines.map((x) => (x.component === code ? { ...x, ...change } : x)) }));
  const setSetting = (field: string, value: string) =>
    setValues((v) => ({ ...v, settings: { ...(v.settings ?? {}), [field]: value } }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const flag = (value: string) => (value === "" ? null : value === "true");
  return (
    <form className="panel form-grid" aria-label={t("pay.prepare")} onSubmit={submit}>
      <h3 className="wide">{isNew ? t("pay.prepareNew") : t("pay.prepare")}</h3>
      <label>
        {t("pay.from")}
        <input
          type="month"
          value={values.effective_from}
          onChange={(e) => setValues((v) => ({ ...v, effective_from: e.target.value }))}
        />
      </label>
      <label>
        {t("pay.reason")}
        <input value={values.reason} onChange={(e) => setValues((v) => ({ ...v, reason: e.target.value }))} />
      </label>
      <div className="wide table-wrap">
        <table aria-label={t("pay.amounts")}>
          <thead>
            <tr>
              <th>{t("pay.component")}</th>
              <th>{t("pay.now")}</th>
              <th>{t("pay.newAmount")}</th>
              <th>{t("pc.epf")}</th>
              <th>{t("pc.apit")}</th>
            </tr>
          </thead>
          <tbody>
            {pay.components.map((comp) => {
              const line = values.lines.find((x) => x.component === comp.code)!;
              const now = pay.current.find((x) => x.component === comp.code);
              const earning = comp.kind === "earning";
              return (
                <tr key={comp.code}>
                  <td>
                    {comp.name}
                    {comp.is_allowance && <span className="tag"> {t("pc.allowance")}</span>}
                  </td>
                  <td className="num">{now ? formatDecimal(now.amount) : "—"}</td>
                  <td>
                    <input
                      aria-label={`${t("pay.newAmount")} ${comp.name}`}
                      inputMode="decimal"
                      value={line.amount}
                      onChange={(e) => setLine(comp.code, { amount: e.target.value })}
                    />
                  </td>
                  <td>
                    {earning && (
                      <select
                        aria-label={`${t("pc.epf")} ${comp.name}`}
                        value={mark(line.epf_liable)}
                        onChange={(e) => setLine(comp.code, { epf_liable: flag(e.target.value) })}
                      >
                        <option value="">{t("pay.defaultMark", { value: comp.epf_liable ? t("pc.yes") : t("pay.no") })}</option>
                        <option value="true">{t("pc.yes")}</option>
                        <option value="false">{t("pay.no")}</option>
                      </select>
                    )}
                  </td>
                  <td>
                    {earning && (
                      <select
                        aria-label={`${t("pc.apit")} ${comp.name}`}
                        value={mark(line.apit_taxable)}
                        onChange={(e) => setLine(comp.code, { apit_taxable: flag(e.target.value) })}
                      >
                        <option value="">{t("pay.defaultMark", { value: comp.apit_taxable ? t("pc.yes") : t("pay.no") })}</option>
                        <option value="true">{t("pc.yes")}</option>
                        <option value="false">{t("pay.no")}</option>
                      </select>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted wide">{t("pay.amountsHelp")}</p>
      <label className="check wide">
        <input
          type="checkbox"
          checked={values.settings !== null}
          onChange={(e) => setValues((v) => ({ ...v, settings: e.target.checked ? {} : null }))}
        />{" "}
        {t("pay.withSettings")}
      </label>
      {values.settings !== null && (
        <>
          {SETTING_FIELDS.map((f) => (
            <label key={f}>
              {t(`pay.s.${f}`)}
              <input
                inputMode="decimal"
                placeholder={`${t("pay.default")}: ${pay.defaults[f] ?? "—"}`}
                value={values.settings?.[f] ?? ""}
                onChange={(e) => setSetting(f, e.target.value)}
              />
            </label>
          ))}
          <label>
            {t("pay.s.apit")}
            <select value={values.settings?.apit || "primary"} onChange={(e) => setSetting("apit", e.target.value)}>
              <option value="primary">{t("pay.apit.primary")}</option>
              <option value="secondary">{t("pay.apit.secondary")}</option>
            </select>
          </label>
          <p className="muted wide">{t("pay.settingsHelp")}</p>
        </>
      )}
      <div className="wide row-actions">
        <button type="submit" disabled={save.isPending}>
          {t("pay.saveDraft")}
        </button>
        <button type="button" className="secondary" onClick={() => onDone(null)}>
          {t("pc.cancel")}
        </button>
      </div>
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}
