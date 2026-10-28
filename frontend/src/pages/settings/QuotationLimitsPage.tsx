import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { can, canDo } from "../../api/access";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";
import {
  confirmLimit,
  limitsKey,
  listLimits,
  proposeLimit,
  rejectLimit,
  withdrawLimit,
  type QuotationLimit,
} from "../../api/limits";
import { divisionsAdminKey, listDivisionsAdmin } from "../../api/organisation";
import DataTable from "../../components/DataTable";
import { formatDecimal } from "../../lib/decimal";

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError && error.detail ? error.detail : fallback;
}

function ErrorLine({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return (
    <p className="form-error" role="alert">
      {errorText(error, t("common.error"))}
    </p>
  );
}

const localToday = () => new Date().toLocaleDateString("en-CA");
const pct = (value: string) => `${formatDecimal(value)}%`;

export default function QuotationLimitsPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const rows = useQuery({ queryKey: limitsKey, queryFn: listLimits });
  const divisions = useQuery({ queryKey: divisionsAdminKey, queryFn: listDivisionsAdmin });
  const canPropose = can(me.access, "settings", "manage");
  const canDecide = canDo(me.access, "confirm_limits");
  const pending = rows.data?.filter((r) => r.status === "pending") ?? [];
  const active = divisions.data?.filter((d) => d.is_active) ?? [];

  return (
    <main className="page">
      <h1>{t("limits.title")}</h1>
      <p className="muted">{t("limits.help")}</p>

      {rows.data && (
        <section className="panel">
          <h2>{t("limits.inForce")}</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("factory.division")}</th>
                  <th className="num">{t("limits.minMargin")}</th>
                  <th className="num">{t("limits.directorAbove")}</th>
                  <th>{t("limits.since")}</th>
                </tr>
              </thead>
              <tbody>
                {active.map((d) => {
                  const current = rows.data?.find((r) => r.division === d.code && r.in_force);
                  return (
                    <tr key={d.code}>
                      <td>
                        {d.code} {d.name}
                      </td>
                      <td className="num">{current ? pct(current.min_margin_pct) : "—"}</td>
                      <td className="num">
                        {current ? formatDecimal(current.director_above_lkr) : t("limits.notSet")}
                      </td>
                      <td>{current?.effective_from ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="muted">{t("limits.notSetHelp")}</p>
        </section>
      )}

      {pending.length > 0 && (
        <section className="panel" aria-label={t("limits.waiting")}>
          <h2>{t("limits.waiting")}</h2>
          {pending.map((limit) => (
            <PendingChange
              key={limit.id}
              limit={limit}
              canDecide={canDecide}
              mine={limit.created_by === me.email}
            />
          ))}
        </section>
      )}

      {canPropose && active.length > 0 && <ProposeForm divisions={active.map((d) => d.code)} />}

      {rows.data && (
        <section className="panel">
          <h2>{t("limits.history")}</h2>
          <DataTable
            label={t("limits.history")}
            rows={rows.data}
            rowKey={(r) => r.id}
            columns={[
              { id: "division", header: t("factory.division"), value: (r) => r.division },
              { id: "from", header: t("limits.from"), value: (r) => r.effective_from },
              { id: "margin", header: t("limits.minMargin"), value: (r) => pct(r.min_margin_pct) },
              {
                id: "value",
                header: t("limits.directorAbove"),
                value: (r) => r.director_above_lkr,
                cell: (r) => formatDecimal(r.director_above_lkr),
              },
              {
                id: "status",
                header: t("users.status"),
                value: (r) => t(`limits.status.${r.status}`),
                cell: (r) => (
                  <>
                    {t(`limits.status.${r.status}`)}
                    {r.in_force && <span className="tag">{t("limits.inForceTag")}</span>}
                  </>
                ),
              },
              { id: "by", header: t("limits.enteredBy"), value: (r) => r.created_by },
              { id: "decided", header: t("limits.decidedBy"), value: (r) => r.decided_by ?? "" },
              {
                id: "reason",
                header: t("access.reason"),
                value: (r) => [r.reason, r.decision_note].filter(Boolean).join(" / "),
              },
            ]}
          />
        </section>
      )}
    </main>
  );
}

function PendingChange(props: { limit: QuotationLimit; canDecide: boolean; mine: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { limit } = props;
  const [note, setNote] = useState("");
  const done = () => void queryClient.invalidateQueries({ queryKey: limitsKey });
  const confirm = useMutation({ mutationFn: () => confirmLimit(limit.id), onSuccess: done });
  const reject = useMutation({ mutationFn: () => rejectLimit(limit.id, note), onSuccess: done });
  const withdraw = useMutation({ mutationFn: () => withdrawLimit(limit.id), onSuccess: done });
  const label = t("limits.changeFor", { division: limit.division });

  return (
    <div className="pending-change" role="group" aria-label={label}>
      <p>
        <strong>{label}</strong>{" "}
        {t("limits.changeText", {
          from: limit.effective_from,
          margin: pct(limit.min_margin_pct),
          value: formatDecimal(limit.director_above_lkr),
          by: limit.created_by,
        })}
      </p>
      <p className="muted">
        {t("access.reason")}: {limit.reason}
      </p>
      <div className="row-actions">
        {props.canDecide && !props.mine && (
          <>
            <button type="button" onClick={() => confirm.mutate()}>
              {t("access.confirm")}
            </button>
            <input
              aria-label={t("limits.rejectReason")}
              placeholder={t("limits.rejectReason")}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <button type="button" className="danger" onClick={() => reject.mutate()}>
              {t("limits.reject")}
            </button>
          </>
        )}
        {props.mine && (
          <button type="button" className="secondary" onClick={() => withdraw.mutate()}>
            {t("limits.withdraw")}
          </button>
        )}
      </div>
      <ErrorLine error={confirm.error ?? reject.error ?? withdraw.error} />
    </div>
  );
}

function ProposeForm({ divisions }: { divisions: string[] }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [division, setDivision] = useState(divisions[0]);
  const [from, setFrom] = useState(localToday());
  const [margin, setMargin] = useState("");
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () =>
      proposeLimit({
        division,
        effective_from: from,
        min_margin_pct: margin,
        director_above_lkr: value,
        reason,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: limitsKey });
      setMargin("");
      setValue("");
      setReason("");
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <section className="panel" aria-label={t("limits.propose")}>
      <h2>{t("limits.propose")}</h2>
      <form className="inline-form" onSubmit={submit}>
        <label>
          {t("factory.division")}
          <select value={division} onChange={(e) => setDivision(e.target.value)}>
            {divisions.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("limits.from")}
          <input type="date" value={from} min={localToday()} required onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>
          {t("limits.minMargin")}
          <input inputMode="decimal" value={margin} required onChange={(e) => setMargin(e.target.value)} />
        </label>
        <label>
          {t("limits.directorAbove")}
          <input inputMode="decimal" value={value} required onChange={(e) => setValue(e.target.value)} />
        </label>
        <label>
          {t("access.reason")}
          <input value={reason} required onChange={(e) => setReason(e.target.value)} />
        </label>
        <button type="submit" disabled={save.isPending}>
          {t("limits.send")}
        </button>
      </form>
      <p className="muted">{t("limits.proposeHelp")}</p>
      <ErrorLine error={save.error} />
    </section>
  );
}
