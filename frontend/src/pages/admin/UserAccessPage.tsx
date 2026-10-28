import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import { can, canDo, type Level } from "../../api/access";
import {
  confirmOverride,
  copyAccess,
  createOverride,
  deactivateUser,
  getAccessGrid,
  listDivisions,
  listOverrides,
  listRoles,
  listUsers,
  reactivateUser,
  resetOverrides,
  revokeOverride,
  setUserRoles,
  setUserScope,
  type AccessGrid,
  type OverrideInfo,
  type UserRecord,
} from "../../api/admin";
import { getAuditLog } from "../../api/audit";
import type { CurrentUser } from "../../api/auth";
import { ApiError } from "../../api/client";
import AuditTable from "../../components/AuditTable";
import SectionScopePanel from "../../components/SectionScopePanel";

const LEVELS: Level[] = ["view", "enter", "approve", "manage"];

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError && error.detail ? error.detail : fallback;
}

function warningsOf(error: unknown): string[] {
  const body = error instanceof ApiError ? (error.body as { warnings?: string[] } | null) : null;
  return body?.warnings ?? [];
}

/** One cell of the access grid: what the roles give, any override, and the result. */
function cellMark(fromRoles: boolean, override: OverrideInfo | null, effective: boolean) {
  if (override?.status === "pending") return { mark: "…", kind: "pending" };
  if (override?.effect === "remove") return { mark: "−", kind: "removed" };
  if (override?.effect === "grant" && effective) return { mark: "+", kind: "granted" };
  if (effective && fromRoles) return { mark: "●", kind: "role" };
  return { mark: "", kind: "none" };
}

type Target = { area?: string; level?: Level; action?: string; label: string; held: boolean };

