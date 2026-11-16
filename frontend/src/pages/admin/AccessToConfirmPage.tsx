import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import {
  accessToConfirmKey,
  confirmOverride,
  confirmRole,
  decidePasswordReset,
  getAccessToConfirm,
  refuseRole,
  revokeOverride,
} from "../../api/admin";
import { ApiError } from "../../api/client";
import { waitingKey } from "../../api/waiting";
import { formatDateTime } from "../../lib/time";

function errorText(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.detail ? error.detail : fallback;
}

/** Access to confirm (owner, 15 Nov 2026): every new role, sensitive extra access and password
 * reset the Admin asked for, waiting for the Director. Confirm, or refuse with a reason. A
 * person never decides what they asked for or what is for themselves (the server checks). */
export default function AccessToConfirmPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const data = useQuery({ queryKey: accessToConfirmKey, queryFn: getAccessToConfirm });
  const [done, setDone] = useState("");
  const refresh = (message: string) => {
    setDone(message);
    void queryClient.invalidateQueries({ queryKey: accessToConfirmKey });
    void queryClient.invalidateQueries({ queryKey: waitingKey });
  };
  const act = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
  });
  const d = data.data;
  const empty = d && d.roles.length + d.grants.length + d.resets.length === 0;

  return (
    <main className="page">
      <h1>{t("atc.title")}</h1>
      <p className="muted">{t("atc.help")}</p>
      {done && (
        <p className="notice" role="status">
          {done}
        </p>
      )}
      {act.isError && (
        <p className="form-error" role="alert">
          {errorText(act.error, t("common.error"))}
        </p>
      )}
      {empty && <p className="muted">{t("atc.none")}</p>}

      {d && d.roles.length > 0 && (
        <section className="panel" aria-label={t("atc.roles")}>
          <h2>{t("atc.roles")}</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("atc.person")}</th>
                  <th>{t("atc.role")}</th>
                  <th>{t("atc.askedBy")}</th>
                  <th>{t("access.reason")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {d.roles.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link to={`/admin/users/${r.user_id}`}>{r.user}</Link>
                    </td>
                    <td>
                      {r.name}
                      {r.conflict_warning && <p className="warning-text">{r.conflict_warning}</p>}
                    </td>
                    <td>
                      {r.requested_by} <span className="muted">{formatDateTime(r.requested_at)}</span>
                    </td>
                    <td>{r.reason}</td>
                    <td className="row-actions">
                      {d.can_confirm && !r.mine && (
                        <>
                          <button
                            type="button"
                            disabled={act.isPending}
                            onClick={() =>
                              act.mutate(() => confirmRole(r.id), {
                                onSuccess: () => refresh(t("atc.roleConfirmed", { role: r.name, name: r.user })),
                              })
                            }
                          >
                            {t("atc.confirm")}
                          </button>
                          <Refuse
                            label={t("atc.refuse")}
                            pending={act.isPending}
                            onRemove={(reason) =>
                              act.mutate(() => refuseRole(r.id, reason), {
                                onSuccess: () => refresh(t("atc.roleRefused", { role: r.name, name: r.user })),
                              })
                            }
                          />
                        </>
                      )}
                      {r.mine && <span className="muted">{t("atc.notYours")}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {d && d.grants.length > 0 && (
        <section className="panel" aria-label={t("atc.grants")}>
          <h2>{t("atc.grants")}</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("atc.person")}</th>
                  <th>{t("atc.what")}</th>
                  <th>{t("atc.askedBy")}</th>
                  <th>{t("access.reason")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {d.grants.map((g) => (
                  <tr key={g.id}>
                    <td>
                      <Link to={`/admin/users/${g.user_id}`}>{g.user_name}</Link>
                    </td>
                    <td>
                      {g.action || `${g.area}: ${g.level}`}
                      {g.ends_on && <span className="muted"> · {t("atc.until", { date: g.ends_on })}</span>}
                    </td>
                    <td>{g.created_by}</td>
                    <td>{g.reason}</td>
                    <td className="row-actions">
                      {d.can_confirm && !g.mine && (
                        <>
                          <button
                            type="button"
                            disabled={act.isPending}
                            onClick={() =>
                              act.mutate(() => confirmOverride(g.id), {
                                onSuccess: () => refresh(t("atc.grantConfirmed", { name: g.user_name })),
                              })
                            }
                          >
                            {t("atc.confirm")}
                          </button>
                          <Refuse
                            label={t("atc.refuse")}
                            pending={act.isPending}
                            onRemove={(reason) =>
                              act.mutate(() => revokeOverride(g.id, reason), {
                                onSuccess: () => refresh(t("atc.grantRefused", { name: g.user_name })),
                              })
                            }
                          />
                        </>
                      )}
                      {g.mine && <span className="muted">{t("atc.notYours")}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {d && d.resets.length > 0 && (
        <section className="panel" aria-label={t("atc.resets")}>
          <h2>{t("atc.resets")}</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("atc.person")}</th>
                  <th>{t("atc.what")}</th>
                  <th>{t("atc.askedBy")}</th>
                  <th>{t("access.reason")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {d.resets.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link to={`/admin/users/${r.user_id}`}>{r.user_name}</Link>
                    </td>
                    <td>{r.with_authenticator ? t("atc.resetBoth") : t("atc.resetPassword")}</td>
                    <td>{r.requested_by}</td>
                    <td>{r.reason}</td>
                    <td className="row-actions">
                      {r.can_decide ? (
                        <>
                          <button
                            type="button"
                            disabled={act.isPending}
                            onClick={() =>
                              act.mutate(() => decidePasswordReset(r.id, true, ""), {
                                onSuccess: () => refresh(t("atc.resetApproved", { name: r.user_name })),
                              })
                            }
                          >
                            {t("atc.approve")}
                          </button>
                          <Refuse
                            label={t("atc.refuse")}
                            pending={act.isPending}
                            onRemove={(reason) =>
                              act.mutate(() => decidePasswordReset(r.id, false, reason), {
                                onSuccess: () => refresh(t("atc.resetRefused", { name: r.user_name })),
                              })
                            }
                          />
                        </>
                      ) : (
                        <span className="muted">{t("atc.notYours")}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </main>
  );
}

/** Refuse, asking the reason in place. */
function Refuse({ label, pending, onRemove }: { label: string; pending: boolean; onRemove: (reason: string) => void }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  if (!open) {
    return (
      <button type="button" className="secondary" onClick={() => setOpen(true)}>
        {label}
      </button>
    );
  }
  return (
    <span className="inline-form">
      <label>
        {t("atc.refuseReason")}
        <input value={reason} autoFocus onChange={(e) => setReason(e.target.value)} />
      </label>
      <button type="button" className="danger" disabled={pending || !reason.trim()} onClick={() => onRemove(reason.trim())}>
        {label}
      </button>
      <button type="button" className="secondary" onClick={() => setOpen(false)}>
        {t("access.cancel")}
      </button>
    </span>
  );
}
