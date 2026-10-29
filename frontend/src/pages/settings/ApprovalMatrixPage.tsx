import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can } from "../../api/access";
import {
  addRule,
  getMatrix,
  getReminders,
  remindersKey,
  setReminder,
  type ReminderSetting,
  matrixKey,
  previewRoute,
  switchOffRule,
  type ApprovalRule,
  type RouteStep,
} from "../../api/approvals";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";
import { formatDecimal } from "../../lib/decimal";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

function Conditions({ rule }: { rule: ApprovalRule }) {
  const { t } = useTranslation();
  const parts: string[] = [];
  if (rule.min_amount) parts.push(t("matrix.from", { amount: formatDecimal(rule.min_amount) }));
  if (rule.max_amount) parts.push(t("matrix.upTo", { amount: formatDecimal(rule.max_amount) }));
  if (rule.division) parts.push(t("matrix.division", { code: rule.division }));
  if (rule.subtype) parts.push(t("matrix.subtype", { subtype: rule.subtype }));
  return <>{parts.length ? parts.join(" · ") : t("matrix.always")}</>;
}

/** Who approves each kind of document, level by level (spec 3, approval engine). */
export default function ApprovalMatrixPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const matrix = useQuery({ queryKey: matrixKey, queryFn: getMatrix });
  const data = matrix.data;
  const canManage = can(me.access, "settings", "manage");
  const [reason, setReason] = useState("");
  const switchOff = useMutation({
    mutationFn: (id: number) => switchOffRule(id, reason),
    onSuccess: (data) => queryClient.setQueryData(matrixKey, data),
  });

  return (
    <main className="page">
      <h1>{t("matrix.title")}</h1>
      <p className="muted">{t("matrix.help")}</p>
      {data?.document_types.map((type) => {
        const rules = data.rules.filter((r) => r.document_type === type.code);
        return (
          <section className="panel" key={type.code} aria-label={type.name}>
            <h2>{type.name}</h2>
            <p className="muted">
              {t("matrix.levelOne")}
              {type.final_role && ` ${t("matrix.minimum", { levels: String(type.min_approvals) })}`}
            </p>
            <div className="table-wrap">
              <table aria-label={t("matrix.rulesOf", { name: type.name })}>
                <thead>
                  <tr>
                    <th className="num">{t("matrix.level")}</th>
                    <th>{t("matrix.role")}</th>
                    <th>{t("matrix.conditions")}</th>
                    <th>{t("users.status")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rules.map((rule) => (
                    <tr key={rule.id} className={rule.is_active ? undefined : "muted"}>
                      <td className="num">L{rule.level}</td>
                      <td>{rule.role.name}</td>
                      <td>
                        <Conditions rule={rule} />
                      </td>
                      <td>{rule.is_active ? t("matrix.inUse") : t("matrix.off")}</td>
                      <td>
                        {canManage && rule.is_active && (
                          <button
                            type="button"
                            className="small secondary"
                            onClick={() => switchOff.mutate(rule.id)}
                          >
                            {t("matrix.switchOff")}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {canManage && (
              <label className="inline-form">
                {t("access.reason")}
                <input value={reason} onChange={(e) => setReason(e.target.value)} />
              </label>
            )}
            <ErrorLine error={switchOff.error} />
            {canManage && <AddRule documentType={type.code} subtypeLabel={type.subtype_label} reason={reason} />}
            <RouteCheck documentType={type.code} subtypeLabel={type.subtype_label} />
          </section>
        );
      })}
      <ErrorLine error={matrix.error} />
      <Reminders canManage={canManage} />
    </main>
  );
}

function AddRule(props: { documentType: string; subtypeLabel: string; reason: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const matrix = useQuery({ queryKey: matrixKey, queryFn: getMatrix });
  const [values, setValues] = useState({ level: "2", role: "", min: "", max: "", division: "", subtype: "" });
  const set = (key: keyof typeof values) => (value: string) => setValues((now) => ({ ...now, [key]: value }));
  const save = useMutation({
    mutationFn: () =>
      addRule({
        document_type: props.documentType,
        level: Number(values.level),
        role: values.role,
        min_amount: values.min || null,
        max_amount: values.max || null,
        division: values.division || null,
        subtype: values.subtype,
        reason: props.reason,
      }),
    onSuccess: (data) => queryClient.setQueryData(matrixKey, data),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className="form-grid" aria-label={t("matrix.add")} onSubmit={submit}>
      <label>
        {t("matrix.level")}
        <input type="number" min={2} max={9} value={values.level} required onChange={(e) => set("level")(e.target.value)} />
      </label>
      <label>
        {t("matrix.role")}
        <select value={values.role} required onChange={(e) => set("role")(e.target.value)}>
          <option value="">—</option>
          {matrix.data?.roles.map((role) => (
            <option key={role.code} value={role.code}>
              {role.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t("matrix.minAmount")}
        <input inputMode="decimal" value={values.min} onChange={(e) => set("min")(e.target.value)} />
      </label>
      <label>
        {t("matrix.maxAmount")}
        <input inputMode="decimal" value={values.max} onChange={(e) => set("max")(e.target.value)} />
      </label>
      <label>
        {t("matrix.divisionOptional")}
        <input value={values.division} maxLength={2} onChange={(e) => set("division")(e.target.value)} />
      </label>
      {props.subtypeLabel && (
        <label>
          {props.subtypeLabel}
          <input value={values.subtype} onChange={(e) => set("subtype")(e.target.value)} />
        </label>
      )}
      <div className="wide">
        <button type="submit" disabled={save.isPending}>
          {t("matrix.add")}
        </button>
      </div>
      <div className="wide">
        <ErrorLine error={save.error} />
      </div>
    </form>
  );
}

function RouteCheck(props: { documentType: string; subtypeLabel: string }) {
  const { t } = useTranslation();
  const [amount, setAmount] = useState("");
  const [subtype, setSubtype] = useState("");
  const check = useMutation({
    mutationFn: () => previewRoute({ document_type: props.documentType, amount, subtype }),
  });
  const steps: RouteStep[] = check.data ?? [];

  return (
    <form
      className="inline-form"
      aria-label={t("matrix.check")}
      onSubmit={(e) => {
        e.preventDefault();
        check.mutate();
      }}
    >
      <label>
        {t("matrix.amount")}
        <input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
      </label>
      {props.subtypeLabel && (
        <label>
          {props.subtypeLabel}
          <input value={subtype} onChange={(e) => setSubtype(e.target.value)} />
        </label>
      )}
      <button type="submit" className="secondary">
        {t("matrix.check")}
      </button>
      {check.data && (
        <p role="status">
          {[t("matrix.submitter"), ...steps.map((s) => `L${s.level} ${s.role_name}`)].join(" → ")}
        </p>
      )}
      <ErrorLine error={check.error} />
    </form>
  );
}

/** Reminders: approvers are reminded again, once a day, when a document has waited at
 * their level for the set number of days (spec 4.3, P1-09). */
function Reminders({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation();
  const rows = useQuery({ queryKey: remindersKey, queryFn: getReminders });
  return (
    <section className="panel" aria-label={t("reminders.title")}>
      <h2>{t("reminders.title")}</h2>
      <p className="muted">{t("reminders.help")}</p>
      {rows.data?.map((row) => (
        <ReminderRow key={row.document_type} row={row} canManage={canManage} />
      ))}
      <ErrorLine error={rows.error} />
    </section>
  );
}

function ReminderRow({ row, canManage }: { row: ReminderSetting; canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [enabled, setEnabled] = useState(row.enabled);
  const [days, setDays] = useState(String(row.after_days));
  const save = useMutation({
    mutationFn: () => setReminder({ document_type: row.document_type, enabled, after_days: Number(days), reason: "" }),
    onSuccess: (data) => queryClient.setQueryData(remindersKey, data),
  });
  const changed = enabled !== row.enabled || days !== String(row.after_days);
  return (
    <div className="inline-form" role="group" aria-label={row.name}>
      <strong>{row.name}</strong>
      <label>
        <input type="checkbox" checked={enabled} disabled={!canManage} onChange={(e) => setEnabled(e.target.checked)} />{" "}
        {t("reminders.on")}
      </label>
      <label>
        {t("reminders.afterDays")}
        <input
          type="number"
          min={1}
          max={60}
          value={days}
          disabled={!canManage || !enabled}
          onChange={(e) => setDays(e.target.value)}
        />
      </label>
      {canManage && (
        <button type="button" className="small" disabled={!changed || save.isPending} onClick={() => save.mutate()}>
          {t("reminders.save")}
        </button>
      )}
      <ErrorLine error={save.error} />
    </div>
  );
}
