import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../api/client";
import {
  addReason,
  addSetting,
  changeReason,
  getSetup,
  setupKey,
  type ProductionSetting,
  type ProductionSetup,
  type Reason,
  type SettingValues,
} from "../../api/productionSetup";

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {error instanceof ApiError && error.detail ? error.detail : t("common.error")}
    </p>
  );
}

/** P3-02: reject and downtime reasons per division, and the dated production settings. */
export default function ProductionSetupPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const found = useQuery({ queryKey: setupKey, queryFn: getSetup });
  const done = (d: ProductionSetup) => queryClient.setQueryData(setupKey, d);
  const d = found.data;
  return (
    <main className="page">
      <h1>{t("prodSetup.title")}</h1>
      <ErrorLine error={found.error} />
      {d && (
        <>
          <Settings data={d} onDone={done} />
          <Reasons data={d} onDone={done} />
        </>
      )}
    </main>
  );
}

function Settings({ data, onDone }: { data: ProductionSetup; onDone: (d: ProductionSetup) => void }) {
  const { t } = useTranslation();
  const current = data.settings.find((s) => s.id === data.current)!;
  const [values, setValues] = useState<SettingValues>({
    effective_from: "",
    grace_hours: current.grace_hours,
    reject_alert_pct: current.reject_alert_pct,
    overrun_alert_pct: current.overrun_alert_pct,
    min_margin_pct: current.min_margin_pct,
    reason: "",
  });
  const save = useMutation({ mutationFn: () => addSetting(values), onSuccess: onDone });
  const set = (key: keyof SettingValues) => (e: { target: { value: string } }) => setValues({ ...values, [key]: e.target.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  const label = (s: ProductionSetting) =>
    t("prodSetup.line", {
      grace: s.grace_hours,
      reject: s.reject_alert_pct,
      overrun: s.overrun_alert_pct,
      margin: s.min_margin_pct ? `${s.min_margin_pct}%` : t("prodSetup.quotationMargin"),
    });
  return (
    <section className="panel" aria-label={t("prodSetup.settings")}>
      <h2>{t("prodSetup.settings")}</h2>
      <p>
        <strong>{t("prodSetup.now")}</strong> {label(current)}
      </p>
      <ul className="plain muted">
        {data.settings
          .filter((s) => s.id !== data.current)
          .map((s) => (
            <li key={s.id}>
              {s.in_force ? t("prodSetup.until") : t("prodSetup.from")} {s.effective_from}: {label(s)} — {s.reason}
            </li>
          ))}
      </ul>
      {data.can_manage && (
        <form className="form-grid" aria-label={t("prodSetup.change")} onSubmit={submit}>
          <h3 className="wide">{t("prodSetup.change")}</h3>
          <label>
            {t("prodSetup.effectiveFrom")}
            <input type="date" value={values.effective_from} onChange={set("effective_from")} />
          </label>
          <label>
            {t("prodSetup.grace")}
            <input inputMode="decimal" value={values.grace_hours} onChange={set("grace_hours")} />
          </label>
          <label>
            {t("prodSetup.reject")}
            <input inputMode="decimal" value={values.reject_alert_pct} onChange={set("reject_alert_pct")} />
          </label>
          <label>
            {t("prodSetup.overrun")}
            <input inputMode="decimal" value={values.overrun_alert_pct} onChange={set("overrun_alert_pct")} />
          </label>
          <label>
            {t("prodSetup.margin")}
            <input inputMode="decimal" value={values.min_margin_pct} onChange={set("min_margin_pct")} />
          </label>
          <label className="wide">
            {t("prodSetup.reason")}
            <input value={values.reason} onChange={set("reason")} />
          </label>
          <div className="wide row-actions">
            <button type="submit" disabled={save.isPending}>
              {t("prodSetup.save")}
            </button>
          </div>
          <p className="muted wide">{t("prodSetup.changeHelp")}</p>
          <div className="wide">
            <ErrorLine error={save.error} />
          </div>
        </form>
      )}
    </section>
  );
}

function Reasons({ data, onDone }: { data: ProductionSetup; onDone: (d: ProductionSetup) => void }) {
  const { t } = useTranslation();
  const [division, setDivision] = useState(data.divisions[0] ?? "IM");
  const [kind, setKind] = useState<"reject" | "downtime">("downtime");
  const [values, setValues] = useState({ code: "", name: "", planned: false });
  const shown = data.reasons.filter((r) => r.division === division && r.kind === kind);
  const add = useMutation({
    mutationFn: () => addReason({ division, kind, ...values }),
    onSuccess: (d) => {
      setValues({ code: "", name: "", planned: false });
      onDone(d);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  return (
    <section className="panel" aria-label={t("prodSetup.reasons")}>
      <h2>{t("prodSetup.reasons")}</h2>
      <p className="muted">{t("prodSetup.reasonsHelp")}</p>
      <div className="inline-form">
        <label>
          {t("prodSetup.division")}
          <select value={division} onChange={(e) => setDivision(e.target.value)}>
            {data.divisions.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("prodSetup.kind")}
          <select value={kind} onChange={(e) => setKind(e.target.value as "reject" | "downtime")}>
            <option value="downtime">{t("prodSetup.downtime")}</option>
            <option value="reject">{t("prodSetup.rejectKind")}</option>
          </select>
        </label>
      </div>
      <table aria-label={t("prodSetup.reasons")}>
        <thead>
          <tr>
            <th>{t("prodSetup.code")}</th>
            <th>{t("prodSetup.name")}</th>
            {kind === "downtime" && <th>{t("prodSetup.planned")}</th>}
            <th>{t("prodSetup.active")}</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <ReasonRow key={r.id} reason={r} canManage={data.can_manage} onDone={onDone} />
          ))}
        </tbody>
      </table>
      {data.can_manage && (
        <form className="inline-form" aria-label={t("prodSetup.addReason")} onSubmit={submit}>
          <label>
            {t("prodSetup.code")}
            <input value={values.code} onChange={(e) => setValues({ ...values, code: e.target.value })} />
          </label>
          <label>
            {t("prodSetup.name")}
            <input value={values.name} onChange={(e) => setValues({ ...values, name: e.target.value })} />
          </label>
          {kind === "downtime" && (
            <label className="check">
              <input type="checkbox" checked={values.planned} onChange={(e) => setValues({ ...values, planned: e.target.checked })} />{" "}
              {t("prodSetup.planned")}
            </label>
          )}
          <button type="submit" disabled={add.isPending}>
            {t("prodSetup.addReason")}
          </button>
        </form>
      )}
      <ErrorLine error={add.error} />
    </section>
  );
}

function ReasonRow({ reason: r, canManage, onDone }: { reason: Reason; canManage: boolean; onDone: (d: ProductionSetup) => void }) {
  const { t } = useTranslation();
  const [name, setName] = useState(r.name);
  const save = useMutation({
    mutationFn: (values: Partial<Pick<Reason, "name" | "planned" | "is_active">>) => changeReason(r.id, values),
    onSuccess: onDone,
  });
  return (
    <tr className={r.is_active ? "" : "muted"}>
      <td>{r.code}</td>
      <td>
        {canManage ? (
          <input
            aria-label={t("prodSetup.nameOf", { code: r.code })}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => name !== r.name && save.mutate({ name })}
          />
        ) : (
          r.name
        )}
        <ErrorLine error={save.error} />
      </td>
      {r.kind === "downtime" && (
        <td>
          <input
            type="checkbox"
            aria-label={t("prodSetup.plannedOf", { code: r.code })}
            checked={r.planned}
            disabled={!canManage}
            onChange={(e) => save.mutate({ planned: e.target.checked })}
          />
        </td>
      )}
      <td>
        <input
          type="checkbox"
          aria-label={t("prodSetup.activeOf", { code: r.code })}
          checked={r.is_active}
          disabled={!canManage}
          onChange={(e) => save.mutate({ is_active: e.target.checked })}
        />
      </td>
    </tr>
  );
}