export default function UserAccessPage({ me }: { me: CurrentUser }) {
  const { t } = useTranslation();
  const id = Number(useParams().id);
  const queryClient = useQueryClient();

  const grid = useQuery({ queryKey: ["user-access", id], queryFn: () => getAccessGrid(id) });
  const overrides = useQuery({ queryKey: ["overrides", id], queryFn: () => listOverrides(id) });
  const canManage = can(me.access, "users", "manage");
  const canConfirm = canDo(me.access, "confirm_sensitive_grants");

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["user-access", id] });
    void queryClient.invalidateQueries({ queryKey: ["overrides", id] });
    void queryClient.invalidateQueries({ queryKey: ["users"] });
    void queryClient.invalidateQueries({ queryKey: ["audit"] });
  };

  if (grid.isPending) return <p className="page-message">{t("common.loading")}</p>;
  if (grid.isError) return <p className="page-message">{errorText(grid.error, t("common.error"))}</p>;

  const user = grid.data.user;
  const own = user.email === me.email;

  return (
    <main className="page">
      <p className="breadcrumb">
        <Link to="/">{t("app.name")}</Link> › <Link to="/admin/users">{t("users.title")}</Link>
      </p>
      <h1>{user.full_name}</h1>
      <p className="muted">
        {user.email} · {user.is_active ? t("users.active") : t("users.inactive")}
        {user.two_factor_required &&
          ` · ${user.two_factor_enabled ? t("access.twoFactorOn") : t("access.twoFactorOwed")}`}
      </p>
      {own && <p className="notice">{t("access.ownAccount")}</p>}

      {canManage && !own && <Lifecycle user={user} onDone={refresh} />}
      <RolesPanel user={user} editable={canManage && !own} onDone={refresh} />
      <ScopePanel user={user} editable={canManage && !own} onDone={refresh} />
      <SectionScopePanel userId={id} editable={canManage && !own} />
      <GridPanel grid={grid.data} userId={id} editable={canManage && !own} onDone={refresh} />

      <section className="panel">
        <h2>{t("access.overrides")}</h2>
        {overrides.data?.length === 0 && <p className="muted">{t("access.noOverrides")}</p>}
        {overrides.data && overrides.data.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("access.change")}</th>
                  <th>{t("access.reason")}</th>
                  <th>{t("access.until")}</th>
                  <th>{t("users.status")}</th>
                  <th>{t("access.by")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {overrides.data.map((o) => (
                  <tr key={o.id}>
                    <td>
                      {o.effect === "grant" ? "+" : "−"} {o.action || `${o.area} · ${o.level}`}
                    </td>
                    <td>{o.reason}</td>
                    <td>{o.ends_on ?? "—"}</td>
                    <td>{t(`access.status.${o.status}`)}</td>
                    <td>{o.created_by}</td>
                    <td className="row-actions">
                      {o.status === "pending" && canConfirm && (
                        <OverrideButton
                          label={t("access.confirm")}
                          run={() => confirmOverride(o.id)}
                          onDone={refresh}
                        />
                      )}
                      {(o.status === "active" || o.status === "pending") && canManage && !own && (
                        <OverrideButton
                          label={t("access.end")}
                          secondary
                          run={() => revokeOverride(o.id, "Ended by administrator")}
                          onDone={refresh}
                        />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {can(me.access, "audit_logs") && <AuditTrail userId={id} />}
    </main>
  );
}

function AuditTrail({ userId }: { userId: number }) {
  const { t } = useTranslation();
  const trail = useQuery({
    queryKey: ["audit", { user: userId }],
    queryFn: () => getAuditLog({ user: userId, limit: 50 }),
  });
  return (
    <section className="panel">
      <h2>{t("audit.trail")}</h2>
      {trail.data && <AuditTable rows={trail.data} />}
    </section>
  );
}

function OverrideButton(props: {
  label: string;
  secondary?: boolean;
  run: () => Promise<unknown>;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const action = useMutation({ mutationFn: props.run, onSuccess: props.onDone });
  return (
    <>
      <button
        type="button"
        className={props.secondary ? "secondary small" : "small"}
        disabled={action.isPending}
        onClick={() => action.mutate()}
      >
        {props.label}
      </button>
      {action.isError && (
        <span className="form-error" role="alert">
          {" "}
          {errorText(action.error, t("common.error"))}
        </span>
      )}
    </>
  );
}

function Lifecycle({ user, onDone }: { user: UserRecord; onDone: () => void }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState("");
  const [source, setSource] = useState("");
  const users = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const act = useMutation({
    mutationFn: (what: "deactivate" | "reactivate" | "reset" | "copy"): Promise<unknown> => {
      if (what === "deactivate") return deactivateUser(user.id, reason);
      if (what === "reactivate") return reactivateUser(user.id);
      if (what === "reset") return resetOverrides(user.id, reason);
      return copyAccess(user.id, Number(source), reason);
    },
    onSuccess: onDone,
  });

  return (
    <section className="panel">
      <h2>{t("access.account")}</h2>
      <div className="inline-form">
        <label>
          {t("access.reason")}
          <input value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        {user.is_active ? (
          <button type="button" className="danger" onClick={() => act.mutate("deactivate")}>
            {t("access.deactivate")}
          </button>
        ) : (
          <button type="button" onClick={() => act.mutate("reactivate")}>
            {t("access.reactivate")}
          </button>
        )}
        <button type="button" className="secondary" onClick={() => act.mutate("reset")}>
          {t("access.reset")}
        </button>
      </div>
      <div className="inline-form">
        <label>
          {t("access.copyFrom")}
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">—</option>
            {users.data
              ?.filter((u) => u.id !== user.id)
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name} ({u.email})
                </option>
              ))}
          </select>
        </label>
        <button
          type="button"
          className="secondary"
          disabled={!source}
          onClick={() => act.mutate("copy")}
        >
          {t("access.copy")}
        </button>
      </div>
      {act.isError && (
        <p className="form-error" role="alert">
          {errorText(act.error, t("common.error"))}
        </p>
      )}
    </section>
  );
}

function RolesPanel(props: { user: UserRecord; editable: boolean; onDone: () => void }) {
  const { t } = useTranslation();
  const roles = useQuery({ queryKey: ["roles"], queryFn: listRoles });
  const [chosen, setChosen] = useState<string[]>(props.user.roles.map((r) => r.code));
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => setUserRoles(props.user.id, chosen, reason),
    onSuccess: props.onDone,
  });
  const warnings = warningsOf(save.error);

  function toggle(code: string) {
    setChosen((now) => (now.includes(code) ? now.filter((c) => c !== code) : [...now, code]));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <section className="panel">
      <h2>{t("users.roles")}</h2>
      <form onSubmit={submit}>
        <div className="checks">
          {roles.data
            ?.filter((r) => r.is_active || chosen.includes(r.code))
            .map((r) => (
              <label key={r.code} className="check">
                <input
                  type="checkbox"
                  checked={chosen.includes(r.code)}
                  disabled={!props.editable}
                  onChange={() => toggle(r.code)}
                />
                {r.name}
              </label>
            ))}
        </div>
        {props.editable && (
          <div className="inline-form">
            <label>
              {t("access.reason")}
              <input value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            <button type="submit" disabled={save.isPending}>
              {t("access.saveRoles")}
            </button>
          </div>
        )}
        {save.isError && (
          <div className="form-error" role="alert">
            <p>{errorText(save.error, t("common.error"))}</p>
            {warnings.length > 0 && (
              <ul>
                {warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        {save.isSuccess && save.data.warnings.length > 0 && (
          <p className="notice">{t("access.savedWithWarnings")}</p>
        )}
      </form>
    </section>
  );
}

function ScopePanel(props: { user: UserRecord; editable: boolean; onDone: () => void }) {
  const { t } = useTranslation();
  const divisions = useQuery({ queryKey: ["divisions"], queryFn: listDivisions });
  const [all, setAll] = useState(props.user.all_divisions);
  const [chosen, setChosen] = useState<string[]>(props.user.divisions);
  const save = useMutation({
    mutationFn: () => setUserScope(props.user.id, all, all ? [] : chosen),
    onSuccess: props.onDone,
  });

  return (
    <section className="panel">
      <h2>{t("users.divisions")}</h2>
      <div className="checks">
        <label className="check">
          <input
            type="checkbox"
            checked={all}
            disabled={!props.editable}
            onChange={(e) => setAll(e.target.checked)}
          />
          {t("users.allDivisions")}
        </label>
        {divisions.data?.map((d) => (
          <label key={d.code} className="check">
            <input
              type="checkbox"
              checked={all || chosen.includes(d.code)}
              disabled={!props.editable || all}
              onChange={() =>
                setChosen((now) =>
                  now.includes(d.code) ? now.filter((c) => c !== d.code) : [...now, d.code],
                )
              }
            />
            {d.code} {d.name}
          </label>
        ))}
      </div>
      {props.editable && (
        <button type="button" disabled={save.isPending} onClick={() => save.mutate()}>
          {t("access.saveDivisions")}
        </button>
      )}
      {save.isError && (
        <p className="form-error" role="alert">
          {errorText(save.error, t("common.error"))}
        </p>
      )}
    </section>
  );
}

function GridPanel(props: {
  grid: AccessGrid;
  userId: number;
  editable: boolean;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [target, setTarget] = useState<Target | null>(null);
  const [reason, setReason] = useState("");
  const [endsOn, setEndsOn] = useState("");
  const save = useMutation({
    mutationFn: () =>
      createOverride(props.userId, {
        effect: target!.held ? "remove" : "grant",
        area: target!.area ?? "",
        level: target!.level ?? "",
        action: target!.action ?? "",
        reason,
        ends_on: endsOn || null,
      }),
    onSuccess: () => {
      setTarget(null);
      setReason("");
      setEndsOn("");
      props.onDone();
    },
  });

  function pick(next: Target) {
    if (!props.editable) return;
    save.reset();
    setTarget(next);
  }

  return (
    <section className="panel">
      <h2>{t("access.effective")}</h2>
      <p className="muted">{t("access.legend")}</p>
      <div className="table-wrap">
        <table className="grid">
          <thead>
            <tr>
              <th>{t("access.area")}</th>
              {LEVELS.map((level) => (
                <th key={level}>{t(`access.level.${level}`)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {props.grid.areas.map((row) => (
              <tr key={row.area}>
                <th scope="row">{row.label}</th>
                {row.levels.map((cell) => {
                  const { mark, kind } = cellMark(cell.from_roles, cell.override, cell.effective);
                  return (
                    <td key={cell.level} className={`cell ${kind}`}>
                      <button
                        type="button"
                        className="cell-button"
                        disabled={!props.editable}
                        aria-label={`${row.label}: ${t(`access.level.${cell.level}`)}`}
                        onClick={() =>
                          pick({
                            area: row.area,
                            level: cell.level,
                            label: `${row.label} · ${t(`access.level.${cell.level}`)}`,
                            held: cell.effective,
                          })
                        }
                      >
                        {mark}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>{t("access.actions")}</h3>
      <ul className="action-list">
        {props.grid.actions.map((a) => {
          const { mark, kind } = cellMark(a.from_roles, a.override, a.effective);
          return (
            <li key={a.action} className={`cell ${kind}`}>
              <button
                type="button"
                className="cell-button"
                disabled={!props.editable}
                onClick={() => pick({ action: a.action, label: a.label, held: a.effective })}
              >
                {mark || "○"}
              </button>{" "}
              {a.label}
            </li>
          );
        })}
      </ul>

      {target && (
        <form
          className="override-form"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <h3>
            {target.held ? t("access.removeTitle") : t("access.grantTitle")}: {target.label}
          </h3>
          <label>
            {t("access.reason")}
            <input value={reason} onChange={(e) => setReason(e.target.value)} required />
          </label>
          <label>
            {t("access.until")}
            <input type="date" value={endsOn} onChange={(e) => setEndsOn(e.target.value)} />
          </label>
          <div className="inline-form">
            <button type="submit" disabled={save.isPending}>
              {target.held ? t("access.remove") : t("access.grant")}
            </button>
            <button type="button" className="secondary" onClick={() => setTarget(null)}>
              {t("access.cancel")}
            </button>
          </div>
          {save.isError && (
            <p className="form-error" role="alert">
              {errorText(save.error, t("common.error"))}
            </p>
          )}
        </form>
      )}
      {save.isSuccess && save.data.status === "pending" && (
        <p className="notice" role="status">
          {t("access.waitingForDirector")}
        </p>
      )}
    </section>
  );
}
