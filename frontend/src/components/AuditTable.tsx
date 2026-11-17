import { useTranslation } from "react-i18next";

import type { AuditEvent } from "../api/audit";
import { formatDateTime } from "../lib/time";

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

/** "password_reset_requested" → "Password reset requested": plain words for an event that has
 * no wording of its own yet (owner, 16 Nov 2026: raw event names showed in the trail). */
export function eventWords(event: string): string {
  const words = event.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Audit rows, newest first: when, who, what, and each field's old → new value. */
export default function AuditTable({ rows }: { rows: AuditEvent[] }) {
  const { t } = useTranslation();
  if (rows.length === 0) return <p className="muted">{t("audit.none")}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{t("audit.when")}</th>
            <th>{t("audit.who")}</th>
            <th>{t("audit.what")}</th>
            <th>{t("audit.changes")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{formatDateTime(row.occurred_at)}</td>
              <td>
                {row.actor_email}
                {row.ip_address && <div className="muted">{row.ip_address}</div>}
              </td>
              <td>
                <strong>{row.event ? t(`audit.event.${row.event}`, eventWords(row.event)) : t(`audit.action.${row.action}`)}</strong>
                <div>{row.object_repr}</div>
                {row.reason && <div className="muted">{t("audit.reason", { reason: row.reason })}</div>}
              </td>
              <td>
                <ul className="changes">
                  {Object.entries(row.changes).map(([field, [before, after]]) => (
                    <li key={field}>
                      <code>{field}</code>: {show(before)} → {show(after)}
                    </li>
                  ))}
                </ul>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
